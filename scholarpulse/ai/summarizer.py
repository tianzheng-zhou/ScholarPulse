"""AI 摘要、翻译、评分模块

使用 OpenAI 兼容 API（阿里云百炼 qwen3.5-plus）进行：
- 摘要翻译
- 一句话总结
- 相关性评分
- 关键词提取
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from openai import AsyncOpenAI

from ..config import AppConfig

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """\
<role>你是一位资深学术助手，擅长分析各领域学术论文。</role>
<output_format>请始终严格按照指定的 JSON 格式回复，不要输出任何其他文字。</output_format>"""

USER_PROMPT_TEMPLATE = """\
<task>分析以下学术论文，给出中文翻译、摘要总结、相关性评分和关键词提取。</task>

<user_profile>
<research_description>{research_description}</research_description>
<keywords>{keywords_list}</keywords>
</user_profile>

<paper>
<title>{title}</title>
<abstract>{abstract}</abstract>
<journal>{journal}</journal>
</paper>

<instructions>
1. 将英文标题翻译为中文
2. 用 3-5 句中文总结论文的核心内容，包括：
   - 研究解决什么问题
   - 采用什么方法/技术
   - 主要结果或发现
   - 潜在应用价值（如有）
3. 根据以下评分标准，对论文打 1-5 分相关性评分
4. 详细说明评分理由（2-3 句）
5. 提取 3-5 个英文关键词
</instructions>

<scoring_rubric>
评分标准（基于用户的 research_description 和 keywords 综合判断）：

5 分 — 高度相关：
  - 论文主题与用户研究方向直接匹配
  - 解决的问题、使用的方法或研究对象与用户关键词高度重叠
  - 可直接用于用户的研究工作

4 分 — 较相关：
  - 论文主题属于用户研究的子领域或相邻领域
  - 部分方法/结果对用户有参考价值

3 分 — 一般相关：
  - 属于同一大领域，但具体方向不同
  - 包含一些可借鉴的方法或背景知识

2 分 — 弱相关：
  - 仅在学科大类上相关，具体内容与用户研究关联不大

1 分 — 不相关：
  - 与用户研究方向基本无关

加分/减分因素：
  - 顶级期刊（Nature/Science/领域顶刊）可酌情加 0.5 分
  - 高被引论文可酌情加 0.5 分
  - 最终分数不超过 5 分
</scoring_rubric>

<output_schema>
严格返回如下 JSON，不要包含任何其他内容：
{{
  "title_zh": "中文标题",
  "summary_zh": "3-5 句中文总结，包括研究问题、方法、主要结果和应用价值",
  "relevance_score": 4,
  "relevance_reason": "详细说明评分理由，包括与用户研究方向的关联点和参考价值",
  "keywords": ["keyword1", "keyword2", "keyword3"]
}}
</output_schema>"""


class AISummarizer:
    def __init__(self, config: AppConfig) -> None:
        self.config = config
        self.client = AsyncOpenAI(
            api_key=config.llm.api_key,
            base_url=config.llm.base_url,
        )
        self.model = config.llm.model
        self.semaphore = asyncio.Semaphore(config.llm.max_concurrent)
        self._enable_thinking = config.llm.enable_thinking

    async def process_paper(
        self, title: str, abstract: str, journal: str = ""
    ) -> dict[str, Any] | None:
        """处理单篇论文，返回 AI 分析结果字典"""
        if not abstract:
            return None

        prompt = USER_PROMPT_TEMPLATE.format(
            research_description=self.config.research_description,
            keywords_list=", ".join(self.config.keywords),
            title=title,
            abstract=abstract[:3000],  # 截断过长摘要
            journal=journal or "未知",
        )

        async with self.semaphore:
            return await self._call_llm(prompt)

    async def _call_llm(
        self, prompt: str, max_retries: int = 3
    ) -> dict[str, Any] | None:
        for attempt in range(max_retries):
            try:
                extra_body: dict[str, Any] = {
                    "enable_thinking": self._enable_thinking,
                }
                resp = await self.client.chat.completions.create(
                    model=self.model,
                    messages=[
                        {"role": "system", "content": SYSTEM_PROMPT},
                        {"role": "user", "content": prompt},
                    ],
                    temperature=0.3,
                    response_format={"type": "json_object"},
                    extra_body=extra_body,
                )

                content = resp.choices[0].message.content
                if not content:
                    return None

                result = json.loads(content)
                # 校验必要字段
                if "title_zh" in result and "relevance_score" in result:
                    # 确保分数在范围内
                    score = float(result["relevance_score"])
                    result["relevance_score"] = max(1.0, min(5.0, score))
                    return result
                else:
                    logger.warning("AI 返回缺少必要字段: %s", content[:200])
                    return None

            except json.JSONDecodeError:
                logger.warning(
                    "AI 返回 JSON 解析失败 (attempt %d/%d)",
                    attempt + 1,
                    max_retries,
                )
            except Exception:
                logger.exception(
                    "AI 调用失败 (attempt %d/%d)", attempt + 1, max_retries
                )

            if attempt < max_retries - 1:
                wait = 2 ** (attempt + 1)
                await asyncio.sleep(wait)

        return None

    async def process_papers_batch(
        self,
        papers: list[dict[str, str]],
    ) -> list[dict[str, Any] | None]:
        """批量处理论文。papers 为 [{title, abstract, journal}, ...]"""
        tasks = [
            self.process_paper(p["title"], p["abstract"], p.get("journal", ""))
            for p in papers
        ]
        return await asyncio.gather(*tasks)
