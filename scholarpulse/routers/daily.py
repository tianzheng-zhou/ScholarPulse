"""论文库 + 日报路由"""

from __future__ import annotations

import hashlib
import json
import logging
import math
import time
from collections import OrderedDict
from datetime import date, datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, or_, text
from sqlalchemy.orm import Session

from ..ai.embedding import (
    build_paper_text,
    cosine_similarity_batch,
    deserialize_embedding,
    generate_embedding,
    rerank,
)
from ..config import BASE_DIR
from ..database import Paper, SessionLocal
from ..journal_ranks import get_journal_weight, lookup_journal_rank

logger = logging.getLogger(__name__)

router = APIRouter()
templates = Jinja2Templates(directory=str(BASE_DIR / "scholarpulse" / "templates"))

PAGE_SIZE = 30

# ── 语义搜索结果缓存 ──
# key: 查询参数哈希 → value: (paper_id 排序列表, 时间戳)
_semantic_cache: OrderedDict[str, tuple[list[int], float]] = OrderedDict()
_CACHE_MAX = 50  # 最多缓存 50 个查询
_CACHE_TTL = 300  # 5 分钟过期


def _cache_key(q: str, source: str | None, score: float | None, status: str | None) -> str:
    raw = f"{q}|{source}|{score}|{status}"
    return hashlib.md5(raw.encode()).hexdigest()


def _cache_get(key: str) -> list[int] | None:
    entry = _semantic_cache.get(key)
    if entry is None:
        return None
    ids, ts = entry
    if time.monotonic() - ts > _CACHE_TTL:
        _semantic_cache.pop(key, None)
        return None
    _semantic_cache.move_to_end(key)
    return ids


def _cache_set(key: str, ids: list[int]) -> None:
    _semantic_cache[key] = (ids, time.monotonic())
    while len(_semantic_cache) > _CACHE_MAX:
        _semantic_cache.popitem(last=False)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# ────────────────────────────────────────────────────────
# 论文库主页（分页 + 搜索 + 筛选）
# ────────────────────────────────────────────────────────

