"""Read-only DB access + safe SQL execution sandbox."""
from __future__ import annotations
import re
import sqlite3
from pathlib import Path
from typing import Any

DB_PATH = Path(__file__).parent.parent / "database" / "oilgas.db"

# SQL guardrails: only allow SELECT / WITH / EXPLAIN. No DDL/DML.
FORBIDDEN_TOKENS = re.compile(
    r"\b(insert|update|delete|drop|alter|create|attach|detach|pragma|replace|truncate|vacuum)\b",
    re.IGNORECASE,
)
ALLOWED_PREFIX = re.compile(r"^\s*(select|with|explain)\b", re.IGNORECASE)


class UnsafeSQLError(Exception):
    pass


def get_conn() -> sqlite3.Connection:
    if not DB_PATH.exists():
        raise FileNotFoundError(f"Database missing: {DB_PATH}. Run database/seed_data.py first.")
    conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def is_safe_sql(sql: str) -> tuple[bool, str | None]:
    s = sql.strip().rstrip(";")
    if not ALLOWED_PREFIX.match(s):
        return False, "Only SELECT / WITH / EXPLAIN queries are allowed."
    if FORBIDDEN_TOKENS.search(s):
        return False, "Query contains a forbidden keyword (no DDL/DML allowed)."
    if ";" in s:
        return False, "Multiple statements are not allowed."
    return True, None


def execute_sql(sql: str, max_rows: int = 200) -> dict[str, Any]:
    ok, why = is_safe_sql(sql)
    if not ok:
        raise UnsafeSQLError(why or "rejected")
    conn = get_conn()
    try:
        cur = conn.execute(sql)
        cols = [d[0] for d in (cur.description or [])]
        rows = cur.fetchmany(max_rows + 1)
        truncated = len(rows) > max_rows
        rows = rows[:max_rows]
        return {
            "columns": cols,
            "rows": [list(r) for r in rows],
            "row_count": len(rows),
            "truncated": truncated,
        }
    finally:
        conn.close()


# Aggressive English stopword list - words that have no retrieval value.
_FTS_STOP = {
    "a","an","and","are","as","at","be","by","do","does","for","from","get",
    "give","got","had","has","have","how","if","in","into","is","it","its",
    "list","many","me","much","no","not","of","on","or","over","please",
    "show","so","some","tell","than","that","the","their","them","then","there",
    "these","they","this","those","to","total","under","up","us","was","were",
    "what","when","where","which","who","why","will","with","yes","you","your",
    "according","any","also","each","all","just","like","only","such","most",
    "between","both","does","did","done","find","item","items","entry","entries",
}


def _build_fts_query(question: str) -> str:
    """Turn a natural-language question into a FTS5 OR query of stemmable tokens."""
    raw = re.findall(r"[A-Za-z][A-Za-z0-9_-]*", question)
    toks = []
    for w in raw:
        wl = w.lower()
        if wl in _FTS_STOP or len(wl) < 3:
            continue
        # FTS5 dislikes some chars; quote the token to be safe
        toks.append(f'"{wl}"')
    if not toks:
        return ""
    return " OR ".join(toks)


def fts_search(query: str, top_k: int = 6) -> list[dict[str, Any]]:
    """BM25-ranked keyword search over indexed document chunks."""
    fts_q = _build_fts_query(query)
    if not fts_q:
        return []
    conn = get_conn()
    try:
        sql = """
        SELECT c.chunk_id, c.chunk_text, c.chunk_index, e.file_name, e.document_category,
               e.summary, bm25(document_chunks_fts) AS score
        FROM document_chunks_fts f
        JOIN document_chunks c ON c.chunk_id = f.rowid
        JOIN document_extracts e ON e.extract_id = c.extract_id
        WHERE document_chunks_fts MATCH ?
        ORDER BY score
        LIMIT ?
        """
        return [dict(r) for r in conn.execute(sql, (fts_q, top_k)).fetchall()]
    except sqlite3.OperationalError:
        # FTS5 syntax error  -  degrade to LIKE on the strongest 4 tokens
        toks = [t.strip('"') for t in fts_q.split(" OR ")][:4]
        if not toks:
            return []
        like_clauses = " OR ".join(["lower(c.chunk_text) LIKE ?"] * len(toks))
        # Score = number of matching tokens (rough relevance)
        score_expr = " + ".join(
            [f"(CASE WHEN lower(c.chunk_text) LIKE ? THEN 1 ELSE 0 END)"] * len(toks))
        params = [f"%{w}%" for w in toks] * 2 + [top_k]
        sql = f"""
        SELECT c.chunk_id, c.chunk_text, c.chunk_index, e.file_name, e.document_category,
               e.summary, ({score_expr}) AS score
        FROM document_chunks c
        JOIN document_extracts e ON e.extract_id = c.extract_id
        WHERE {like_clauses}
        ORDER BY score DESC
        LIMIT ?
        """
        return [dict(r) for r in conn.execute(sql, params).fetchall()]
    finally:
        conn.close()
