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
from ..database import FetchLog, Paper, SessionLocal
from ..scheduler import run_fetch_job
from ..ai.embedding import (
    build_paper_text,
    generate_embeddings_batch,
    serialize_embedding,
)

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
    openalex_enabled: bool = Form(False),
    openalex_email: str = Form(""),
    ieee_enabled: bool = Form(False),
    crossref_enabled: bool = Form(False),
    crossref_email: str = Form(""),
    rss_enabled: bool = Form(False),
    rss_feeds: str = Form(""),
    llm_base_url: str = Form(""),
    llm_model: str = Form(""),
    llm_max_concurrent: int = Form(5),
    scheduler_enabled: bool = Form(False),
    scheduler_cron: str = Form("0 8 * * *"),
    fetch_days: int = Form(3),
):
    """保存设置"""
    from ..config import SourceConfig

    config = load_config()

    config.research_description = research_description
    config.keywords = [k.strip() for k in keywords.split("\n") if k.strip()]

    # 数据源 — Semantic Scholar
    if "semantic_scholar" not in config.sources:
        config.sources["semantic_scholar"] = SourceConfig()
    config.sources["semantic_scholar"].enabled = ss_enabled

    # 数据源 — arXiv
    if "arxiv" not in config.sources:
        config.sources["arxiv"] = SourceConfig()
    config.sources["arxiv"].enabled = arxiv_enabled
    config.sources["arxiv"].categories = [
        c.strip() for c in arxiv_categories.split("\n") if c.strip()
    ]

    # 数据源 — OpenAlex
    if "openalex" not in config.sources:
        config.sources["openalex"] = SourceConfig()
    config.sources["openalex"].enabled = openalex_enabled
    config.sources["openalex"].email = openalex_email.strip()

    # 数据源 — IEEE Xplore
    if "ieee_xplore" not in config.sources:
        config.sources["ieee_xplore"] = SourceConfig()
    config.sources["ieee_xplore"].enabled = ieee_enabled

    # 数据源 — CrossRef
    if "crossref" not in config.sources:
        config.sources["crossref"] = SourceConfig()
    config.sources["crossref"].enabled = crossref_enabled
    config.sources["crossref"].email = crossref_email.strip()

    # 数据源 — RSS
    if "rss" not in config.sources:
        config.sources["rss"] = SourceConfig()
    config.sources["rss"].enabled = rss_enabled
    feeds: list[dict[str, str]] = []
    for line in rss_feeds.split("\n"):
        line = line.strip()
        if not line:
            continue
        if "|" in line:
            name, url = line.split("|", 1)
            feeds.append({"name": name.strip(), "url": url.strip()})
        else:
            feeds.append({"name": line, "url": line})
    config.sources["rss"].feeds = feeds

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
            "stats": {"message": "拓取任务已在后台启动，请稍后刷新论文库页面查看结果。"},
            "json": json,
        },
    )


@router.post("/retry-failed")
async def retry_failed(
    request: Request,
    background_tasks: BackgroundTasks,
):
    """重置所有失败论文的 ai_fail_count，使其可被重新处理"""
    db = SessionLocal()
    try:
        count = db.query(Paper).filter(Paper.ai_fail_count >= 3).update(
            {Paper.ai_fail_count: 0}, synchronize_session="fetch"
        )
        db.commit()
    finally:
        db.close()

    config = load_config()

    async def _bg_retry() -> None:
        await run_fetch_job(config, days=0)

    background_tasks.add_task(_bg_retry)
    return templates.TemplateResponse(
        request,
        "fetch_result.html",
        {
            "stats": {"message": f"已重置 {count} 篇失败论文，后台重新处理中。"},
            "json": json,
        },
    )


