"""定时调度器：管理论文抓取和 AI 处理的定时任务"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime
from typing import Any

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from .ai.summarizer import AISummarizer
from .config import AppConfig
from .database import Paper, SessionLocal, get_db
from .fetchers.arxiv import ArxivFetcher
from .fetchers.semantic_scholar import SemanticScholarFetcher
from .journal_ranks import lookup_journal_rank

logger = logging.getLogger(__name__)


async def run_fetch_job(config: AppConfig, days: int | None = None) -> dict[str, Any]:
    """执行一次抓取 + AI 处理流程，返回统计信息"""
    fetch_days = days if days is not None else config.scheduler.fetch_days
    stats: dict[str, Any] = {"fetchers": {}, "ai_processed": 0}

    db = SessionLocal()
    try:
        # ── 1. 抓取论文（days=0 时跳过抓取，仅做 AI 处理）──
        if fetch_days > 0:
            fetchers: list[tuple[str, Any]] = []

            ss_cfg = config.sources.get("semantic_scholar")
            if ss_cfg and ss_cfg.enabled:
                fetchers.append(("semantic_scholar", SemanticScholarFetcher()))

            arxiv_cfg = config.sources.get("arxiv")
            if arxiv_cfg and arxiv_cfg.enabled:
                fetchers.append(
                    ("arxiv", ArxivFetcher(categories=arxiv_cfg.categories))
                )

            for name, fetcher in fetchers:
                started = datetime.utcnow()
                try:
                    raw_papers = await fetcher.fetch(
                        keywords=config.keywords, days=fetch_days
                    )
                    found, new = fetcher.save_papers(db, raw_papers)
                    fetcher.log_fetch(db, started, found, new, status="success")
                    stats["fetchers"][name] = {"found": found, "new": new}
                    logger.info(
                        "%s: 发现 %d 篇，新增 %d 篇", name, found, new
                    )
                except Exception as e:
                    logger.exception("抓取器 %s 失败", name)
                    fetcher.log_fetch(
                        db, started, 0, 0, status="error", error_message=str(e)
                    )
                    stats["fetchers"][name] = {"error": str(e)}

            # ── 2. 期刊分级标签 ──
            unranked = db.query(Paper).filter(Paper.journal_rank.is_(None), Paper.journal.isnot(None)).all()
            for paper in unranked:
                if paper.journal:
                    rank = lookup_journal_rank(paper.journal)
                    if rank:
                        paper.set_journal_rank(rank.to_dict())
            db.commit()

        # ── 3. AI 处理 ──
        unprocessed = (
            db.query(Paper)
            .filter(Paper.ai_processed == False)  # noqa: E712
            .all()
        )

        if unprocessed and config.llm.api_key:
            summarizer = AISummarizer(config)
            total = len(unprocessed)
            # 收集需要处理的 paper id 列表（避免在并发中共享 session）
            paper_ids = [p.id for p in unprocessed]
            processed_count = 0

            async def _process_one(paper_id: int) -> None:
                nonlocal processed_count
                # 每篇论文使用独立 session，避免并发 commit/rollback 互相干扰
                sess = SessionLocal()
                try:
                    paper = sess.query(Paper).get(paper_id)
                    if not paper or paper.ai_processed:
                        return
                    result = await summarizer.process_paper(
                        title=paper.title,
                        abstract=paper.abstract or "",
                        journal=paper.journal or "",
                    )
                    if result:
                        paper.title_zh = result.get("title_zh", "")
                        paper.summary_zh = result.get("summary_zh", "")
                        paper.relevance_score = result.get("relevance_score")
                        paper.relevance_reason = result.get("relevance_reason", "")
                        if result.get("keywords"):
                            paper.set_keywords(result["keywords"])
                        paper.ai_processed = True
                        sess.commit()
                        processed_count += 1
                        stats["ai_processed"] = processed_count
                        if processed_count % 50 == 0:
                            logger.info(
                                "AI 处理进度: %d/%d (%.0f%%)",
                                processed_count, total,
                                processed_count / total * 100,
                            )
                except Exception:
                    logger.exception("AI 处理论文 %d 失败", paper_id)
                    sess.rollback()
                finally:
                    sess.close()

            # 并发处理（由 AISummarizer 内部 semaphore 控制并发数）
            await asyncio.gather(*[_process_one(pid) for pid in paper_ids])

            logger.info("AI 处理完成: %d/%d 篇", processed_count, total)

    finally:
        db.close()

    return stats


class Scheduler:
    """定时调度管理器"""

    def __init__(self, config: AppConfig) -> None:
        self.config = config
        self._scheduler = AsyncIOScheduler()
        self._running = False

    def start(self) -> None:
        if not self.config.scheduler.enabled:
            logger.info("调度器已禁用")
            return

        cron_expr = self.config.scheduler.cron
        parts = cron_expr.split()
        if len(parts) == 5:
            minute, hour, day, month, dow = parts
            trigger = CronTrigger(
                minute=minute, hour=hour, day=day, month=month, day_of_week=dow
            )
        else:
            trigger = CronTrigger(hour=8, minute=0)

        self._scheduler.add_job(
            self._job_wrapper,
            trigger=trigger,
            id="daily_fetch",
            replace_existing=True,
        )
        self._scheduler.start()
        self._running = True
        logger.info("调度器已启动，cron: %s", cron_expr)

    def stop(self) -> None:
        if self._running:
            self._scheduler.shutdown(wait=False)
            self._running = False
            logger.info("调度器已停止")

    async def _job_wrapper(self) -> None:
        logger.info("定时任务开始执行")
        try:
            stats = await run_fetch_job(self.config)
            logger.info("定时任务完成: %s", stats)
        except Exception:
            logger.exception("定时任务执行失败")
