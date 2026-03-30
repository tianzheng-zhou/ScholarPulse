"""设置页面路由 + 手动抓取 + AI 设置助手"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import date
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, Form, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from openai import AsyncOpenAI
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse
from sqlalchemy.orm import Session

from ..config import BASE_DIR, AppConfig, load_config, save_config
from ..database import FetchLog, SessionLocal
from ..scheduler import run_fetch_job

logger = logging.getLogger(__name__)

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


# ---------- AI 设置助手 ----------

ASSISTANT_SYSTEM_PROMPT = """\
<role>你是 ScholarPulse 的设置编辑助手，帮助用户配置学术论文追踪系统。</role>

<capabilities>
- 根据用户描述的研究方向，推荐合适的英文搜索关键词
- 推荐合适的 arXiv 分类
- 帮助用户优化研究方向描述，使 AI 评分更准确
- 解释各项设置的含义和最佳实践
- 回答关于 Cron 表达式的问题
- 直接修改用户的设置（通过操作块，用户需确认后才会生效）
</capabilities>

<field_guide>以下是系统中各设置项的详细说明，当用户不知道如何填写时，请根据此引导用户：

1. 研究方向描述 (research_description)
   - 作用：用于指导 AI 对论文进行相关性评分，描述越具体评分越准确
   - 建议：用 1-3 句英文描述你的具体研究兴趣，包括研究对象、方法和应用场景
   - 示例："Research on oxide thin-film transistors (IGZO-TFT) for flexible AMOLED displays, focusing on device stability, carrier mobility enhancement, and low-temperature fabrication."
   - 常见错误：写得太笼统（如 "machine learning"）、用中文写（因为论文多为英文）、留空或写测试内容

2. 搜索关键词 (keywords)
   - 作用：用于在 Semantic Scholar 和 arXiv 上搜索论文，多个关键词分别搜索后合并结果
   - 建议：5-15 个英文关键词，每行一个，涵盖核心术语、同义词、缩写和相关技术
   - 示例：
     - 核心词：Thin-Film Transistor, TFT
     - 材料类：IGZO, Oxide Semiconductor, LTPS
     - 应用类：Flexible Display, Active Matrix, AMOLED backplane
   - 常见错误：只写一个关键词、关键词太宽泛、不同细分方向混在一起

3. arXiv 分类 (arxiv_categories)
   - 作用：限定 arXiv 搜索范围，每行一个分类代码
   - 常用分类：
     - cs.AI (人工智能), cs.LG (机器学习), cs.CV (计算机视觉), cs.CL (计算语言学)
     - cs.RO (机器人), cs.CR (密码学与安全), cs.SE (软件工程)
     - eess.SP (信号处理), eess.IV (图像与视频), eess.SY (系统与控制)
     - physics.app-ph (应用物理), cond-mat.mtrl-sci (材料科学)
     - stat.ML (统计机器学习), q-bio (定量生物学)
   - 建议：选 1-3 个与研究最相关的，太多会引入噪声
   - 完整分类列表见 https://arxiv.org/category_taxonomy

4. Cron 定时表达式 (scheduler_cron)
   - 格式：分 时 日 月 周几（五段式）
   - 示例：
     - "0 8 * * *" — 每天早上 8 点
     - "0 8 * * 1-5" — 工作日早 8 点
     - "0 */6 * * *" — 每 6 小时执行一次
     - "30 9 * * 1" — 每周一 9:30
   - 常见错误：写成 6 段式（含秒）、星期用 7 表示周日（应为 0）

5. 其他设置（用户可能询问但不可通过操作块修改）
   - 数据源开关：勾选启用 Semantic Scholar 和/或 arXiv
   - LLM 配置：API Base URL 和模型名称，默认使用阿里云百炼 qwen3.5-plus
   - API Key：在项目根目录的 .env 文件中设置 DASHSCOPE_API_KEY
   - 抓取天数：每次拓取过去几天的论文，默认 3 天
</field_guide>

<rules>
- 回答简洁明了，直接给出建议
- 如果用户不知道某个字段怎么填，参考 <field_guide> 中的说明和示例进行引导
- 如果用户的问题与设置无关，礼貌引导回设置话题
- 你可以看到用户的完整设置，根据这些信息提供有针对性的建议
- 当你建议修改某项设置时，必须先用文字说明修改原因，然后附上操作块供用户一键应用
- 用户明确要求修改时才输出操作块，纯粙建议时只用普通文本和代码块
</rules>

<action_format>
当需要修改设置时，在说明文字后使用以下格式输出操作块（用户点击“应用”后才会生效）：

```action
{"field": "字段名", "label": "显示名称", "value": "新值"}
```

可用字段：
- research_description — 研究方向描述（纯文本）
- keywords — 搜索关键词（多个关键词用 \n 分隔）
- arxiv_categories — arXiv 分类（多个分类用 \n 分隔）
- scheduler_cron — Cron 定时表达式

