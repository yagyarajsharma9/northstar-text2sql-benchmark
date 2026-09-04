"""
Architecture #2 : Schema-RAG NL2SQL
====================================
Retrieve only the most relevant tables (top-k by keyword overlap) and
feed those into the SQL generator. Reduces token use and hallucination
on a large schema.

Strengths : scales to 100+ tables, lower cost, less context noise.
Weaknesses: retrieval can drop a needed table; no error recovery.
Complexity: 2/5
"""
from __future__ import annotations
import time
from . import common as C
from winning_architecture import schema_catalog as SC

NAME = "02_schema_rag"

SYSTEM = """You are a SQLite expert. Output a single SELECT statement using ONLY the relevant tables provided. No markdown, no commentary."""


def run(question: str) -> dict:
    t0 = time.perf_counter()
    res = C.ArchResult(arch=NAME, question=question)
    tables = SC.retrieve_tables(question, top_k=6)
    block = SC.render_schema_block(tables)
    user = f"{block}\n\nQUESTION: {question}\n\nSQL:"
    text, online = C.llm_or_offline(SYSTEM, user)
    sql = C._strip_sql_fences(text) if online else C.offline_sql_for(question)
    res.sql = sql
    try:
        out = C.safe_exec(sql)
        res.columns = out["columns"]
        res.rows = [dict(zip(out["columns"], r)) for r in out["rows"]]
        res.answer = C.quick_summary(question, sql, res.rows)
        res.success = True
    except Exception as e:
        res.error, res.answer = str(e), f"FAILED: {e}"
    res.elapsed_ms = (time.perf_counter() - t0) * 1000
    res.notes = f"retrieved tables: {tables[:6]}"
    return res.to_dict()
