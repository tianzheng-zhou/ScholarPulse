"""arXiv 抓取器"""

from __future__ import annotations

import asyncio
import logging
import xml.etree.ElementTree as ET
from datetime import date, timedelta
from typing import Any
from urllib.parse import quote

import httpx

from .base import BaseFetcher, RawPaper

logger = logging.getLogger(__name__)

ARXIV_API = "https://export.arxiv.org/api/query"

# arXiv XML 命名空间
NS = {
    "atom": "http://www.w3.org/2005/Atom",
    "arxiv": "http://arxiv.org/schemas/atom",
}


class ArxivFetcher(BaseFetcher):
    source_name = "arxiv"

    def __init__(self, categories: list[str] | None = None) -> None:
        self.categories = categories or []

    async def fetch(
        self, keywords: list[str], days: int = 3, **kwargs: Any
    ) -> list[RawPaper]:
        query = self._build_query(keywords)
        results: list[RawPaper] = []
        seen_ids: set[str] = set()

        start = 0
        max_results = 200  # arXiv 每次最多返回
        cutoff_date = date.today() - timedelta(days=days)

        async with httpx.AsyncClient(timeout=60.0, follow_redirects=True) as client:
            while True:
                params = {
                    "search_query": query,
                    "start": start,
                    "max_results": max_results,
                    "sortBy": "submittedDate",
                    "sortOrder": "descending",
                }

                try:
                    resp = await client.get(ARXIV_API, params=params)
                    if resp.status_code == 429:
                        logger.warning("arXiv 速率限制，等待 30 秒")
                        await asyncio.sleep(30)
                        resp = await client.get(ARXIV_API, params=params)
                    resp.raise_for_status()
                except Exception:
                    logger.exception("arXiv API 请求失败 (start=%d)", start)
                    break

                papers = self._parse_response(resp.text, cutoff_date)
                if not papers:
                    break

                for p in papers:
                    if p.source_id not in seen_ids:
                        seen_ids.add(p.source_id)
                        results.append(p)

                # 如果返回的论文数少于请求量，说明没有更多了
                if len(papers) < max_results:
                    break

                # 如果最后一篇论文已经超出日期范围，停止
                if papers[-1].published_date and papers[-1].published_date < cutoff_date:
                    break

                start += max_results
                if start >= 1000:
                    break

                # arXiv 建议请求间隔 3 秒
                await asyncio.sleep(3)

        logger.info("arXiv 抓取完成: %d 篇论文（去重后）", len(results))
        return results

    def _build_query(self, keywords: list[str]) -> str:
        """构建 arXiv 搜索查询：多关键词 OR 组合 + 分类筛选"""
        # 关键词部分：用 OR 连接
        kw_parts = [f'all:"{kw}"' for kw in keywords]
        kw_query = " OR ".join(kw_parts)

        # 分类部分
        if self.categories:
            cat_parts = [f"cat:{cat}" for cat in self.categories]
            cat_query = " OR ".join(cat_parts)
            return f"({kw_query}) AND ({cat_query})"

        return kw_query

    def _parse_response(
        self, xml_text: str, cutoff_date: date
    ) -> list[RawPaper]:
        papers: list[RawPaper] = []

        try:
            root = ET.fromstring(xml_text)
        except ET.ParseError:
            logger.error("arXiv 响应 XML 解析失败")
            return papers

        for entry in root.findall("atom:entry", NS):
            paper = self._parse_entry(entry)
            if paper is None:
                continue
            # 按日期过滤
            if paper.published_date and paper.published_date < cutoff_date:
                continue
            papers.append(paper)

        return papers

    @staticmethod
    def _parse_entry(entry: ET.Element) -> RawPaper | None:
        # arXiv ID
        id_elem = entry.find("atom:id", NS)
        if id_elem is None or id_elem.text is None:
            return None

        arxiv_url = id_elem.text.strip()
        # 从 URL 提取 ID: http://arxiv.org/abs/2301.12345v1 → 2301.12345
        arxiv_id = arxiv_url.split("/abs/")[-1]
        # 去掉版本号
        if "v" in arxiv_id.split(".")[-1]:
            arxiv_id = arxiv_id.rsplit("v", 1)[0]

        title_elem = entry.find("atom:title", NS)
        title = (title_elem.text or "").strip().replace("\n", " ") if title_elem is not None else ""
        if not title:
            return None

        # 摘要
        summary_elem = entry.find("atom:summary", NS)
        abstract = (summary_elem.text or "").strip().replace("\n", " ") if summary_elem is not None else ""

        # 作者
        authors = []
        for author_elem in entry.findall("atom:author", NS):
            name_elem = author_elem.find("atom:name", NS)
            if name_elem is not None and name_elem.text:
                authors.append(name_elem.text.strip())

        # 发布日期
        pub_date = None
        published_elem = entry.find("atom:published", NS)
        if published_elem is not None and published_elem.text:
            try:
                pub_date = date.fromisoformat(published_elem.text[:10])
            except ValueError:
                pass

        # PDF 链接
        pdf_url = arxiv_url
        for link in entry.findall("atom:link", NS):
            if link.get("title") == "pdf":
                pdf_url = link.get("href", arxiv_url)
                break

        # DOI（如果有）
        doi_elem = entry.find("arxiv:doi", NS)
        doi = (doi_elem.text or "").strip() if doi_elem is not None else ""

        # 期刊引用
        journal_elem = entry.find("arxiv:journal_ref", NS)
        journal = (journal_elem.text or "").strip() if journal_elem is not None else ""

        return RawPaper(
            source="arxiv",
            source_id=arxiv_id,
            title=title,
            authors=authors,
            abstract=abstract,
            url=arxiv_url,
            published_date=pub_date,
            journal=journal,
            doi=doi,
        )
