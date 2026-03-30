"""IEEE Xplore 抓取器"""

from __future__ import annotations

import asyncio
import logging
import os
from datetime import date, timedelta
from typing import Any

import httpx

from .base import BaseFetcher, RawPaper

logger = logging.getLogger(__name__)

API_BASE = "https://ieeexploreapi.ieee.org/api/v1/search/articles"
# 免费 API Key: 200 次/天
MAX_RESULTS_PER_PAGE = 200


class IEEEXploreFetcher(BaseFetcher):
    source_name = "ieee_xplore"

    def __init__(self) -> None:
        self.api_key = os.getenv("IEEE_API_KEY", "").strip()

    async def fetch(
        self, keywords: list[str], days: int = 3, **kwargs: Any
    ) -> list[RawPaper]:
        if not self.api_key:
            logger.warning("IEEE Xplore API Key 未配置，跳过抓取")
            return []

        results: list[RawPaper] = []
        seen_ids: set[str] = set()

        end_date = date.today()
        start_date = end_date - timedelta(days=days)

        # 将所有关键词组合为一个查询（OR 连接），减少 API 调用次数
        query_text = " OR ".join(f'"{kw}"' for kw in keywords)

        start_record = 1
        async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
            while True:
                params = {
                    "apikey": self.api_key,
                    "querytext": query_text,
                    "start_date": start_date.strftime("%Y%m%d"),
                    "end_date": end_date.strftime("%Y%m%d"),
                    "max_records": MAX_RESULTS_PER_PAGE,
                    "start_record": start_record,
                    "sort_order": "desc",
                    "sort_field": "publication_date",
                }

                try:
                    resp = await client.get(API_BASE, params=params)
                    if resp.status_code == 429:
                        logger.warning("IEEE Xplore 速率限制，等待 60 秒")
                        await asyncio.sleep(60)
                        resp = await client.get(API_BASE, params=params)
                    resp.raise_for_status()
                except Exception:
                    logger.exception("IEEE Xplore 请求失败 (start=%d)", start_record)
                    break

                data = resp.json()
                articles = data.get("articles", [])

                if not articles:
                    break

                for item in articles:
                    paper = self._parse_article(item)
                    if paper and paper.source_id not in seen_ids:
                        seen_ids.add(paper.source_id)
                        results.append(paper)

                total_records = data.get("total_records", 0)
                if start_record + MAX_RESULTS_PER_PAGE > total_records:
                    break
                if start_record + MAX_RESULTS_PER_PAGE > 1000:
                    break

                start_record += MAX_RESULTS_PER_PAGE
                await asyncio.sleep(1)  # 礼貌间隔

        logger.info("IEEE Xplore 抓取完成: %d 篇论文（去重后）", len(results))
        return results

    @staticmethod
    def _parse_article(item: dict[str, Any]) -> RawPaper | None:
        article_number = item.get("article_number", "")
        title = item.get("title", "").strip()
        if not article_number or not title:
            return None

        # 作者
        authors_raw = item.get("authors", {}).get("authors", [])
        authors = [a.get("full_name", "") for a in authors_raw if a.get("full_name")]

        # 摘要
        abstract = item.get("abstract", "").strip()

        # DOI
        doi = item.get("doi", "").strip()

        # URL
        url = ""
        if doi:
            url = f"https://doi.org/{doi}"
        elif item.get("pdf_url"):
            url = item["pdf_url"]

        # 发表日期
        pub_date = None
        date_str = item.get("publication_date", "")
        if date_str:
            pub_date = _parse_ieee_date(date_str)
        if not pub_date:
            # 尝试从 online_date 获取
            online_date = item.get("online_date", "")
            if online_date:
                pub_date = _parse_ieee_date(online_date)

        # 期刊
        journal = item.get("publication_title", "").strip()

        return RawPaper(
            source="ieee_xplore",
            source_id=article_number,
            title=title,
            authors=authors,
            abstract=abstract,
            url=url,
            published_date=pub_date,
            journal=journal,
            doi=doi,
            citation_count=item.get("citing_paper_count"),
        )


def _parse_ieee_date(date_str: str) -> date | None:
    """解析 IEEE 的多种日期格式"""
    import re
    # 格式1: "2 April 2026" 或 "April 2026"
    # 格式2: "2026-04-02" 或 "20260402"
    date_str = date_str.strip()

    # ISO 格式
    try:
        return date.fromisoformat(date_str[:10])
    except ValueError:
        pass

    # "DD Month YYYY" 或 "Month YYYY"
    months = {
        "january": 1, "february": 2, "march": 3, "april": 4,
        "may": 5, "june": 6, "july": 7, "august": 8,
        "september": 9, "october": 10, "november": 11, "december": 12,
    }
    parts = date_str.lower().split()
    try:
        if len(parts) == 3:
            day, month_name, year = int(parts[0]), parts[1], int(parts[2])
            if month_name in months:
                return date(year, months[month_name], day)
        elif len(parts) == 2:
            month_name, year = parts[0], int(parts[1])
            if month_name in months:
                return date(year, months[month_name], 1)
    except (ValueError, KeyError):
        pass

    return None