@router.get("/", response_class=HTMLResponse)
async def library_index(
    request: Request,
    q: str | None = None,
    source: str | None = None,
    min_score: str | None = None,
    status: str | None = None,
    sort: str | None = None,
    search_mode: str | None = None,
    page: int = 1,
    db: Session = Depends(get_db),
):
    """论文库主页：所有论文的分页浏览、搜索（支持关键词 / 语义搜索）"""
    score_filter: float | None = None
    if min_score:
        try:
            score_filter = float(min_score)
        except ValueError:
            score_filter = None

    # 判断是否有可用的向量数据
    has_embeddings = db.query(Paper).filter(Paper.embedding.isnot(None)).count() > 0
    # 默认搜索模式：有向量时用语义搜索，否则用关键词
    if search_mode is None:
        search_mode = "semantic" if has_embeddings else "keyword"
    use_semantic = (search_mode == "semantic") and q and has_embeddings

    # ── 公共基础查询（不含文本搜索）──
    base_query = db.query(Paper)

    # 来源筛选
    if source:
        base_query = base_query.filter(Paper.sources.like(f'%"{source}"%'))
    # 评分筛选
    if score_filter is not None:
        base_query = base_query.filter(Paper.relevance_score >= score_filter)
    # 处理状态筛选
    if status == "processed":
        base_query = base_query.filter(Paper.ai_processed == True)  # noqa: E712
    elif status == "unprocessed":
        base_query = base_query.filter(Paper.ai_processed == False, (Paper.ai_fail_count < 3) | (Paper.ai_fail_count.is_(None)))  # noqa: E712
    elif status == "failed":
        base_query = base_query.filter(Paper.ai_fail_count >= 3)

    papers: list[Any] = []
    total = 0

    if use_semantic:
        # ── 语义搜索路径（带缓存）──
        ck = _cache_key(q, source, score_filter, status)
        cached_ids = _cache_get(ck)

        if cached_ids is not None:
            # 缓存命中：直接按已排序的 ID 分页查询
            total = len(cached_ids)
            total_pages = max(1, math.ceil(total / PAGE_SIZE))
            page = max(1, min(page, total_pages))
            page_ids = cached_ids[(page - 1) * PAGE_SIZE : page * PAGE_SIZE]
            if page_ids:
                id_to_paper = {
                    p.id: p
                    for p in db.query(Paper).filter(Paper.id.in_(page_ids)).all()
                }
                papers = [id_to_paper[pid] for pid in page_ids if pid in id_to_paper]
            else:
                papers = []
        else:
            # 缓存未命中：执行完整语义搜索
            try:
                query_vec = await generate_embedding(
                    q,
                    instruct="Represent the search query for finding relevant academic papers",
                )
            except Exception:
                logger.exception("查询向量生成失败，回退到关键词搜索")
                query_vec = None

            if query_vec is not None:
                # 加载所有有向量的论文（已应用筛选条件）
                candidates = (
                    base_query
                    .filter(Paper.embedding.isnot(None))
                    .all()
                )

                if candidates:
                    # 计算余弦相似度
                    emb_list = [deserialize_embedding(p.embedding) for p in candidates]
                    sims = cosine_similarity_batch(query_vec, emb_list)

                    # 按相似度降序，取 top 100 用于重排序
                    scored = sorted(
                        zip(candidates, sims), key=lambda x: x[1], reverse=True
                    )
                    top_n_for_rerank = 100
                    top_candidates = scored[:top_n_for_rerank]

                    # 重排序
                    rerank_docs = [
                        build_paper_text(p.title, p.abstract)
                        for p, _ in top_candidates
                    ]
                    try:
                        rerank_results = await rerank(
                            q, rerank_docs, top_n=top_n_for_rerank
                        )
                    except Exception:
                        logger.exception("重排序失败，使用向量相似度排序")
                        rerank_results = []

                    if rerank_results:
                        ordered_ids = [
                            top_candidates[r["index"]][0].id
                            for r in rerank_results
                        ]
                    else:
                        ordered_ids = [p.id for p, _ in top_candidates]

                    # 写入缓存
                    _cache_set(ck, ordered_ids)

                    total = len(ordered_ids)
                    total_pages = max(1, math.ceil(total / PAGE_SIZE))
                    page = max(1, min(page, total_pages))
                    page_ids = ordered_ids[(page - 1) * PAGE_SIZE : page * PAGE_SIZE]
                    id_to_paper = {
                        p.id: p
                        for p in db.query(Paper).filter(Paper.id.in_(page_ids)).all()
                    }
                    papers = [id_to_paper[pid] for pid in page_ids if pid in id_to_paper]
                else:
                    total = 0
                    total_pages = 1
            else:
                # 向量生成失败，回退到关键词
                use_semantic = False

    if not use_semantic:
        # ── 关键词搜索路径（原逻辑）──
        query_obj = base_query
        if q:
            like_q = f"%{q}%"
            query_obj = query_obj.filter(
                or_(
                    Paper.title.ilike(like_q),
                    Paper.title_zh.ilike(like_q),
                    Paper.abstract.ilike(like_q),
                    Paper.keywords.ilike(like_q),
                )
            )

        # 排序
        if sort == "score":
            query_obj = query_obj.order_by(Paper.relevance_score.desc().nullslast())
        elif sort == "date_asc":
            query_obj = query_obj.order_by(Paper.published_date.asc().nullslast())
        else:
            query_obj = query_obj.order_by(Paper.published_date.desc().nullslast())

        total = query_obj.count()
        total_pages = max(1, math.ceil(total / PAGE_SIZE))
        page = max(1, min(page, total_pages))
        papers = query_obj.offset((page - 1) * PAGE_SIZE).limit(PAGE_SIZE).all()

    # 可用来源列表
    sources_rows = db.execute(
        text("SELECT DISTINCT value FROM papers, json_each(papers.sources) WHERE papers.sources IS NOT NULL")
    ).fetchall()
    available_sources = sorted(r[0] for r in sources_rows)

    # 统计概要
    total_all = db.query(Paper).count()
    processed_count = db.query(Paper).filter(Paper.ai_processed == True).count()  # noqa: E712
    failed_count = db.query(Paper).filter(Paper.ai_fail_count >= 3).count()
    unprocessed_count = total_all - processed_count - failed_count
    embedding_count = db.query(Paper).filter(Paper.embedding.isnot(None)).count()

    return templates.TemplateResponse(
        request,
        "library.html",
        {
            "papers": papers,
            "page": page,
            "total_pages": total_pages,
            "total": total,
            "total_all": total_all,
            "processed_count": processed_count,
            "failed_count": failed_count,
            "unprocessed_count": unprocessed_count,
            "embedding_count": embedding_count,
            "query": q or "",
            "current_source": source,
            "current_min_score": score_filter,
            "current_status": status,
            "current_sort": sort or "date_desc",
            "current_search_mode": search_mode,
            "has_embeddings": has_embeddings,
            "sources": available_sources,
            "json": json,
        },
    )


