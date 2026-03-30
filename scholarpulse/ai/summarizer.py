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
<role>你是一位电子信息领域的资深学术助手，擅长分析学术论文。</role>
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
2. 用一句中文（30字以内）概括论文核心贡献，仅基于摘要内容
3. 根据用户研究方向，对论文打 1-5 分相关性评分（5 为最相关）
4. 简述评分理由
5. 提取 3-5 个英文关键词
6. 如果期刊是顶级期刊（如 Nature/Science/Advanced Materials 等），评分时可适当酌情加分
</instructions>

<output_schema>
严格返回如下 JSON，不要包含任何其他内容：
{{
  "title_zh": "中文标题",
  "summary_zh": "一句话中文总结（30字以内）",
  "relevance_score": 4,
  "relevance_reason": "简述为什么给这个分数",
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
