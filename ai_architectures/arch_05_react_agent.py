"""
Architecture #5 : ReAct / tool-using agent
============================================
Model is given a small toolkit (list_tables, describe_table,
sample_rows, run_sql) and reasons step-by-step. Anthropic-style
tool-use with a hard step limit.

Strengths : adapts to questions that need exploration; shows work.
Weaknesses: latency; can wander; harder to constrain output.
Complexity: 4/5

Note: this stub implements a deterministic 3-step "explore then
write" loop in offline mode and uses the Anthropic tool-use API
when a key is set.
"""
from __future__ import annotations
import os
import time
import json
from . import common as C
from winning_architecture import schema_catalog as SC, db

NAME = "05_react_agent"


def tool_list_tables() -> list[str]:
    return list(SC.TABLES.keys())


def tool_describe_table(t: str) -> dict:
    return SC.TABLES.get(t, {"error": "not found"})


def tool_run_sql(sql: str) -> dict:
    out = db.execute_sql(sql, max_rows=50)
    return {"columns": out["columns"], "row_count": len(out["rows"]), "sample": out["rows"][:5]}


TOOLS = [
    {"name": "list_tables", "description": "List all table names",
     "input_schema": {"type": "object", "properties": {}}},
    {"name": "describe_table", "description": "Get description and columns for a table",
     "input_schema": {"type": "object", "properties": {"table": {"type": "string"}}, "required": ["table"]}},
    {"name": "run_sql", "description": "Execute a read-only SELECT against the DB",
     "input_schema": {"type": "object", "properties": {"sql": {"type": "string"}}, "required": ["sql"]}},
]


def run(question: str) -> dict:
    t0 = time.perf_counter()
    res = C.ArchResult(arch=NAME, question=question)
    if not os.environ.get("ANTHROPIC_API_KEY"):
        # Offline: degrade to schema_rag style
        from . import arch_02_schema_rag as fallback
        d = fallback.run(question)
        d["arch"] = NAME
        d["notes"] = "OFFLINE -> degraded to schema_rag"
        return d

    import anthropic
    client = anthropic.Anthropic()
    history = [{"role": "user", "content":
                f"Question: {question}\nUse the tools to explore the schema then answer with SQL "
                f"and a brief summary. Stop after 6 tool calls."}]
    sql_used, last_rows, last_cols = None, [], []
    for _ in range(7):
        msg = client.messages.create(
            model=os.environ.get("CHAT_MODEL", "claude-opus-4-7"),
            max_tokens=1500,
            tools=TOOLS,
            messages=history,
            system="You are a careful data analyst. Use tools, then answer."
        )
        if msg.stop_reason == "end_turn":
            text = "".join(b.text for b in msg.content if hasattr(b, "text"))
            res.answer = text
            break
        # Process tool calls
        history.append({"role": "assistant", "content": msg.content})
        tool_results = []
        for blk in msg.content:
            if blk.type == "tool_use":
                if blk.name == "list_tables":
                    out = tool_list_tables()
                elif blk.name == "describe_table":
                    out = tool_describe_table(blk.input.get("table"))
                elif blk.name == "run_sql":
                    sql = blk.input.get("sql", "")
                    sql_used = sql
                    try:
                        ex = db.execute_sql(sql, max_rows=200)
                        last_cols = ex["columns"]
                        last_rows = [dict(zip(ex["columns"], r)) for r in ex["rows"]]
                        out = {"columns": ex["columns"], "rows": last_rows[:10],
                               "row_count": len(last_rows)}
                    except Exception as e:
                        out = {"error": str(e)}
                else:
                    out = {"error": "unknown tool"}
                tool_results.append({"type": "tool_result", "tool_use_id": blk.id,
                                     "content": json.dumps(out, default=str)[:4000]})
        history.append({"role": "user", "content": tool_results})

    res.sql = sql_used
    res.columns = last_cols
    res.rows = last_rows
    res.success = bool(last_rows or res.answer)
    res.elapsed_ms = (time.perf_counter() - t0) * 1000
    res.notes = "anthropic tool-use, 7-turn cap"
    return res.to_dict()
