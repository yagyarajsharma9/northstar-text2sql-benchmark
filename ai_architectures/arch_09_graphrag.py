"""
Architecture #9 : GraphRAG over schema
========================================
Build a graph where nodes are tables and edges are foreign keys.
Given a question, walk the graph from the most relevant seed table
to assemble the minimum spanning subgraph that covers all referenced
entities. Feed that subgraph (not the whole schema) to the SQL agent.

Strengths : excellent on highly-relational domains (this one).
Weaknesses: graph construction overhead; needs FK metadata.
Complexity: 4/5
"""
from __future__ import annotations
import time
from collections import deque
from . import common as C
from winning_architecture import schema_catalog as SC

NAME = "09_graphrag"

SYSTEM = "You are a SQLite expert. Use only the connected subgraph of tables. Output a single SELECT."


def _bfs(seeds: list[str], max_nodes: int = 10) -> list[str]:
    visited = []
    q = deque(seeds)
    while q and len(visited) < max_nodes:
        t = q.popleft()
        if t in visited or t not in SC.TABLES:
            continue
        visited.append(t)
        for nb in SC.RELATIONS.get(t, []):
            if nb not in visited:
                q.append(nb)
    return visited


def run(question: str) -> dict:
    t0 = time.perf_counter()
    res = C.ArchResult(arch=NAME, question=question)
    seeds = SC.retrieve_tables(question, top_k=2)[:2]
    subgraph = _bfs(seeds, max_nodes=10)
    block = SC.render_schema_block(subgraph)
    text, online = C.llm_or_offline(SYSTEM, f"{block}\n\nQ: {question}\nSQL:")
    sql = C._strip_sql_fences(text) if online else C.offline_sql_for(question)
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
    res.notes = f"subgraph: {subgraph}"
    return res.to_dict()
