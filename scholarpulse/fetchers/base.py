"""抓取器基类：定义统一接口和通用工具"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

from sqlalchemy.orm import Session

from ..database import FetchLog, Paper

logger = logging.getLogger(__name__)


@dataclass
class RawPaper:
    """抓取器返回的统一论文数据结构"""

    source: str
    source_id: str
    title: str
    authors: list[str] = field(default_factory=list)
    abstract: str = ""
    url: str = ""
    published_date: date | None = None
    journal: str = ""
    doi: str = ""
    citation_count: int | None = None
    influential_citation_count: int | None = None


class BaseFetcher(ABC):
    """所有数据源抓取器的基类"""

    source_name: str = ""

    @abstractmethod
    async def fetch(
        self, keywords: list[str], days: int = 3, **kwargs: Any
    ) -> list[RawPaper]:
        """抓取论文，返回 RawPaper 列表"""
        ...

    def save_papers(
        self, db: Session, raw_papers: list[RawPaper]
    ) -> tuple[int, int]:
        """
        将抓取到的论文保存到数据库，执行去重。
        返回 (found_count, new_count)。
        """
        found = len(raw_papers)
        new_count = 0

        for rp in raw_papers:
            # 1. 同源去重：source + source_id
            exists = (
                db.query(Paper)
                .filter(Paper.source == rp.source, Paper.source_id == rp.source_id)
                .first()
            )
            if exists:
                continue

            # 2. 跨源 DOI 去重：若已有同 DOI 论文，补记来源后跳过
            if rp.doi:
                doi_exists = (
                    db.query(Paper).filter(Paper.doi == rp.doi).first()
                )
                if doi_exists:
                    doi_exists.add_source(rp.source)
                    continue

            import json

            paper = Paper(
                source=rp.source,
                source_id=rp.source_id,
                title=rp.title,
                authors=json.dumps(rp.authors, ensure_ascii=False),
                abstract=rp.abstract,
                url=rp.url,
                published_date=rp.published_date,
                journal=rp.journal,
                doi=rp.doi,
                sources=json.dumps([rp.source], ensure_ascii=False),
                citation_count=rp.citation_count,
                influential_citation_count=rp.influential_citation_count,
                fetched_at=datetime.utcnow(),
                ai_processed=False,
            )
            db.add(paper)
            new_count += 1

        db.commit()
        return found, new_count

    def log_fetch(
        self,
        db: Session,
        started_at: datetime,
        papers_found: int,
        papers_new: int,
        status: str = "success",
        error_message: str = "",
    ) -> None:
        log = FetchLog(
            source=self.source_name,
            started_at=started_at,
            finished_at=datetime.utcnow(),
            papers_found=papers_found,
            papers_new=papers_new,
            status=status,
            error_message=error_message,
        )
        db.add(log)
        db.commit()