@router.post("/generate-embeddings")
async def generate_embeddings_route(
    request: Request,
    background_tasks: BackgroundTasks,
):
    """为所有缺少向量的论文批量生成 embedding"""
    db = SessionLocal()
    try:
        pending = db.query(Paper).filter(
            Paper.embedding.is_(None), Paper.title.isnot(None)
        ).count()
    finally:
        db.close()

    async def _bg_embed() -> None:
        sess = SessionLocal()
        try:
            papers = sess.query(Paper).filter(
                Paper.embedding.is_(None), Paper.title.isnot(None)
            ).all()
            if not papers:
                return
            texts = [build_paper_text(p.title, p.abstract) for p in papers]
            vectors = await generate_embeddings_batch(
                texts,
                instruct="Represent the academic paper for retrieval",
            )
            count = 0
            for paper, vec in zip(papers, vectors):
                if vec is not None:
                    paper.embedding = serialize_embedding(vec)
                    count += 1
            sess.commit()
            logger.info("手动向量生成完成: %d/%d 篇", count, len(papers))
        except Exception:
            logger.exception("手动向量生成失败")
            sess.rollback()
        finally:
            sess.close()

    background_tasks.add_task(_bg_embed)
    return templates.TemplateResponse(
        request,
        "fetch_result.html",
        {
            "stats": {"message": f"向量生成任务已启动，{pending} 篇论文待处理。请稍后刷新查看进度。"},
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
<role>你是 ScholarPulse 的智能助手，帮助用户配置和使用这个学术论文追踪系统。</role>

<project_overview>
ScholarPulse 是一个多平台聚合学术 AI 日报系统，工作流程如下：
1. **抓取**：从多个学术数据源（Semantic Scholar、arXiv、OpenAlex、IEEE Xplore、RSS）按用户关键词搜索最新论文
2. **元数据补全**：通过 CrossRef 补充引用数、期刊信息等元数据
3. **期刊分级**：自动标注中科院分区、JCR 分区、影响因子
4. **AI 处理**：用大语言模型对每篇论文进行中文标题翻译、摘要总结、1-5 分相关性评分、关键词提取
5. **展示**：以日报形式（按论文发表日期分组）和论文库（全量分页浏览）呈现结果

系统页面：
- 论文库主页 (/) — 所有论文的分页浏览、搜索、筛选，可手动触发抓取
- 日报 (/daily) — 按论文发表日期浏览，按相关性×期刊权重综合排序
- 论文详情 (/paper/{id}) — 单篇论文完整信息
- 设置 (/settings) — 你所在的页面，配置关键词、数据源、LLM 和调度
- 抓取日志 (/logs) — 查看历史抓取记录和各数据源状态
</project_overview>

<capabilities>
- 根据用户描述的研究方向，推荐合适的英文搜索关键词
- 推荐合适的 arXiv 分类
- 帮助用户优化研究方向描述，使 AI 评分更准确
- 解释各项设置的含义和最佳实践
- 回答关于 Cron 表达式的问题
- 推荐合适的数据源组合和 RSS 期刊源
- 直接修改用户的设置（通过操作块，用户需确认后才会生效）
- 指导用户使用系统的各项功能
</capabilities>

<data_sources_guide>
各数据源特点和适用场景：

1. **Semantic Scholar**（推荐始终启用）
   - 覆盖面最广：涵盖全学科数万种期刊和会议
   - 按关键词逐个搜索，支持日期范围筛选
   - 有 API Key 时限速 1 req/s，无 Key 时 100 req/5min
   - API Key 在 .env 文件中设置 S2_API_KEY（可选）

2. **arXiv**（推荐启用，尤其适合 CS、物理、数学方向）
   - 专注预印本，论文发布速度最快
   - 需要配置 arXiv 分类代码来限定搜索范围
   - 免费无需 API Key

3. **OpenAlex**（推荐启用）
   - 全学科开放元数据，超过 2.5 亿篇论文
   - 填写邮箱后进入 polite pool，速率提升到 ~100 req/s
   - 免费无需 API Key

4. **IEEE Xplore**（适合工程技术方向）
   - IEEE 出版物（期刊 + 会议 + 标准）
   - 需要 API Key（.env 中设置 IEEE_API_KEY），免费 200 次/天
   - 在 https://developer.ieee.org/ 申请，需等待审批激活

5. **CrossRef**（推荐启用，辅助层）
   - 不直接搜索论文，而是为已抓取的论文补全引用数、期刊元数据
   - 填写邮箱后进入 polite pool，提升速率
   - 免费无需 API Key

6. **RSS**（推荐启用，零成本追踪核心期刊）
   - 订阅指定期刊的 RSS Feed，获取最新目录
   - 不能按关键词搜索，但确保不遗漏核心期刊的每篇文章
   - 适合配置研究领域的 Top 期刊
   - 格式：每行 "期刊名称|RSS URL"
</data_sources_guide>

<field_guide>以下是系统中各设置项的详细说明：

1. 研究方向描述 (research_description)
   - 作用：用于指导 AI 对论文进行相关性评分，描述越具体评分越准确
   - 建议：用 1-3 句英文描述你的具体研究兴趣，包括研究对象、方法和应用场景
   - 示例："Research on oxide thin-film transistors (IGZO-TFT) for flexible AMOLED displays, focusing on device stability, carrier mobility enhancement, and low-temperature fabrication."
   - 常见错误：写得太笼统（如 "machine learning"）、用中文写（因为论文多为英文）、留空

2. 搜索关键词 (keywords)
   - 作用：用于在 Semantic Scholar、arXiv 和 OpenAlex 上搜索论文，每个关键词独立搜索后去重合并
   - 建议：5-15 个英文关键词，涵盖核心术语、同义词、缩写和相关技术
   - 注意：关键词太多会增加抓取时间，太少则可能遗漏论文。太宽泛的关键词会引入大量无关论文

3. arXiv 分类 (arxiv_categories)
   - 作用：限定 arXiv 搜索范围
   - 常用分类：cs.AI, cs.LG, cs.CV, cs.CL, cs.RO, eess.SP, physics.app-ph, cond-mat.mtrl-sci, stat.ML
   - 建议：选 1-3 个最相关的

4. Cron 定时表达式 (scheduler_cron)
   - 格式：分 时 日 月 周几（五段式）
   - 示例："0 8 * * *" 每天早 8 点，"0 8 * * 1-5" 工作日早 8 点

5. 抓取天数 (fetch_days)
   - 每次抓取过去几天的论文，默认 3 天
   - 定时每天执行时设 3 天可覆盖周末，首次使用可设 7 天
</field_guide>

<workflow_guide>
以下是用户在不同场景下应采取的操作，在合适的时机主动告知：

**首次使用 / 刚改了研究方向**
→ 1. 先填写研究方向描述和关键词
→ 2. 保存设置后，在主页点击"手动抓取"按钮触发第一次抓取
→ 3. 等待抓取 + AI 处理完成后，到日报页面查看结果

**修改了研究方向描述**
→ 研究方向影响 AI 评分，已有论文的评分不会自动更新
→ 建议点击设置页底部的「🔄 重新评分所有论文」按钮
→ 提醒：重新评分会消耗 AI API 额度，论文多时需要一些时间

**修改了搜索关键词**
→ 只影响下次抓取的搜索范围，不影响已有论文
→ 如果关键词变化大，建议同时更新研究方向描述，并考虑重新评分

**想看到更多/更少的论文**
→ 论文太少：增加关键词、启用更多数据源、增加抓取天数
→ 论文太多：减少宽泛关键词、在日报页面用"最低评分"筛选
→ 无关论文太多：优化研究方向描述使评分更精准

**抓取结果为 0 或数据源报错**
→ 检查抓取日志页面（/logs）查看各数据源状态
→ 常见原因：API Key 未配置或失效、网络问题、关键词拼写错误
→ IEEE Xplore 需 API Key 且申请后需等审批
→ OpenAlex 和 Semantic Scholar 无需 API Key 即可使用

**AI 处理失败的论文**
→ 在主页筛选"处理失败"的论文
→ 点击设置页的「🔄 重新评分所有论文」重新处理
→ 每篇论文最多重试 3 次

**想自动化每日运行**
→ 启用定时调度，设置 Cron 表达式
→ 系统会自动执行抓取 + AI 处理
→ 注意：定时任务需要服务保持运行
</workflow_guide>

<rules>
- 回答简洁明了，直接给出建议
- 你可以看到用户的完整设置，发现不合理之处时主动提示
- 建议修改时先用文字说明原因，再附操作块
- 用户明确要求修改时才输出操作块，纯建议时用普通文本
- 在合适的时机参考 <workflow_guide> 主动提醒下一步操作
- 推荐 RSS 源时，根据用户研究方向推荐高影响力期刊
- 如果用户的问题超出设置范围但与学术论文相关，给出有用的指引（如指向具体页面）
</rules>

<action_format>
修改设置时使用以下格式输出操作块（用户点击"应用"后才生效）：

```action
{"field": "字段名", "label": "显示名称", "value": "新值"}
```

可用字段：
- research_description — 研究方向描述（纯文本）
- keywords — 搜索关键词（多个用 
 分隔）
- arxiv_categories — arXiv 分类（多个用 
 分隔）
- scheduler_cron — Cron 定时表达式
- source_semantic_scholar — 启用/禁用 Semantic Scholar（"true"/"false"）
- source_arxiv — 启用/禁用 arXiv（"true"/"false"）
- source_openalex — 启用/禁用 OpenAlex（"true"/"false"）
- source_ieee_xplore — 启用/禁用 IEEE Xplore（"true"/"false"）
- source_crossref — 启用/禁用 CrossRef（"true"/"false"）
- source_rss — 启用/禁用 RSS（"true"/"false"）
- openalex_email — OpenAlex 邮箱
- crossref_email — CrossRef 邮箱
- rss_feeds — RSS 源列表（每行 名称|URL，用 
 分隔）
- fetch_days — 每次抓取天数（整数）

每个字段一个操作块，可同时输出多个。value 中换行用 
 表示。
</action_format>"""


def _build_config_context(config: AppConfig) -> str:
    """将完整配置序列化为 XML 上下文供 AI 助手参考"""
    ss = config.sources.get("semantic_scholar")
    arxiv = config.sources.get("arxiv")
    openalex = config.sources.get("openalex")
    ieee = config.sources.get("ieee_xplore")
    crossref = config.sources.get("crossref")
    rss = config.sources.get("rss")

    # RSS feeds
    rss_feeds_str = "无"
    if rss and rss.feeds:
        rss_feeds_str = chr(10).join(f"    {f.get('name', f.get('url', ''))}|{f.get('url', '')}" for f in rss.feeds)

    return (
        "<current_settings>\n"
        f"<research_description>{config.research_description or '未填写'}</research_description>\n"
        f"<keywords>{chr(10).join(config.keywords) if config.keywords else '无'}</keywords>\n"
        "<sources>\n"
        f"  <semantic_scholar enabled=\"{ss.enabled if ss else False}\" />\n"
        f"  <arxiv enabled=\"{arxiv.enabled if arxiv else False}\">\n"
        f"    <categories>{chr(10).join(arxiv.categories) if arxiv and arxiv.categories else '无'}</categories>\n"
        f"  </arxiv>\n"
        f"  <openalex enabled=\"{openalex.enabled if openalex else False}\" email=\"{openalex.email if openalex else ''}\" />\n"
        f"  <ieee_xplore enabled=\"{ieee.enabled if ieee else False}\" />\n"
        f"  <crossref enabled=\"{crossref.enabled if crossref else False}\" email=\"{crossref.email if crossref else ''}\" />\n"
        f"  <rss enabled=\"{rss.enabled if rss else False}\">\n"
        f"    <feeds>\n{rss_feeds_str}\n    </feeds>\n"
        f"  </rss>\n"
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
ALLOWED_FIELDS = {
    "research_description", "keywords", "arxiv_categories", "scheduler_cron",
    "source_semantic_scholar", "source_arxiv", "source_openalex",
    "source_ieee_xplore", "source_crossref", "source_rss",
    "openalex_email", "crossref_email", "rss_feeds", "fetch_days",
}


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

    # 设置助手固定使用 qwen3.5-plus，不受用户 LLM 配置影响
    _ASSISTANT_MODEL = "qwen3.5-plus"

    client = AsyncOpenAI(
        api_key=config.llm.api_key,
        base_url=config.llm.base_url,
    )

    async def _stream():
        try:
            stream = await client.chat.completions.create(
                model=_ASSISTANT_MODEL,
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

    elif body.field.startswith("source_"):
        source_key = body.field[len("source_"):]
        src = config.sources.get(source_key)
        if not src:
            from ..config import SourceConfig
            src = SourceConfig()
            config.sources[source_key] = src
        old_value = str(src.enabled).lower()
        src.enabled = body.value.strip().lower() == "true"

    elif body.field == "openalex_email":
        src = config.sources.get("openalex")
        if not src:
            from ..config import SourceConfig
            src = SourceConfig()
            config.sources["openalex"] = src
        old_value = src.email or ""
        src.email = body.value.strip()

    elif body.field == "crossref_email":
        src = config.sources.get("crossref")
        if not src:
            from ..config import SourceConfig
            src = SourceConfig()
            config.sources["crossref"] = src
        old_value = src.email or ""
        src.email = body.value.strip()

    elif body.field == "rss_feeds":
        src = config.sources.get("rss")
        if not src:
            from ..config import SourceConfig
            src = SourceConfig()
            config.sources["rss"] = src
        old_value = "\n".join(f"{f.get('name', '')}|{f.get('url', '')}" for f in (src.feeds or []))
        feeds: list[dict[str, str]] = []
        for line in body.value.split("\n"):
            line = line.strip()
            if not line:
                continue
            if "|" in line:
                name, url = line.split("|", 1)
                feeds.append({"name": name.strip(), "url": url.strip()})
            else:
                feeds.append({"name": line, "url": line})
        src.feeds = feeds

    elif body.field == "fetch_days":
        old_value = str(config.scheduler.fetch_days)
        try:
            config.scheduler.fetch_days = int(body.value.strip())
        except ValueError:
            return {"success": False, "error": "抓取天数必须为整数"}

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
