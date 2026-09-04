"""
Architecture #4 : Few-shot example bank (Vanna.ai style)
=========================================================
Curated NL/SQL pairs are retrieved by similarity and shown as
in-context examples. The model copies the patterns.

Strengths : extraordinary accuracy on domains where examples exist;
            cheap to maintain.
Weaknesses: cold-start problem; novel questions outside the bank fail.
Complexity: 2/5
"""
from __future__ import annotations
import time
from . import common as C
from winning_architecture import examples as EX
from winning_architecture import schema_catalog as SC

NAME = "04_few_shot"

SYSTEM = """You are a SQLite expert. Mimic the style of the provided examples. Output a single SELECT, no markdown."""


def run(question: str) -> dict:
    t0 = time.perf_counter()
    res = C.ArchResult(arch=NAME, question=question)
    exs = EX.retrieve_examples(question, top_k=4)
    schema = SC.render_schema_block(SC.retrieve_tables(question, top_k=4))
    user = f"{schema}\n\n{EX.render_examples_block(exs)}\n\nQUESTION: {question}\nSQL:"
    text, online = C.llm_or_offline(SYSTEM, user)
    sql = C._strip_sql_fences(text) if online else (exs[0]["sql"] if exs else "SELECT 1")
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
    res.notes = f"used {len(exs)} examples"
    return res.to_dict()
