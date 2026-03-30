"""数据库初始化与模型定义"""

from __future__ import annotations

import json
from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    Column,
    Date,
    DateTime,
    Float,
    Integer,
    Text,
    UniqueConstraint,
    create_engine,
    event,
)
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .config import BASE_DIR

import os

DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)

DATABASE_PATH = DATA_DIR / "scholarpulse.db"
DATABASE_URL = os.getenv("DATABASE_URL", f"sqlite:///{DATABASE_PATH}")


class Base(DeclarativeBase):
    pass


class Paper(Base):
    __tablename__ = "papers"
    __table_args__ = (
        UniqueConstraint("source", "source_id", name="uq_source_source_id"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    source = Column(Text, nullable=False)
    source_id = Column(Text, nullable=False)
    title = Column(Text, nullable=False)
    title_zh = Column(Text)
    authors = Column(Text)  # JSON list
    abstract = Column(Text)
    summary_zh = Column(Text)
    relevance_score = Column(Float)
    keywords = Column(Text)  # JSON list
    url = Column(Text)
    published_date = Column(Date)
    fetched_at = Column(DateTime, default=datetime.utcnow)
    ai_processed = Column(Boolean, default=False)
    journal = Column(Text)
    journal_rank = Column(Text)  # JSON, e.g. {"cas": "1区", "jcr": "Q1", "if": 30.2}
    citation_count = Column(Integer)
    influential_citation_count = Column(Integer)
    doi = Column(Text)

    def get_authors(self) -> list[str]:
        if not self.authors:
            return []
        return json.loads(self.authors)

    def set_authors(self, authors: list[str]) -> None:
        self.authors = json.dumps(authors, ensure_ascii=False)

    def get_keywords(self) -> list[str]:
        if not self.keywords:
            return []
        return json.loads(self.keywords)

    def set_keywords(self, kw: list[str]) -> None:
        self.keywords = json.dumps(kw, ensure_ascii=False)

    def get_journal_rank(self) -> dict[str, Any]:
        if not self.journal_rank:
            return {}
        return json.loads(self.journal_rank)

    def set_journal_rank(self, rank: dict[str, Any]) -> None:
        self.journal_rank = json.dumps(rank, ensure_ascii=False)


class FetchLog(Base):
    __tablename__ = "fetch_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    source = Column(Text, nullable=False)
    started_at = Column(DateTime, nullable=False)
    finished_at = Column(DateTime)
    papers_found = Column(Integer, default=0)
    papers_new = Column(Integer, default=0)
    status = Column(Text, default="running")
    error_message = Column(Text)


# ── Engine & Session ──

engine = create_engine(DATABASE_URL, echo=False)


@event.listens_for(engine, "connect")
def _set_sqlite_pragma(dbapi_conn: Any, _: Any) -> None:
    cursor = dbapi_conn.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


SessionLocal = sessionmaker(bind=engine)


def init_db() -> None:
    """创建所有表"""
    Base.metadata.create_all(bind=engine)


def get_db() -> Session:  # type: ignore[type-arg]
    db = SessionLocal()
    try:
        return db
    except Exception:
        db.close()
        raise
