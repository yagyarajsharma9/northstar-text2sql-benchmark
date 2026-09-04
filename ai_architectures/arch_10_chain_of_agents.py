"""
Architecture #10 : Chain-of-Agents with Validator Gate (THE WINNER)
======================================================================
Production version lives in /winning_architecture. This module is a thin
adapter so the benchmark can score it alongside the other 9.

Pipeline: Router -> Schema-RAG -> Example-Retrieve -> SQL-Gen ->
          Validator Gate -> Executor (with self-correct loop) ->
          Doc-RAG enrichment -> Summarizer

Strengths : best accuracy + auditable trace + safe SQL guardrails +
            handles questions that span data and policies.
Weaknesses: most calls per query; highest latency in the worst case.
Complexity: 5/5
"""
from __future__ import annotations
import time
from . import common as C
from winning_architecture import engine

NAME = "10_chain_of_agents"


def run(question: str, history: list | None = None) -> dict:
    t0 = time.perf_counter()
    pr = engine.run_chain(question, history=history)
    return {
        "arch": NAME,
        "question": question,
        "answer": pr.answer,
        "sql": pr.sql,
        "columns": pr.columns,
        "rows": pr.rows,
        "row_count": len(pr.rows),
        "citations": pr.citations,
        "elapsed_ms": (time.perf_counter() - t0) * 1000,
        "error": None,
        "success": bool(pr.rows or pr.answer),
        "notes": "WINNER - validator gate + self-correct + doc enrichment",
    }
