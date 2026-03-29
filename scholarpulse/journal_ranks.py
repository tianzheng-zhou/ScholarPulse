"""期刊分级映射表

维护本领域常见期刊的中科院分区、JCR 分区和影响因子信息。
可通过设置页面手动维护。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import json


@dataclass
class JournalRank:
    name: str
    cas_rank: str  # 中科院分区: "1区", "2区", ...
    jcr_rank: str  # JCR 分区: "Q1", "Q2", ...
    impact_factor: float  # 近似影响因子

    def to_dict(self) -> dict[str, Any]:
        return {
            "cas": self.cas_rank,
            "jcr": self.jcr_rank,
            "if": self.impact_factor,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False)


# 本领域常见期刊分级映射表
# key 为期刊名的标准化小写形式，便于模糊匹配
JOURNAL_RANKINGS: dict[str, JournalRank] = {}

_RANKINGS_DATA = [
    JournalRank("Nature Electronics", "1区", "Q1", 30.0),
    JournalRank("Nature Nanotechnology", "1区", "Q1", 38.0),
    JournalRank("Nature Materials", "1区", "Q1", 37.0),
    JournalRank("Advanced Materials", "1区", "Q1", 28.0),
    JournalRank("Advanced Functional Materials", "1区", "Q1", 18.0),
    JournalRank("Advanced Electronic Materials", "2区", "Q1", 6.0),
    JournalRank("ACS Nano", "1区", "Q1", 15.0),
    JournalRank("Nano Letters", "1区", "Q1", 10.0),
    JournalRank("IEEE Electron Device Letters", "2区", "Q1", 4.5),
    JournalRank("IEEE Transactions on Electron Devices", "3区", "Q2", 3.0),
    JournalRank("IEEE Journal of the Electron Devices Society", "3区", "Q2", 2.5),
    JournalRank("Neuromorphic Computing and Engineering", "", "Q2", 3.0),
    JournalRank("Applied Physics Letters", "2区", "Q1", 3.5),
    JournalRank("ACS Applied Materials & Interfaces", "1区", "Q1", 9.5),
    JournalRank("Nano Energy", "1区", "Q1", 16.0),
    JournalRank("Small", "1区", "Q1", 13.0),
    JournalRank("Nanoscale", "2区", "Q1", 6.7),
    JournalRank("Journal of Materials Chemistry C", "2区", "Q1", 6.4),
    JournalRank("Thin Solid Films", "4区", "Q3", 2.0),
    JournalRank("Semiconductor Science and Technology", "4区", "Q3", 1.8),
    JournalRank("Journal of Applied Physics", "3区", "Q2", 2.7),
    JournalRank("Science", "1区", "Q1", 56.0),
    JournalRank("Nature", "1区", "Q1", 64.0),
]


def _init_rankings() -> None:
    for jr in _RANKINGS_DATA:
        key = jr.name.lower().strip()
        JOURNAL_RANKINGS[key] = jr


_init_rankings()


def lookup_journal_rank(journal_name: str) -> JournalRank | None:
    """根据期刊名查找分级信息，支持模糊匹配"""
    if not journal_name:
        return None

    name_lower = journal_name.lower().strip()

    # 精确匹配
    if name_lower in JOURNAL_RANKINGS:
        return JOURNAL_RANKINGS[name_lower]

    # 包含匹配
    for key, rank in JOURNAL_RANKINGS.items():
        if key in name_lower or name_lower in key:
            return rank

    return None


def get_journal_weight(rank: JournalRank | None) -> float:
    """根据期刊等级返回权重因子（用于排序）"""
    if rank is None:
        return 1.0

    cas = rank.cas_rank
    if cas == "1区":
        return 2.0
    elif cas == "2区":
        return 1.5
    elif cas == "3区":
        return 1.2
    else:
        return 1.0
