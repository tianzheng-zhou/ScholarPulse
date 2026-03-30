"""日报页面路由"""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..config import BASE_DIR
from ..database import Paper, SessionLocal
from ..journal_ranks import get_journal_weight, lookup_journal_rank

router = APIRouter()
templates = Jinja2Templates(directory=str(BASE_DIR / "scholarpulse" / "templates"))


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@router.get("/", response_class=HTMLResponse)
async def daily_index(
    request: Request,
    d: str | None = None,
    source: str | None = None,
    min_score: str | None = None,
    keyword: str | None = None,
    db: Session = Depends(get_db),
):
    """日报主页"""
    # 解析评分筛选（兼容空字符串）
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
        target_date = date.today()

    prev_date = target_date - timedelta(days=1)
    next_date = target_date + timedelta(days=1)

    # 查询论文
    query = db.query(Paper).filter(
        Paper.fetched_at >= datetime.combine(target_date, datetime.min.time()),
        Paper.fetched_at < datetime.combine(target_date + timedelta(days=1), datetime.min.time()),
    )

    # 如果当天没有论文，回退查找最近有数据的日期
    count = query.count()
    if count == 0 and d is None:
        latest = db.query(func.max(Paper.fetched_at)).scalar()
        if latest:
            target_date = latest.date()
            prev_date = target_date - timedelta(days=1)
            next_date = target_date + timedelta(days=1)
            query = db.query(Paper).filter(
                Paper.fetched_at >= datetime.combine(target_date, datetime.min.time()),
                Paper.fetched_at < datetime.combine(target_date + timedelta(days=1), datetime.min.time()),
            )

    # 筛选
    if source:
        query = query.filter(Paper.source == source)
    if score_filter is not None:
        query = query.filter(Paper.relevance_score >= score_filter)
    if keyword:
        query = query.filter(Paper.keywords.contains(keyword))

    papers = query.all()

    # 排序：相关性评分 × 期刊权重
    def sort_key(p: Paper) -> float:
        score = p.relevance_score or 0
        rank = lookup_journal_rank(p.journal or "")
        weight = get_journal_weight(rank)
        return score * weight

    papers.sort(key=sort_key, reverse=True)

    # 获取可用的数据源列表
    sources_list = (
        db.query(Paper.source).distinct().all()
    )
    available_sources = [s[0] for s in sources_list]

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
            "current_keyword": keyword,
            "sources": available_sources,
            "total_count": len(papers),
            "json": json,
        },
    )


@router.get("/daily/{d}", response_class=HTMLResponse)
async def daily_by_date(
    request: Request,
    d: str,
    source: str | None = None,
    min_score: str | None = None,
    keyword: str | None = None,
    db: Session = Depends(get_db),
):
    return await daily_index(request, d=d, source=source, min_score=min_score, keyword=keyword, db=db)


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
