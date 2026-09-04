"""Shared helpers used by all architecture variants."""
from __future__ import annotations
import os
import re
import time
from dataclasses import dataclass, field, asdict

# Re-use the production DB layer + schema + examples to keep the lab honest.
from winning_architecture import db, schema_catalog, examples as ex_bank
from winning_architecture.engine import _llm, _strip_sql_fences


@dataclass
class ArchResult:
    arch: str
    question: str
    answer: str = ""
    sql: str | None = None
    rows: list = field(default_factory=list)
    columns: list = field(default_factory=list)
    citations: list = field(default_factory=list)
    elapsed_ms: float = 0.0
    error: str | None = None
    success: bool = False
    notes: str = ""

    def to_dict(self):
        d = asdict(self)
        d["row_count"] = len(self.rows)
        return d


def time_block():
    return time.perf_counter()


def safe_exec(sql: str, max_rows: int = 200):
    return db.execute_sql(sql, max_rows=max_rows)


def llm_or_offline(system: str, user: str, max_tokens: int = 600) -> tuple[str, bool]:
    """Returns (text, was_online). Uses offline example-bank fallback if no key."""
    try:
        return _llm(system, user, max_tokens=max_tokens), True
    except RuntimeError:
        return "", False


def offline_sql_for(question: str) -> str:
    matches = ex_bank.retrieve_examples(question, top_k=1)
    return matches[0]["sql"] if matches else "SELECT 'offline' AS msg LIMIT 1"


def quick_summary(question: str, sql: str, rows: list) -> str:
    if not rows:
        return "Query ran but returned no rows."
    sample = rows[0]
    head = ", ".join(f"{k}={v}" for k, v in list(sample.items())[:3])
    return f"Returned {len(rows)} row(s). First: {head}."
