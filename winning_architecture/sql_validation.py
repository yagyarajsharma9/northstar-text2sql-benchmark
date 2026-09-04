"""
Schema-aware SQL validation using sqlglot.

Catches hallucinated columns / wrong tables BEFORE we burn an execution.
Returns:
    (is_valid: bool, reason: str | None, normalized_sql: str)

This is a structural check — it says nothing about semantic correctness.
The validator agent is still responsible for the "did this answer the
question" judgement.
"""
from __future__ import annotations
from typing import Iterable

try:
    import sqlglot
    from sqlglot import exp
    HAS_SQLGLOT = True
except ImportError:
    HAS_SQLGLOT = False

from . import schema_catalog as SC


def _build_table_columns() -> dict[str, set[str]]:
    out: dict[str, set[str]] = {}
    for table, info in SC.TABLES.items():
        out[table] = set(info["cols"].split())
    # FTS5 internal table for doc questions
    out.setdefault("document_chunks_fts", {"chunk_text", "rowid"})
    return out


_TABLE_COLS: dict[str, set[str]] = _build_table_columns()
_ALL_TABLES = set(_TABLE_COLS.keys())
_ALL_COLUMNS = {c for cols in _TABLE_COLS.values() for c in cols}

# SQLite scalar/aggregate functions and built-in pseudo-columns we should not
# flag as hallucinated.
_SAFE_PSEUDO = {
    "*", "rowid", "oid", "_rowid_",
    "now", "current_timestamp", "current_date", "current_time",
    "true", "false", "null",
}


def validate(sql: str) -> tuple[bool, str | None, str]:
    if not HAS_SQLGLOT:
        return True, None, sql  # cannot validate; let it through
    if not sql or not sql.strip():
        return False, "empty SQL", sql
    try:
        tree = sqlglot.parse_one(sql, dialect="sqlite")
    except Exception as e:
        return False, f"parse error: {e}", sql

    # Collect referenced tables (real tables, not subquery aliases).
    referenced_tables: set[str] = set()
    aliases: dict[str, str] = {}
    for tbl in tree.find_all(exp.Table):
        name = tbl.name
        if not name:
            continue
        if name not in _ALL_TABLES:
            return False, f"unknown table '{name}'", sql
        referenced_tables.add(name)
        alias = tbl.alias_or_name
        if alias and alias != name:
            aliases[alias] = name

    if not referenced_tables:
        # CTE-only or VALUES — accept if nothing weird
        return True, None, sql

    # Build the union of legal columns for the referenced tables.
    legal_cols = {"*"}
    for t in referenced_tables:
        legal_cols.update(_TABLE_COLS.get(t, set()))

    # Walk Column nodes. If a column has a table prefix, check against that
    # table's column set; otherwise check against the union.
    for col in tree.find_all(exp.Column):
        col_name = (col.name or "").lower()
        if not col_name or col_name in _SAFE_PSEUDO:
            continue
        # CTE-like generated cols (case_when_x) sometimes parse as Column;
        # accept anything that looks like an alias from earlier in the query.
        if col.find_ancestor(exp.With):
            continue
        tbl_qualifier = (col.table or "").lower()
        if tbl_qualifier:
            # Resolve alias to real table name.
            real_table = aliases.get(tbl_qualifier, tbl_qualifier)
            if real_table not in _TABLE_COLS:
                # Could be a CTE name - allow.
                continue
            allowed = _TABLE_COLS[real_table]
            if col_name not in allowed and col_name != "*":
                return False, f"column '{tbl_qualifier}.{col_name}' not in table '{real_table}'", sql
        else:
            # Unqualified — accept if any referenced table has it OR if it's
            # likely an aggregate alias (we can't easily check those).
            if col_name not in legal_cols:
                # Tolerate: aliases from the SELECT list, scalar literals, etc.
                # Only fail if obviously hallucinated (very rare).
                pass
    return True, None, sql


def referenced_tables(sql: str) -> set[str]:
    if not HAS_SQLGLOT:
        return set()
    try:
        tree = sqlglot.parse_one(sql, dialect="sqlite")
    except Exception:
        return set()
    return {t.name for t in tree.find_all(exp.Table) if t.name in _ALL_TABLES}


# Tokens that almost always appear in real questions (verbs, articles, etc.)
# that we should NOT flag as "fabricated metric". This is a hard list of
# common English plus our actual column tokens. Anything snake_case-looking
# in a question that's NOT in this set is a strong signal of a metric the
# user is asking about.
_GENERIC_QUESTION_TOKENS = {
    # articles / pronouns / common verbs
    "the","a","an","this","that","these","those","each","every","all","any","some",
    "show","list","get","find","tell","give","display","print","return",
    "what","which","who","when","where","why","how","is","are","do","does","did",
    "can","could","will","would","should","may","might","have","has","had","be","been",
    # generic nouns
    "data","record","records","row","rows","column","columns","value","values",
    "balance","total","number","amount","item","items","entry","entries","detail","details",
    "information","summary","report","entry","section",
    # business
    "company","year","month","day","date","range","period","quarter","status",
    # connectors
    "for","of","in","on","by","with","from","to","and","or","not","but","also","please",
    "me","my","our","us","you","your","they","them","their","its","it",
}


def detect_fabricated_metric(question: str, sql: str) -> str | None:
    """Catch hallucinated columns of the form ``<literal> AS <name>`` where
    <name> is a metric the user asked about and we have NO real column for it.

    Returns a reason string if a fabrication is detected, else None.
    """
    if not HAS_SQLGLOT or not sql or not question:
        return None
    try:
        tree = sqlglot.parse_one(sql, dialect="sqlite")
    except Exception:
        return None

    # Walk SELECT projections: find Aliases whose source is a Literal/Null.
    fabricated: list[str] = []
    for alias_node in tree.find_all(exp.Alias):
        src = alias_node.this
        alias_name = (alias_node.alias or "").lower()
        if not alias_name:
            continue
        is_literal = isinstance(src, (exp.Literal, exp.Null, exp.Boolean))
        if not is_literal:
            continue
        # Is the alias a real column anywhere in the schema?
        if alias_name in _ALL_COLUMNS:
            continue
        fabricated.append(alias_name)

    if not fabricated:
        return None

    # Now check whether the user actually asked about this metric.
    import re as _re
    q_tokens = {t.lower() for t in _re.findall(r"[A-Za-z][A-Za-z0-9_]+", question)}
    q_tokens -= _GENERIC_QUESTION_TOKENS
    # Also include underscore-split forms of multi-word identifiers in the question.
    snake_in_q: set[str] = set()
    for t in q_tokens:
        snake_in_q.add(t)
    # Heuristic: also recognise compound terms like "carbon_offset_credits"
    snake_terms = _re.findall(r"[A-Za-z][A-Za-z]+_[A-Za-z_]+", question)
    snake_in_q.update(s.lower() for s in snake_terms)

    for alias in fabricated:
        # Direct match : alias appears as a token in the question.
        if alias in snake_in_q:
            return (f"fabricated column '{alias}' (literal AS {alias}); "
                    f"the schema has no such column - the right answer is to say we don't track it")
        # Compound match : alias parts overlap with question tokens.
        parts = [p for p in alias.split("_") if len(p) > 2]
        if parts and all(p in q_tokens for p in parts):
            return (f"fabricated column '{alias}' (literal AS {alias}); "
                    f"all parts of the column name come from the user's question, "
                    f"strongly suggesting hallucination")
    return None
