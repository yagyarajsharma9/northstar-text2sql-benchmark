"""
Architecture #7 : DAIL-SQL / C3-SQL (skeleton-aware retrieval)
================================================================
DAIL-SQL uses masked-question similarity (replace constants with
placeholders) to retrieve nearest examples. C3-SQL adds clear-prompt
calibration. Both push BIRD-SQL accuracy to state of the art.

Strengths : best example-retrieval quality; resilient to phrasing drift.
Weaknesses: needs a maintained example bank; embedding service helpful.
Complexity: 4/5

Stub uses a regex skeletoniser + the existing example bank.
"""
from __future__ import annotations
import re
import time
from . import common as C
from winning_architecture import examples as EX
from winning_architecture import schema_catalog as SC

NAME = "07_dail_c3"

SYSTEM = """You are a SQLite expert. The following are skeleton-similar examples for the user question.
Mimic the most relevant skeleton. Output a single SELECT, no markdown."""


def skeletonize(q: str) -> str:
    q = re.sub(r"\b\d+(\.\d+)?\b", "<num>", q)
    q = re.sub(r"\b(20\d{2}|q[1-4])\b", "<period>", q, flags=re.IGNORECASE)
    q = re.sub(r"\b[A-Z]{2,}-[A-Z0-9-]+\b", "<code>", q)
    return q.lower()


def run(question: str) -> dict:
    t0 = time.perf_counter()
    res = C.ArchResult(arch=NAME, question=question)
    skel_q = skeletonize(question)
    # Score examples by word overlap on skeletonised forms
    qtok = set(re.findall(r"[a-z]{3,}", skel_q))
    scored = []
    for ex in EX.EXAMPLES:
        etok = set(re.findall(r"[a-z]{3,}", skeletonize(ex["q"])))
        scored.append((len(qtok & etok), ex))
    scored.sort(key=lambda x: x[0], reverse=True)
    chosen = [e for _, e in scored[:5] if _]
    schema = SC.render_schema_block(SC.retrieve_tables(question, top_k=5))
    user = f"{schema}\n\n{EX.render_examples_block(chosen)}\n\nQ: {question}\nSQL:"
    text, online = C.llm_or_offline(SYSTEM, user)
    sql = C._strip_sql_fences(text) if online else (chosen[0]["sql"] if chosen else C.offline_sql_for(question))
    res.sql = sql
    try:
        out = C.safe_exec(sql)
        res.columns = out["columns"]
        res.rows = [dict(zip(out["columns"], r)) for r in out["rows"]]
        res.success = True
        res.answer = C.quick_summary(question, sql, res.rows)
    except Exception as e:
        res.error, res.answer = str(e), f"FAILED: {e}"
    res.elapsed_ms = (time.perf_counter() - t0) * 1000
    res.notes = f"skeleton: {skel_q[:80]}"
    return res.to_dict()
