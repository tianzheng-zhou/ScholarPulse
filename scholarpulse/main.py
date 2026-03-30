"""FastAPI 应用入口"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from logging.handlers import RotatingFileHandler
from typing import AsyncGenerator

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from .config import BASE_DIR, load_config
from .database import init_db
from .routers import daily, settings
from .scheduler import Scheduler

# 日志目录
LOG_DIR = BASE_DIR / "data" / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)

_log_fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")

# 文件日志：按大小轮转，单文件最大 5MB，保留 5 个备份
_file_handler = RotatingFileHandler(
    LOG_DIR / "scholarpulse.log",
    maxBytes=5 * 1024 * 1024,
    backupCount=5,
    encoding="utf-8",
)
_file_handler.setFormatter(_log_fmt)
_file_handler.setLevel(logging.INFO)

# 控制台日志
_console_handler = logging.StreamHandler()
_console_handler.setFormatter(_log_fmt)
_console_handler.setLevel(logging.INFO)

logging.basicConfig(
    level=logging.INFO,
    handlers=[_console_handler, _file_handler],
)

# 让 uvicorn 的日志也写入文件
for _uv_name in ("uvicorn", "uvicorn.access", "uvicorn.error"):
    _uv_logger = logging.getLogger(_uv_name)
    _uv_logger.addHandler(_file_handler)

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
