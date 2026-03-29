"""设置页面路由 + 手动抓取"""

from __future__ import annotations

import asyncio
import json
from datetime import date
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, Form, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from ..config import BASE_DIR, AppConfig, load_config, save_config
from ..database import FetchLog, SessionLocal
from ..scheduler import run_fetch_job

router = APIRouter()
templates = Jinja2Templates(directory=str(BASE_DIR / "scholarpulse" / "templates"))


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@router.get("/settings", response_class=HTMLResponse)
async def settings_page(request: Request, saved: bool = False):
    """设置页面"""
    config = load_config()
    return templates.TemplateResponse(
        request,
        "settings.html",
        {
            "config": config,
            "saved": saved,
        },
    )


@router.post("/settings")
async def save_settings(
    request: Request,
    research_description: str = Form(""),
    keywords: str = Form(""),
    ss_enabled: bool = Form(False),
    arxiv_enabled: bool = Form(False),
    arxiv_categories: str = Form(""),
    llm_base_url: str = Form(""),
    llm_model: str = Form(""),
    llm_max_concurrent: int = Form(5),
    scheduler_enabled: bool = Form(False),
    scheduler_cron: str = Form("0 8 * * *"),
    fetch_days: int = Form(3),
):
    """保存设置"""
    config = load_config()

    config.research_description = research_description
    config.keywords = [k.strip() for k in keywords.split("\n") if k.strip()]

    # 数据源
    if "semantic_scholar" not in config.sources:
        from ..config import SourceConfig
        config.sources["semantic_scholar"] = SourceConfig()
    config.sources["semantic_scholar"].enabled = ss_enabled

    if "arxiv" not in config.sources:
        from ..config import SourceConfig
        config.sources["arxiv"] = SourceConfig()
    config.sources["arxiv"].enabled = arxiv_enabled
    config.sources["arxiv"].categories = [
        c.strip() for c in arxiv_categories.split("\n") if c.strip()
    ]

    # LLM
    config.llm.base_url = llm_base_url
    config.llm.model = llm_model
    config.llm.max_concurrent = llm_max_concurrent

    # 调度
    config.scheduler.enabled = scheduler_enabled
    config.scheduler.cron = scheduler_cron
    config.scheduler.fetch_days = fetch_days

    save_config(config)
    return RedirectResponse(url="/settings?saved=true", status_code=303)


@router.post("/fetch", response_class=HTMLResponse)
async def manual_fetch(
    request: Request,
    background_tasks: BackgroundTasks,
    days: int = Form(3),
):
    """手动触发抓取（后台执行）"""
    config = load_config()

    async def _bg_fetch() -> None:
        await run_fetch_job(config, days=days)

    background_tasks.add_task(_bg_fetch)
    return templates.TemplateResponse(
        request,
        "fetch_result.html",
        {
            "stats": {"message": "拓取任务已在后台启动，请稍后刷新日报页面查看结果。"},
            "json": json,
        },
    )


@router.get("/logs", response_class=HTMLResponse)
async def fetch_logs(
    request: Request,
    db: Session = Depends(get_db),
):
    """抓取日志页面"""
    logs = db.query(FetchLog).order_by(FetchLog.id.desc()).limit(50).all()
    return templates.TemplateResponse(
        request,
        "logs.html",
        {"logs": logs},
    )
