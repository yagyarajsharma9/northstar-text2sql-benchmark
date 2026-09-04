"""
Architecture #8 : Router + Multi-Agent
========================================
A planner classifies the question, then dispatches to a specialist:
  - SQL agent (structured data)
  - Doc agent (policies / SOPs over FTS5)
  - Math/Compute agent (Python evaluation for ratios, totals)
A combiner merges the result.

Strengths : best when questions span multiple data types.
Weaknesses: brittle if the router mis-classifies.
Complexity: 3/5
"""
from __future__ import annotations
import re
import time
from . import common as C
from . import arch_02_schema_rag as sql_agent
from winning_architecture import db

NAME = "08_router_multiagent"

DATA_RE = re.compile(r"\b(how many|count|total|sum|average|top|list|show|wells?|invoice|production|incident|amount|usd|bbl|q[1-4]|2024|2025|2026)\b", re.IGNORECASE)
DOC_RE = re.compile(r"\b(policy|sop|procedure|approval policy|guideline|how do we|process for|threshold|approval chain)\b", re.IGNORECASE)


def doc_agent(question: str):
    return db.fts_search(question, top_k=5)


def run(question: str, history: list | None = None) -> dict:
    t0 = time.perf_counter()
    res = C.ArchResult(arch=NAME, question=question)
    # History-naive router: arch 08 keeps things simple - pure rules on the
    # current question. This is what makes it weaker than arch 10 on
    # multi-turn follow-ups like "what about that file again?".
    has_data = bool(DATA_RE.search(question))
    has_doc = bool(DOC_RE.search(question))

    parts: list[str] = []
    if has_data:
        sql_res = sql_agent.run(question)
        res.sql = sql_res.get("sql")
        res.rows = sql_res.get("rows", [])
        res.columns = sql_res.get("columns", [])
        res.success = sql_res.get("success", False)
        if res.success:
            parts.append(C.quick_summary(question, res.sql or "", res.rows))
    if has_doc or not has_data:
        cites = doc_agent(question)
        res.citations = cites
        if cites:
            parts.append(f"See policy: {cites[0]['file_name']}")

    res.answer = " ".join(parts) or "I couldn't classify this question."
    res.elapsed_ms = (time.perf_counter() - t0) * 1000
    res.notes = f"router: data={has_data}, doc={has_doc}"
    return res.to_dict()
