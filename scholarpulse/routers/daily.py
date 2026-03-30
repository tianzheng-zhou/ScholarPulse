"""论文库 + 日报路由"""

from __future__ import annotations

import json
import math
from datetime import date, datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from ..config import BASE_DIR
from ..database import Paper, SessionLocal
from ..journal_ranks import get_journal_weight, lookup_journal_rank

router = APIRouter()
templates = Jinja2Templates(directory=str(BASE_DIR / "scholarpulse" / "templates"))

PAGE_SIZE = 30


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
    page: int = 1,
    db: Session = Depends(get_db),
):
    """论文库主页：所有论文的分页浏览、搜索"""
    score_filter: float | None = None
    if min_score:
        try:
            score_filter = float(min_score)
        except ValueError:
            score_filter = None

    query = db.query(Paper)

    # 搜索：匹配标题、中文标题、摘要
    if q:
        like_q = f"%{q}%"
        query = query.filter(
            or_(
                Paper.title.ilike(like_q),
                Paper.title_zh.ilike(like_q),
                Paper.abstract.ilike(like_q),
                Paper.keywords.ilike(like_q),
            )
        )

    # 来源筛选
    if source:
        query = query.filter(Paper.source == source)

    # 评分筛选
    if score_filter is not None:
        query = query.filter(Paper.relevance_score >= score_filter)

    # 处理状态筛选
    if status == "processed":
        query = query.filter(Paper.ai_processed == True)  # noqa: E712
    elif status == "unprocessed":
        query = query.filter(Paper.ai_processed == False)  # noqa: E712

    # 排序
    if sort == "score":
        query = query.order_by(Paper.relevance_score.desc().nullslast())
    elif sort == "date_asc":
        query = query.order_by(Paper.published_date.asc().nullslast())
    else:  # 默认：按发表日期降序
        query = query.order_by(Paper.published_date.desc().nullslast())

    # 统计
    total = query.count()
    total_pages = max(1, math.ceil(total / PAGE_SIZE))
    page = max(1, min(page, total_pages))
    papers = query.offset((page - 1) * PAGE_SIZE).limit(PAGE_SIZE).all()

    # 可用来源列表
    sources_list = db.query(Paper.source).distinct().all()
    available_sources = [s[0] for s in sources_list]

    # 统计概要
    total_all = db.query(Paper).count()
    processed_count = db.query(Paper).filter(Paper.ai_processed == True).count()  # noqa: E712
    unprocessed_count = total_all - processed_count

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
            "unprocessed_count": unprocessed_count,
            "query": q or "",
            "current_source": source,
            "current_min_score": score_filter,
            "current_status": status,
            "current_sort": sort or "date_desc",
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
        query = query.filter(Paper.source == source)
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

    # 可用来源列表
    sources_list = db.query(Paper.source).distinct().all()
    available_sources = [s[0] for s in sources_list]

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
            "total_count": len(papers),
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
