"""
Architecture #1 : Naive Text-to-SQL (single shot)
=================================================
The simplest possible thing. One LLM call, full schema dumped in,
no validation, no retry. Useful as a lower bound on quality.

Strengths : fastest, simplest, cheapest.
Weaknesses: hallucinates columns, gets joins wrong, no recovery.
Complexity: 1/5
"""
from __future__ import annotations
import time
from . import common as C
from winning_architecture import schema_catalog as SC

NAME = "01_naive_text2sql"

SYSTEM = """You are a SQLite expert. Output a single SELECT statement (no markdown, no commentary)
that answers the user's question. Use only tables/columns from the schema below."""


def _full_schema() -> str:
    parts = []
    for t, info in SC.TABLES.items():
        parts.append(f"{t}({info['cols']})")
    return "\n".join(parts)


def run(question: str) -> dict:
    t0 = time.perf_counter()
    res = C.ArchResult(arch=NAME, question=question)
    schema = _full_schema()
    user = f"SCHEMA:\n{schema}\n\nQUESTION: {question}\n\nSQL:"
    text, online = C.llm_or_offline(SYSTEM, user, max_tokens=400)
    sql = C._strip_sql_fences(text) if online else C.offline_sql_for(question)
    res.sql = sql
    try:
        out = C.safe_exec(sql)
        res.columns = out["columns"]
        res.rows = [dict(zip(out["columns"], r)) for r in out["rows"]]
        res.answer = C.quick_summary(question, sql, res.rows)
        res.success = True
    except Exception as e:
        res.error = str(e)
        res.answer = f"FAILED: {e}"
    res.elapsed_ms = (time.perf_counter() - t0) * 1000
    res.notes = "single-shot, no retry, full schema dump"
    return res.to_dict()
