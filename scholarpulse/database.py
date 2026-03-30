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
    sources = Column(Text)  # JSON list, e.g. ["arxiv", "semantic_scholar"]
    relevance_reason = Column(Text)
    ai_fail_count = Column(Integer, default=0)

    def get_sources(self) -> list[str]:
        if not self.sources:
            return [self.source] if self.source else []
        return json.loads(self.sources)

    def add_source(self, src: str) -> None:
        current = self.get_sources()
        if src not in current:
            current.append(src)
            self.sources = json.dumps(current, ensure_ascii=False)

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

engine = create_engine(
    DATABASE_URL,
    echo=False,
    pool_size=20,
    max_overflow=40,
    pool_timeout=120,
    pool_pre_ping=True,
)


@event.listens_for(engine, "connect")
def _set_sqlite_pragma(dbapi_conn: Any, _: Any) -> None:
    cursor = dbapi_conn.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


SessionLocal = sessionmaker(bind=engine)


def init_db() -> None:
    """创建所有表 + 自动迁移新列"""
    Base.metadata.create_all(bind=engine)
    # 自动添加新列（SQLite ALTER TABLE ADD COLUMN）
    _migrate_columns()


def _migrate_columns() -> None:
    """检查并添加缺失的列"""
    import sqlite3
    conn = sqlite3.connect(str(DATABASE_PATH))
    cursor = conn.cursor()
    cursor.execute("PRAGMA table_info(papers)")
    existing = {row[1] for row in cursor.fetchall()}
    migrations = [
        ("relevance_reason", "TEXT"),
        ("ai_fail_count", "INTEGER DEFAULT 0"),
        ("sources", "TEXT"),
    ]
    for col_name, col_type in migrations:
        if col_name not in existing:
            cursor.execute(f"ALTER TABLE papers ADD COLUMN {col_name} {col_type}")
    # 为已有数据补充 sources 字段
    cursor.execute(
        "UPDATE papers SET sources = json_array(source) WHERE sources IS NULL"
    )
    conn.commit()
    conn.close()


def get_db() -> Session:  # type: ignore[type-arg]
    db = SessionLocal()
    try:
        return db
    except Exception:
        db.close()
        raise
