"""
Architecture #6 : DIN-SQL  (Decomposed In-context, Pourreza & Rafiei 2023)
=========================================================================
Decompose into 4 stages:
  1) schema link  - identify which tables/columns are relevant
  2) classify     - question type (easy / non-nested / nested / set ops)
  3) generate     - tailored generator for the class
  4) self-correct - one fix-up pass

Strengths : strong on Spider/BIRD; better on hard joins.
Weaknesses: many calls per query; latency.
Complexity: 4/5
"""
from __future__ import annotations
import time
from . import common as C
from winning_architecture import schema_catalog as SC

NAME = "06_din_sql"

SYS_LINK = "List the table.column names from the schema that the question needs. JSON array of strings only."
SYS_CLASS = "Classify the SQL the question needs as one of: EASY, NON_NESTED, NESTED, SET_OPS. Output one word."
SYS_GEN = "Output a single SQLite SELECT statement only."
SYS_FIX = "Critique then output a corrected single SQLite SELECT, no markdown."


def run(question: str) -> dict:
    t0 = time.perf_counter()
    res = C.ArchResult(arch=NAME, question=question)
    schema = SC.render_schema_block(SC.retrieve_tables(question, top_k=8))

    # Stage 1: schema link
    link, online = C.llm_or_offline(SYS_LINK, f"{schema}\n\nQ: {question}", 200)
    # Stage 2: classify
    cls, _ = C.llm_or_offline(SYS_CLASS, f"Q: {question}", 30) if online else ("EASY", False)
    # Stage 3: generate (we condition on the schema link snippet)
    gen_prompt = (f"{schema}\n\nLink: {link}\nClass: {cls.strip().upper()}\n\nQ: {question}\nSQL:")
    sql_text, _ = C.llm_or_offline(SYS_GEN, gen_prompt, 500) if online else ("", False)
    sql = C._strip_sql_fences(sql_text) if online else C.offline_sql_for(question)
    res.sql = sql

    try:
        out = C.safe_exec(sql)
        res.columns = out["columns"]
        res.rows = [dict(zip(out["columns"], r)) for r in out["rows"]]
        res.success = True
    except Exception:
        # Stage 4: self-correct
        fix_prompt = f"{schema}\n\nQ: {question}\nBuggy SQL: {sql}\nFix:"
        fix_text, online2 = C.llm_or_offline(SYS_FIX, fix_prompt, 500)
        sql = C._strip_sql_fences(fix_text) if online2 else sql
        res.sql = sql
        try:
            out = C.safe_exec(sql)
            res.columns = out["columns"]
            res.rows = [dict(zip(out["columns"], r)) for r in out["rows"]]
            res.success = True
        except Exception as e:
            res.error = str(e)
    res.answer = C.quick_summary(question, res.sql, res.rows) if res.success else f"FAILED: {res.error}"
    res.elapsed_ms = (time.perf_counter() - t0) * 1000
    res.notes = f"class={cls.strip()[:20] if isinstance(cls, str) else 'NA'}"
    return res.to_dict()
