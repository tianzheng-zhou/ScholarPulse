"""FastAPI 应用入口"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from .config import BASE_DIR, load_config
from .database import init_db
from .routers import daily, settings
from .scheduler import Scheduler

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

_scheduler: Scheduler | None = None


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    global _scheduler

    # 启动时
    logger.info("ScholarPulse 启动中...")
    init_db()
    logger.info("数据库初始化完成")

    config = load_config()
    _scheduler = Scheduler(config)
    _scheduler.start()

    yield

    # 关闭时
    if _scheduler:
        _scheduler.stop()
    logger.info("ScholarPulse 已关闭")


app = FastAPI(
    title="ScholarPulse",
    description="多平台聚合学术 AI 日报系统",
    version="0.1.0",
    lifespan=lifespan,
)

# 静态文件
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "scholarpulse" / "static")), name="static")

# 注册路由
app.include_router(daily.router)
app.include_router(settings.router)
