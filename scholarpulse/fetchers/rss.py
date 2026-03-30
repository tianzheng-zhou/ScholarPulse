"""RSS 抓取器：从指定期刊的 RSS/Atom Feed 抓取论文"""

from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from typing import Any

import feedparser
import httpx

from .base import BaseFetcher, RawPaper

logger = logging.getLogger(__name__)


class RSSFetcher(BaseFetcher):
    source_name = "rss"

    def __init__(self, feeds: list[dict[str, str]] | None = None) -> None:
        self.feeds = feeds or []

    async def fetch(
        self, keywords: list[str], days: int = 3, **kwargs: Any
    ) -> list[RawPaper]:
        results: list[RawPaper] = []
        seen_ids: set[str] = set()
        cutoff_date = date.today() - timedelta(days=days)

        async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
            for feed_cfg in self.feeds:
                feed_url = feed_cfg.get("url", "").strip()
                feed_name = feed_cfg.get("name", feed_url)

                if not feed_url:
                    logger.warning("RSS 源 '%s' 的 URL 为空，跳过", feed_name)
                    continue

                try:
                    papers = await self._fetch_feed(
                        client, feed_url, feed_name, cutoff_date
                    )
                    for p in papers:
                        if p.source_id not in seen_ids:
                            seen_ids.add(p.source_id)
                            results.append(p)
                except Exception:
                    logger.exception("RSS 源 '%s' 抓取失败", feed_name)

                await asyncio.sleep(1)  # 礼貌间隔

        logger.info("RSS 抓取完成: %d 篇论文（去重后）", len(results))
        return results

    async def _fetch_feed(
        self,
        client: httpx.AsyncClient,
        feed_url: str,
        feed_name: str,
        cutoff_date: date,
    ) -> list[RawPaper]:
        resp = await client.get(feed_url)
        resp.raise_for_status()

        feed = feedparser.parse(resp.text)
        papers: list[RawPaper] = []

        for entry in feed.entries:
            paper = self._parse_entry(entry, feed_name)
            if paper is None:
                continue

            # 日期过滤：没有日期的保留（稍后由数据库去重处理）
            if paper.published_date and paper.published_date < cutoff_date:
                continue

            papers.append(paper)

        logger.info("RSS '%s': 解析到 %d 篇论文", feed_name, len(papers))
        return papers

    @staticmethod
    def _parse_entry(entry: Any, feed_name: str) -> RawPaper | None:
        title = (entry.get("title") or "").strip()
        if not title:
            return None

        # 唯一 ID：优先 entry.id，其次 link
        entry_id = entry.get("id") or entry.get("link") or ""
        if not entry_id:
            return None

        # 链接
        url = entry.get("link") or ""

        # 摘要
        abstract = ""
        if entry.get("summary"):
            # feedparser 可能返回 HTML，做简单清理
            import re
            abstract = re.sub(r"<[^>]+>", "", entry["summary"]).strip()

        # 发表日期
        pub_date = None
        for date_field in ("published_parsed", "updated_parsed"):
            parsed = entry.get(date_field)
            if parsed:
                try:
                    from time import mktime
                    dt = datetime.fromtimestamp(mktime(parsed), tz=timezone.utc)
                    pub_date = dt.date()
                    break
                except (TypeError, ValueError, OverflowError):
                    pass

        # 作者
        authors = []
        if entry.get("authors"):
            for a in entry["authors"]:
                name = a.get("name", "").strip()
                if name:
                    authors.append(name)
        elif entry.get("author"):
            authors = [entry["author"].strip()]

        # DOI：常见于学术 RSS（如 dx.doi.org 链接或 prism:doi）
        doi = ""
        if entry.get("prism_doi"):
            doi = entry["prism_doi"]
        elif url and "doi.org/" in url:
            doi = url.split("doi.org/", 1)[-1]

        return RawPaper(
            source="rss",
            source_id=entry_id,
            title=title,
            authors=authors,
            abstract=abstract,
            url=url,
            published_date=pub_date,
            journal=feed_name,
            doi=doi,
        )