每个字段输出一个操作块。可同时输出多个操作块修改不同字段。
value 中的换行用 \n 表示（JSON 转义）。
</action_format>"""


def _build_config_context(config: AppConfig) -> str:
    """将完整配置序列化为 XML 上下文供 AI 助手参考"""
    ss = config.sources.get("semantic_scholar")
    arxiv = config.sources.get("arxiv")
    return (
        "<current_settings>\n"
        f"<research_description>{config.research_description or '未填写'}</research_description>\n"
        f"<keywords>{chr(10).join(config.keywords) if config.keywords else '无'}</keywords>\n"
        "<sources>\n"
        f"  <semantic_scholar enabled=\"{ss.enabled if ss else False}\" />\n"
        f"  <arxiv enabled=\"{arxiv.enabled if arxiv else False}\">\n"
        f"    <categories>{chr(10).join(arxiv.categories) if arxiv and arxiv.categories else '无'}</categories>\n"
        f"  </arxiv>\n"
        "</sources>\n"
        "<llm>\n"
        f"  <base_url>{config.llm.base_url}</base_url>\n"
        f"  <model>{config.llm.model}</model>\n"
        f"  <max_concurrent>{config.llm.max_concurrent}</max_concurrent>\n"
        "</llm>\n"
        "<scheduler>\n"
        f"  <enabled>{config.scheduler.enabled}</enabled>\n"
        f"  <cron>{config.scheduler.cron}</cron>\n"
        f"  <fetch_days>{config.scheduler.fetch_days}</fetch_days>\n"
        "</scheduler>\n"
        "</current_settings>"
    )


# 允许 AI 助手修改的字段白名单
ALLOWED_FIELDS = {"research_description", "keywords", "arxiv_categories", "scheduler_cron"}


class ChatMessage(BaseModel):
    message: str
    history: list[dict[str, str]] = []


class ApplyActionRequest(BaseModel):
    field: str
    value: str


@router.post("/settings/chat")
async def settings_chat(body: ChatMessage):
    """AI 设置助手 — 流式返回"""
    config = load_config()

    if not config.llm.api_key:
        async def _no_key():
            yield {"data": "⚠️ 尚未配置 DASHSCOPE_API_KEY，无法使用 AI 助手。请在 .env 文件中设置。"}
        return EventSourceResponse(_no_key())

    # 构造完整配置上下文
    config_context = _build_config_context(config)

    messages: list[dict[str, str]] = [
        {"role": "system", "content": ASSISTANT_SYSTEM_PROMPT},
        {"role": "system", "content": config_context},
    ]

    # 加入历史对话（最多保留最近 10 轮）
    for msg in body.history[-20:]:
        if msg.get("role") in ("user", "assistant"):
            messages.append({"role": msg["role"], "content": msg["content"]})

    messages.append({"role": "user", "content": body.message})

    client = AsyncOpenAI(
        api_key=config.llm.api_key,
        base_url=config.llm.base_url,
    )

    async def _stream():
        try:
            stream = await client.chat.completions.create(
                model=config.llm.model,
                messages=messages,
                temperature=0.7,
                stream=True,
                extra_body={"enable_thinking": False},
            )
            async for chunk in stream:
                delta = chunk.choices[0].delta if chunk.choices else None
                if delta and delta.content:
                    yield {"data": delta.content}
        except Exception as e:
            logger.exception("AI 设置助手调用失败")
            yield {"data": f"\n\n⚠️ AI 调用出错：{type(e).__name__}"}

    return EventSourceResponse(_stream())


@router.post("/settings/apply-action")
async def apply_setting_action(body: ApplyActionRequest):
    """应用 AI 助手建议的设置修改，返回旧值以支持撤销"""
    if body.field not in ALLOWED_FIELDS:
        return {"success": False, "error": "不允许修改该字段"}

    config = load_config()
    old_value: str = ""

    if body.field == "research_description":
        old_value = config.research_description
        config.research_description = body.value

    elif body.field == "keywords":
        old_value = "\n".join(config.keywords)
        config.keywords = [k.strip() for k in body.value.split("\n") if k.strip()]

    elif body.field == "arxiv_categories":
        arxiv_src = config.sources.get("arxiv")
        if arxiv_src:
            old_value = "\n".join(arxiv_src.categories)
            arxiv_src.categories = [c.strip() for c in body.value.split("\n") if c.strip()]
        else:
            return {"success": False, "error": "arXiv 数据源未配置"}

    elif body.field == "scheduler_cron":
        old_value = config.scheduler.cron
        config.scheduler.cron = body.value.strip()

    save_config(config)
    return {"success": True, "old_value": old_value}


class RescoreRequest(BaseModel):
    """重新评分请求"""
    pass


@router.post("/settings/rescore")
async def rescore_papers(background_tasks: BackgroundTasks):
    """重置所有论文的 AI 处理状态，后台重新评分"""
    db = SessionLocal()
    try:
        from ..database import Paper
        count = db.query(Paper).filter(Paper.ai_processed == True).count()  # noqa: E712
        if count == 0:
            return {"success": True, "message": "没有需要重新评分的论文", "count": 0}
        db.query(Paper).filter(Paper.ai_processed == True).update(  # noqa: E712
            {Paper.ai_processed: False, Paper.relevance_score: None, Paper.relevance_reason: None, Paper.summary_zh: None, Paper.title_zh: None, Paper.keywords: None},
            synchronize_session="fetch",
        )
        db.commit()
    finally:
        db.close()

    config = load_config()

    async def _bg_rescore() -> None:
        await run_fetch_job(config, days=0)

    background_tasks.add_task(_bg_rescore)
    return {"success": True, "message": f"已重置 {count} 篇论文，后台重新评分中", "count": count}