# ────────────────────────────────────────────────────────
# 日报视图（按 published_date 分组）
# ────────────────────────────────────────────────────────

@router.get("/daily", response_class=HTMLResponse)
@router.get("/daily/{d}", response_class=HTMLResponse)
async def daily_view(
    request: Request,
    d: str | None = None,
    source: str | None = None,
    min_score: str | None = None,
    page: int = 1,
    db: Session = Depends(get_db),
):
    """日报视图：按论文发表日期浏览"""
    score_filter: float | None = None
    if min_score:
        try:
            score_filter = float(min_score)
        except ValueError:
            score_filter = None

    # 确定日期
    if d:
        try:
            target_date = date.fromisoformat(d)
        except ValueError:
            target_date = date.today()
    else:
        # 默认找最近有数据的日期
        latest = (
            db.query(Paper.published_date)
            .filter(Paper.published_date.isnot(None))
            .order_by(Paper.published_date.desc())
            .first()
        )
        target_date = latest[0] if latest else date.today()

    prev_date = target_date - timedelta(days=1)
    next_date = target_date + timedelta(days=1)

    # 查询当天发表的论文
    query = db.query(Paper).filter(Paper.published_date == target_date)

    if source:
        query = query.filter(Paper.sources.like(f'%"{source}"%'))
    if score_filter is not None:
        query = query.filter(Paper.relevance_score >= score_filter)

    papers = query.all()

    # 排序：相关性评分 × 期刊权重
    def sort_key(p: Paper) -> float:
        score = p.relevance_score or 0
        rank = lookup_journal_rank(p.journal or "")
        weight = get_journal_weight(rank)
        return score * weight

    papers.sort(key=sort_key, reverse=True)

    # 分页
    total_count = len(papers)
    total_pages = max(1, math.ceil(total_count / PAGE_SIZE))
    page = max(1, min(page, total_pages))
    papers = papers[(page - 1) * PAGE_SIZE : page * PAGE_SIZE]

    # 可用来源列表（从 sources JSON 数组提取所有不重复来源）
    sources_rows = db.execute(
        text("SELECT DISTINCT value FROM papers, json_each(papers.sources) WHERE papers.sources IS NOT NULL")
    ).fetchall()
    available_sources = sorted(r[0] for r in sources_rows)

    # 获取有数据的日期列表（最近 30 天有论文的日期）
    date_counts = (
        db.query(Paper.published_date, func.count(Paper.id))
        .filter(Paper.published_date.isnot(None))
        .group_by(Paper.published_date)
        .order_by(Paper.published_date.desc())
        .limit(30)
        .all()
    )

    return templates.TemplateResponse(
        request,
        "daily.html",
        {
            "papers": papers,
            "target_date": target_date,
            "prev_date": prev_date.isoformat(),
            "next_date": next_date.isoformat(),
            "current_source": source,
            "current_min_score": score_filter,
            "sources": available_sources,
            "total_count": total_count,
            "page": page,
            "total_pages": total_pages,
            "date_counts": date_counts,
            "json": json,
        },
    )


# ────────────────────────────────────────────────────────
# 论文详情
# ────────────────────────────────────────────────────────

@router.get("/paper/{paper_id}", response_class=HTMLResponse)
async def paper_detail(
    request: Request,
    paper_id: int,
    db: Session = Depends(get_db),
):
    """论文详情页"""
    paper = db.query(Paper).filter(Paper.id == paper_id).first()
    if not paper:
        return templates.TemplateResponse(
            request,
            "paper_detail.html",
            {"paper": None, "json": json},
        )

    rank = lookup_journal_rank(paper.journal or "")

    return templates.TemplateResponse(
        request,
        "paper_detail.html",
        {
            "paper": paper,
            "journal_rank": rank,
            "json": json,
        },
    )
