"""Semantic Scholar 抓取器"""

from __future__ import annotations

import asyncio
import logging
from datetime import date, timedelta
from typing import Any

import httpx

from .base import BaseFetcher, RawPaper

logger = logging.getLogger(__name__)

API_BASE = "https://api.semanticscholar.org/graph/v1"
FIELDS = (
    "paperId,externalIds,title,abstract,authors,publicationDate,"
    "journal,citationCount,influentialCitationCount,url"
)
# 免费额度: 100 请求/5 分钟 → 每次请求间隔至少 3 秒
REQUEST_INTERVAL = 3.2


class SemanticScholarFetcher(BaseFetcher):
    source_name = "semantic_scholar"

    async def fetch(
        self, keywords: list[str], days: int = 3, **kwargs: Any
    ) -> list[RawPaper]:
        results: list[RawPaper] = []
        seen_ids: set[str] = set()

        end_date = date.today()
        start_date = end_date - timedelta(days=days)
        date_range = f"{start_date}:{end_date}"

        async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
            for kw in keywords:
                try:
                    papers = await self._search_keyword(
                        client, kw, date_range
                    )
                    for p in papers:
                        if p.source_id not in seen_ids:
                            seen_ids.add(p.source_id)
                            results.append(p)
                except Exception:
                    logger.exception("Semantic Scholar 搜索关键词 '%s' 失败", kw)

                await asyncio.sleep(REQUEST_INTERVAL)

        logger.info(
            "Semantic Scholar 抓取完成: %d 篇论文（去重后）", len(results)
        )
        return results

    async def _search_keyword(
        self, client: httpx.AsyncClient, keyword: str, date_range: str
    ) -> list[RawPaper]:
        papers: list[RawPaper] = []
        offset = 0
        limit = 100
        max_retries_429 = 3

        while True:
            params = {
                "query": keyword,
                "fields": FIELDS,
                "publicationDateOrYear": date_range,
                "offset": offset,
                "limit": limit,
            }

            retries = 0
            while True:
                resp = await client.get(f"{API_BASE}/paper/search", params=params)
                if resp.status_code == 429:
                    retries += 1
                    if retries > max_retries_429:
                        logger.error("Semantic Scholar 达到最大重试次数，跳过关键词 '%s'", keyword)
                        return papers
                    logger.warning("Semantic Scholar 速率限制，等待 60 秒 (%d/%d)", retries, max_retries_429)
                    await asyncio.sleep(60)
                    continue
                break

            resp.raise_for_status()
            data = resp.json()

            for item in data.get("data", []):
                paper = self._parse_paper(item)
                if paper:
                    papers.append(paper)

            total = data.get("total", 0)
            next_offset = data.get("next")
            if next_offset is None or offset + limit >= total or offset + limit >= 500:
                break

            offset = next_offset
            await asyncio.sleep(REQUEST_INTERVAL)

        return papers

    @staticmethod
    def _parse_paper(item: dict[str, Any]) -> RawPaper | None:
        paper_id = item.get("paperId")
        title = item.get("title")
        if not paper_id or not title:
            return None

        # 提取 DOI
        external_ids = item.get("externalIds") or {}
        doi = external_ids.get("DOI", "")

        # 解析作者
        authors_raw = item.get("authors") or []
        authors = [a.get("name", "") for a in authors_raw if a.get("name")]

        # 解析日期
        pub_date = None
        date_str = item.get("publicationDate")
        if date_str:
            try:
                pub_date = date.fromisoformat(date_str)
            except ValueError:
                pass

        # 期刊
        journal_info = item.get("journal") or {}
        journal_name = journal_info.get("name", "")

        return RawPaper(
            source="semantic_scholar",
            source_id=paper_id,
            title=title,
            authors=authors,
            abstract=item.get("abstract") or "",
            url=item.get("url") or f"https://www.semanticscholar.org/paper/{paper_id}",
            published_date=pub_date,
            journal=journal_name,
            doi=doi,
            citation_count=item.get("citationCount"),
            influential_citation_count=item.get("influentialCitationCount"),
        )
