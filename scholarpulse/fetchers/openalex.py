"""OpenAlex 抓取器"""

from __future__ import annotations

import asyncio
import logging
from datetime import date, timedelta
from typing import Any

import httpx

from .base import BaseFetcher, RawPaper

logger = logging.getLogger(__name__)

API_BASE = "https://api.openalex.org"
# OpenAlex 建议 polite pool：设 mailto 参数可获得更高速率
PER_PAGE = 200  # 每页最多 200


class OpenAlexFetcher(BaseFetcher):
    source_name = "openalex"

    def __init__(self, email: str = "") -> None:
        self.email = email

    async def fetch(
        self, keywords: list[str], days: int = 3, **kwargs: Any
    ) -> list[RawPaper]:
        results: list[RawPaper] = []
        seen_ids: set[str] = set()

        end_date = date.today()
        start_date = end_date - timedelta(days=days)

        async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
            for kw in keywords:
                try:
                    papers = await self._search_keyword(client, kw, start_date, end_date)
                    for p in papers:
                        if p.source_id not in seen_ids:
                            seen_ids.add(p.source_id)
                            results.append(p)
                except Exception:
                    logger.exception("OpenAlex 搜索关键词 '%s' 失败", kw)
                await asyncio.sleep(0.2)

        logger.info("OpenAlex 抓取完成: %d 篇论文（去重后）", len(results))
        return results

    async def _search_keyword(
        self, client: httpx.AsyncClient, keyword: str, start_date: date, end_date: date
    ) -> list[RawPaper]:
        papers: list[RawPaper] = []

        params: dict[str, Any] = {
            "search": keyword,
            "filter": f"from_publication_date:{start_date},to_publication_date:{end_date}",
            "per_page": PER_PAGE,
            "sort": "publication_date:desc",
            "select": "id,doi,title,authorships,publication_date,primary_location,cited_by_count,abstract_inverted_index",
        }
        if self.email:
            params["mailto"] = self.email

        page = 1
        while True:
            params["page"] = page
            try:
                resp = await client.get(f"{API_BASE}/works", params=params)
                if resp.status_code == 429:
                    logger.warning("OpenAlex 速率限制，等待 10 秒")
                    await asyncio.sleep(10)
                    resp = await client.get(f"{API_BASE}/works", params=params)
                resp.raise_for_status()
            except Exception:
                logger.exception("OpenAlex 请求失败 (keyword='%s', page=%d)", keyword, page)
                break

            data = resp.json()
            works = data.get("results", [])

            if not works:
                break

            for item in works:
                paper = self._parse_work(item)
                if paper:
                    papers.append(paper)

            meta = data.get("meta", {})
            total_count = meta.get("count", 0)
            if page * PER_PAGE >= total_count or page * PER_PAGE >= 1000:
                break

            page += 1
            await asyncio.sleep(0.2)

        return papers

    @staticmethod
    def _reconstruct_abstract(inverted_index: dict[str, list[int]]) -> str:
        """从 OpenAlex 的 inverted index 格式还原摘要文本"""
        if not inverted_index:
            return ""
        word_positions: list[tuple[int, str]] = []
        for word, positions in inverted_index.items():
            for pos in positions:
                word_positions.append((pos, word))
        word_positions.sort(key=lambda x: x[0])
        return " ".join(w for _, w in word_positions)

    @staticmethod
    def _parse_work(item: dict[str, Any]) -> RawPaper | None:
        openalex_id = item.get("id", "")
        if not openalex_id:
            return None
        # OpenAlex ID 格式: https://openalex.org/W1234567890 → W1234567890
        source_id = openalex_id.split("/")[-1]

        title = item.get("title") or ""
        if not title:
            return None

        # DOI
        doi_raw = item.get("doi") or ""
        doi = doi_raw.replace("https://doi.org/", "") if doi_raw else ""

        # 作者
        authorships = item.get("authorships") or []
        authors = []
        for a in authorships:
            author_info = a.get("author", {})
            name = author_info.get("display_name", "")
            if name:
                authors.append(name)

        # 发表日期
        pub_date = None
        date_str = item.get("publication_date")
        if date_str:
            try:
                pub_date = date.fromisoformat(date_str)
            except ValueError:
                pass

        # 期刊
        journal = ""
        primary_loc = item.get("primary_location") or {}
        source_info = primary_loc.get("source") or {}
        journal = source_info.get("display_name") or ""

        # 摘要
        abstract = OpenAlexFetcher._reconstruct_abstract(
            item.get("abstract_inverted_index") or {}
        )

        # URL
        url = doi_raw or openalex_id

        return RawPaper(
            source="openalex",
            source_id=source_id,
            title=title,
            authors=authors,
            abstract=abstract,
            url=url,
            published_date=pub_date,
            journal=journal,
            doi=doi,
            citation_count=item.get("cited_by_count"),
        )
