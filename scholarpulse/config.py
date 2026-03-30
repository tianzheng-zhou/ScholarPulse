"""配置加载模块：从 config.yaml 和 .env 读取配置"""

from __future__ import annotations

import os
from pathlib import Path
from dataclasses import dataclass, field
from typing import Any

import yaml
from dotenv import load_dotenv

# 项目根目录
BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")


@dataclass
class LLMConfig:
    base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    model: str = "qwen3.5-plus"
    max_concurrent: int = 30
    enable_thinking: bool = False
    api_key: str = ""

    def __post_init__(self) -> None:
        self.api_key = os.getenv("DASHSCOPE_API_KEY", "")


@dataclass
class SchedulerConfig:
    enabled: bool = True
    cron: str = "0 8 * * *"
    fetch_days: int = 3


@dataclass
class ServerConfig:
    host: str = "127.0.0.1"
    port: int = 15471


@dataclass
class SourceConfig:
    enabled: bool = False
    categories: list[str] = field(default_factory=list)
    email: str = ""
    feeds: list[dict[str, str]] = field(default_factory=list)


@dataclass
class AppConfig:
    research_description: str = ""
    keywords: list[str] = field(default_factory=list)
    sources: dict[str, SourceConfig] = field(default_factory=dict)
    llm: LLMConfig = field(default_factory=LLMConfig)
    scheduler: SchedulerConfig = field(default_factory=SchedulerConfig)
    server: ServerConfig = field(default_factory=ServerConfig)


def _parse_source(data: dict[str, Any]) -> SourceConfig:
    return SourceConfig(
        enabled=data.get("enabled", False),
        categories=data.get("categories", []),
        email=data.get("email", ""),
        feeds=data.get("feeds", []),
    )


def load_config(path: Path | None = None) -> AppConfig:
    """从 YAML 文件加载配置"""
    if path is None:
        path = BASE_DIR / "config.yaml"

    if not path.exists():
        return AppConfig()

    with open(path, "r", encoding="utf-8") as f:
        raw: dict[str, Any] = yaml.safe_load(f) or {}

    sources_raw: dict[str, Any] = raw.get("sources", {})
    sources = {name: _parse_source(cfg) for name, cfg in sources_raw.items()}

    llm_raw = raw.get("llm", {})
    llm = LLMConfig(
        base_url=llm_raw.get("base_url", LLMConfig.base_url),
        model=llm_raw.get("model", LLMConfig.model),
        max_concurrent=llm_raw.get("max_concurrent", LLMConfig.max_concurrent),
        enable_thinking=llm_raw.get("enable_thinking", LLMConfig.enable_thinking),
    )

    sched_raw = raw.get("scheduler", {})
    scheduler = SchedulerConfig(
        enabled=sched_raw.get("enabled", True),
        cron=sched_raw.get("cron", "0 8 * * *"),
        fetch_days=sched_raw.get("fetch_days", 3),
    )

    server_raw = raw.get("server", {})
    server = ServerConfig(
        host=server_raw.get("host", "127.0.0.1"),
        port=server_raw.get("port", 15471),
    )

    return AppConfig(
        research_description=raw.get("research_description", ""),
        keywords=raw.get("keywords", []),
        sources=sources,
        llm=llm,
        scheduler=scheduler,
        server=server,
    )


def save_config(cfg: AppConfig, path: Path | None = None) -> None:
    """将配置保存到 YAML 文件"""
    if path is None:
        path = BASE_DIR / "config.yaml"

    sources_data: dict[str, Any] = {}
    for name, src in cfg.sources.items():
        d: dict[str, Any] = {"enabled": src.enabled}
        if src.categories:
            d["categories"] = src.categories
        if src.email:
            d["email"] = src.email
        if src.feeds:
            d["feeds"] = src.feeds
        sources_data[name] = d

    data: dict[str, Any] = {
        "research_description": cfg.research_description,
        "keywords": cfg.keywords,
        "sources": sources_data,
        "llm": {
            "base_url": cfg.llm.base_url,
            "model": cfg.llm.model,
            "max_concurrent": cfg.llm.max_concurrent,
            "enable_thinking": cfg.llm.enable_thinking,
        },
        "scheduler": {
            "enabled": cfg.scheduler.enabled,
            "cron": cfg.scheduler.cron,
            "fetch_days": cfg.scheduler.fetch_days,
        },
        "server": {
            "host": cfg.server.host,
            "port": cfg.server.port,
        },
    }

    with open(path, "w", encoding="utf-8") as f:
        yaml.dump(data, f, allow_unicode=True, default_flow_style=False, sort_keys=False)
