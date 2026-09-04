"""
Architecture #3 : Self-correcting SQL loop
============================================
Generate SQL, execute, on error feed the error message back to the
LLM and ask it to fix. Up to 3 attempts.

Strengths : recovers from typos, missing JOINs, ambiguous columns.
Weaknesses: silently passes semantically-wrong-but-runnable queries.
Complexity: 2/5
"""
from __future__ import annotations
import time
from . import common as C
from winning_architecture import schema_catalog as SC

NAME = "03_self_correct"

SYSTEM = """You are a SQLite expert. Output exactly one SELECT statement, no markdown."""


def run(question: str) -> dict:
    t0 = time.perf_counter()
    res = C.ArchResult(arch=NAME, question=question)
    block = SC.render_schema_block(SC.retrieve_tables(question, top_k=6))
    last_err = None
    sql = None
    for attempt in range(1, 4):
        prompt = f"{block}\n\nQUESTION: {question}\n"
        if last_err:
            prompt += f"\nPrevious attempt failed with: {last_err}\nFix and try again.\n"
        prompt += "\nSQL:"
        text, online = C.llm_or_offline(SYSTEM, prompt)
        sql = C._strip_sql_fences(text) if online else C.offline_sql_for(question)
        res.sql = sql
        try:
            out = C.safe_exec(sql)
            res.columns = out["columns"]
            res.rows = [dict(zip(out["columns"], r)) for r in out["rows"]]
            res.answer = C.quick_summary(question, sql, res.rows)
            res.success = True
            res.notes = f"succeeded on attempt {attempt}"
            break
        except Exception as e:
            last_err = str(e)
            res.error = last_err
    if not res.success:
        res.answer = f"FAILED after 3 attempts: {res.error}"
    res.elapsed_ms = (time.perf_counter() - t0) * 1000
    return res.to_dict()
