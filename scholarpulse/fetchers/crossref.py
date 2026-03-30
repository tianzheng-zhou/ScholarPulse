"""CrossRef 辅助层：元数据补全与引用数获取（非主要抓取源）"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import httpx
from sqlalchemy.orm import Session

from ..database import Paper

logger = logging.getLogger(__name__)

API_BASE = "https://api.crossref.org"
# polite pool: 设 mailto 可提升速率到 ~50 req/s
USER_AGENT = "ScholarPulse/0.1 (mailto:{email})"


class CrossRefEnricher:
    """CrossRef 辅助工具：补全引用数和期刊元数据，不作为主要抓取源。"""

    def __init__(self, email: str = "") -> None:
        self.email = email

    async def enrich_papers(self, db: Session, limit: int = 100) -> int:
        """
        为数据库中有 DOI 但缺引用数的论文从 CrossRef 补全元数据。
        返回成功补全的论文数。
        """
        papers = (
            db.query(Paper)
            .filter(
                Paper.doi.isnot(None),
                Paper.doi != "",
                Paper.citation_count.is_(None),
            )
            .limit(limit)
            .all()
        )

        if not papers:
            logger.info("CrossRef: 没有需要补全的论文")
            return 0

        enriched = 0
        headers = {}
        if self.email:
            headers["User-Agent"] = USER_AGENT.format(email=self.email)

        async with httpx.AsyncClient(timeout=20.0, follow_redirects=True, headers=headers) as client:
            for paper in papers:
                try:
                    metadata = await self._fetch_by_doi(client, paper.doi)
                    if metadata:
                        self._apply_metadata(paper, metadata)
                        enriched += 1
                except Exception:
                    logger.debug("CrossRef 查询 DOI %s 失败", paper.doi)

                await asyncio.sleep(0.1 if self.email else 1.0)

        db.commit()
        logger.info("CrossRef: 补全了 %d 篇论文的元数据", enriched)
        return enriched

    async def _fetch_by_doi(
        self, client: httpx.AsyncClient, doi: str
    ) -> dict[str, Any] | None:
        resp = await client.get(f"{API_BASE}/works/{doi}")
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        data = resp.json()
        return data.get("message")

    @staticmethod
    def _apply_metadata(paper: Paper, metadata: dict[str, Any]) -> None:
        """将 CrossRef 元数据应用到论文记录"""
        # 引用次数
        cite_count = metadata.get("is-referenced-by-count")
        if cite_count is not None:
            paper.citation_count = cite_count

        # 期刊名补全（如果论文缺期刊信息）
        if not paper.journal:
            container = metadata.get("container-title", [])
            if container:
                paper.journal = container[0]
