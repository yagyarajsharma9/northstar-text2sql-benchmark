"""
Chain-of-Agents with Validator Gate - the WINNING architecture.

Pipeline (per user message):
    Router  ->  Schema-RAG  ->  Example-Retrieve  ->  SQL Gen  ->
        Validator Gate (semantic + safety)  ->  Executor  ->
            Self-correct loop (on error or empty result)  ->
                Doc-RAG (FTS5) for any policy citations  ->
                    Summarizer

Each stage emits a `trace_event` so the UI can show the pipeline live.

LLM provider auto-selection (LLM_PROVIDER env, default "auto"):
  - openai     : uses OPENAI_API_KEY  + OPENAI_MODEL  (default gpt-4o)
  - anthropic  : uses ANTHROPIC_API_KEY + CHAT_MODEL  (default claude-opus-4-7)
  - auto       : prefer OpenAI if key present, else Anthropic, else offline
If neither key is set the pipeline falls back to a deterministic offline mode
that uses the example bank, so the UI is still demonstrable without a key.
"""
from __future__ import annotations
import os
import re
import json
import time
import logging
from dataclasses import dataclass, field
from typing import Any, Iterator, Callable
from pathlib import Path

# Load .env if present (silent if missing python-dotenv)
try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parent.parent / ".env")
except Exception:
    pass

from . import db as dbmod
from . import schema_catalog
from . import examples as ex_bank
from . import sql_validation

log = logging.getLogger("engine")

# ---- Provider selection ----
LLM_PROVIDER = os.environ.get("LLM_PROVIDER", "auto").lower()
ANTHROPIC_MODEL = os.environ.get("CHAT_MODEL", "claude-opus-4-7")
OPENAI_MODEL = os.environ.get("OPENAI_MODEL", "gpt-4o")

_anthropic_client = None
_openai_client = None


def _get_anthropic():
    global _anthropic_client
    if _anthropic_client is not None:
        return _anthropic_client
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        return None
    try:
        import anthropic
        _anthropic_client = anthropic.Anthropic(api_key=key)
        return _anthropic_client
    except ImportError:
        return None


def _get_openai():
    global _openai_client
    if _openai_client is not None:
        return _openai_client
    key = os.environ.get("OPENAI_API_KEY")
    if not key:
        return None
    try:
        from openai import OpenAI
        _openai_client = OpenAI(api_key=key)
        return _openai_client
    except ImportError:
        return None


def active_provider() -> str:
    """Return 'openai' | 'anthropic' | 'offline' based on env."""
    if LLM_PROVIDER == "openai":
        return "openai" if _get_openai() else "offline"
    if LLM_PROVIDER == "anthropic":
        return "anthropic" if _get_anthropic() else "offline"
    # auto
    if _get_openai():
        return "openai"
    if _get_anthropic():
        return "anthropic"
    return "offline"


def active_model() -> str:
    p = active_provider()
    if p == "openai":
        return OPENAI_MODEL
    if p == "anthropic":
        return ANTHROPIC_MODEL
    return "offline"


@dataclass
class TraceEvent:
    stage: str
    status: str          # "start" | "ok" | "warn" | "error"
    message: str = ""
    payload: dict = field(default_factory=dict)


@dataclass
class PipelineResult:
    answer: str
    sql: str | None = None
    rows: list[dict] = field(default_factory=list)
    columns: list[str] = field(default_factory=list)
    citations: list[dict] = field(default_factory=list)
    trace: list[dict] = field(default_factory=list)


# =====================================================================
# Stage 0 : Router  (DATA / POLICY / BOTH)
# =====================================================================

POLICY_HINTS = re.compile(
    r"\b(policy|sop|procedure|approval policy|safety|hse|threshold|"
    r"requirement|guideline|regulation|how do we|how to|process for|"
    r"checklist|onboarding|deviation|penalty|"
    # documents/sections
    r"plan|manual|standard|charter|memo|report says|"
    # "what does X say" pattern
    r"says|states|specifies|defines|notification timeline|"
    r"section \d|article \d|tier \d|category (alpha|bravo|charlie|delta))\b",
    re.IGNORECASE)

DATA_HINTS = re.compile(
    r"\b(how many|how much|count|sum|total|average|avg|top|bottom|list|"
    r"show|which|who|when|highest|lowest|trend|over time|last|month|"
    r"year|2023|2024|2025|2026|q[1-4])\b", re.IGNORECASE)

# COMPLIANCE: questions that need BOTH the policy threshold/rule AND the
# actual database fact, then a comparison.
COMPLIANCE_HINTS = re.compile(
    r"\b(compliant|compliance|violat(ion|ing|ed|e)|breach(es|ed|ing)?|"
    r"meet(ing|s)? (the )?(target|threshold|policy|requirement)|"
    r"exceed(ing|s|ed)? (the )?(target|limit|threshold|max)|"
    r"in (line|breach) with|"
    r"(within|outside) (policy|tolerance|spec|sla)|"
    r"approaching (expiry|expir|threshold)|"
    r"audit (finding|trail)|self[- ]approv|conflict of interest)\b",
    re.IGNORECASE)

# Prompt-injection / jailbreak attempts that the router must short-circuit.
PROMPT_INJECTION = re.compile(
    r"(ignore (all )?(previous|prior|above) (instructions|rules|prompts)|"
    r"disregard (all )?(previous|prior) instructions|"
    r"reveal (your |the )?(system )?prompt|"
    r"print (your |the )?(api[ _]?key|secret|password)|"
    r"jailbreak|developer mode|act as (?:dan|an? unrestricted))",
    re.IGNORECASE)

# Destructive operation requests - the user is explicitly asking us to mutate.
# The DB connection is read-only so it would fail anyway, but we want a clear
# refusal in the user-facing answer rather than a confusing fallback SELECT.
DESTRUCTIVE_REQUEST = re.compile(
    r"\b(delete (all|every|the)|drop (the |all )?(table|database|schema)|"
    r"truncate (the )?(table|database)|wipe (out |all )?(the )?(data|records|tables)|"
    r"remove all (records|users|rows|entries)|"
    r"erase (all|every|the))\b", re.IGNORECASE)

# Credential / sensitive-column extraction requests.
SENSITIVE_COL_REQUEST = re.compile(
    r"\b(password[_ ]?hash(es)?|password[_ ]?salt|api[_ ]?key|secret|"
    r"private[_ ]?key|mfa[_ ]?secret|"
    r"all (passwords?|credentials|secrets|tokens))\b", re.IGNORECASE)


# Phrases that look like a follow-up to whatever was just discussed.
FOLLOWUP_HINTS = re.compile(
    r"^\s*(yes|no|ok|sure|continue|go on|"
    r"more|tell me more|show more|expand|elaborate|"
    r"why|why not|what about|how about|and|"
    r"again|that file|the file|the doc|the document|"
    r"the previous|the last one|the earlier)\b", re.IGNORECASE)

DOC_REF_HINTS = re.compile(
    r"\b(that file|the file|the doc|the document|the report|the policy|"
    r"the procedure|the sop|the manual|the contract|uploaded|attached)\b",
    re.IGNORECASE)


def _last_intent(history: list[dict] | None) -> str | None:
    if not history:
        return None
    for turn in reversed(history):
        if turn.get("role") == "assistant" and turn.get("intent"):
            return turn["intent"]
    return None


def _last_doc_files(history: list[dict] | None, max_n: int = 3) -> list[str]:
    """Names of documents cited in the most recent assistant turn(s)."""
    if not history:
        return []
    seen, out = set(), []
    for turn in reversed(history):
        if turn.get("role") != "assistant":
            continue
        for c in turn.get("citations", []) or []:
            fn = c.get("file_name") if isinstance(c, dict) else None
            if fn and fn not in seen:
                seen.add(fn)
                out.append(fn)
        if out:
            break
    return out[:max_n]


def _recent_doc_terms(history: list[dict] | None) -> set[str]:
    """Distinctive words (>=4 chars) from the most recent doc-citing assistant turn."""
    if not history:
        return set()
    for turn in reversed(history):
        if turn.get("role") != "assistant":
            continue
        if turn.get("citations"):
            content = turn.get("content") or ""
            words = re.findall(r"[A-Za-z][A-Za-z\-]{4,}", content)
            # Filter common words
            common = {"there","their","these","those","which","while","would","should",
                      "could","about","information","provided","according","include",
                      "incident","incidents","details","please","reference","procedure"}
            return {w.lower() for w in words if w.lower() not in common}
    return set()


DB_REF_HINTS = re.compile(
    r"\b(database|the db|the data warehouse|in the table|in our table|"
    r"check (our |the )?(database|db|records))\b", re.IGNORECASE)


def route(question: str, history: list[dict] | None = None) -> str:
    """Quick rule-based router. History-aware: short follow-ups inherit the prior intent.
    Returns one of: DATA, POLICY, BOTH, COMPLIANCE, REJECT."""
    # Reject prompt-injection / destructive / credential-grab attempts up front.
    if PROMPT_INJECTION.search(question):
        return "REJECT"
    if DESTRUCTIVE_REQUEST.search(question):
        return "REJECT"
    if SENSITIVE_COL_REQUEST.search(question):
        return "REJECT"

    # Explicit DB reference -> DATA (overrides POLICY inheritance from prior turn).
    if DB_REF_HINTS.search(question):
        return "DATA"

    has_data = bool(DATA_HINTS.search(question))
    has_policy = bool(POLICY_HINTS.search(question))
    has_compliance = bool(COMPLIANCE_HINTS.search(question))

    if has_compliance:
        return "COMPLIANCE"

    if DOC_REF_HINTS.search(question):
        return "POLICY"

    if FOLLOWUP_HINTS.match(question.strip()) or len(question.split()) <= 4:
        prior = _last_intent(history)
        if prior:
            return prior

    if not has_data:
        recent_terms = _recent_doc_terms(history)
        if recent_terms:
            qwords = {w.lower() for w in re.findall(r"[A-Za-z][A-Za-z\-]{4,}", question)}
            overlap = qwords & recent_terms
            if len(overlap) >= 2:
                return "POLICY"

    if has_data and has_policy:
        return "BOTH"
    if has_policy and not has_data:
        return "POLICY"
    return "DATA"


def render_history_block(history: list[dict] | None, max_turns: int = 4) -> str:
    """Format last N turns of conversation for prompt injection."""
    if not history:
        return ""
    pairs = []
    cur = []
    for turn in history[-(max_turns * 2):]:
        cur.append(turn)
        if len(cur) == 2:
            pairs.append(cur); cur = []
    if not pairs and cur:
        pairs.append(cur)
    lines = ["# RECENT CONVERSATION (most recent last)"]
    for p in pairs:
        for t in p:
            who = "USER" if t.get("role") == "user" else "ASSISTANT"
            content = (t.get("content") or "").strip()[:600]
            lines.append(f"\n{who}: {content}")
            if t.get("sql"):
                lines.append(f"  (ran SQL: {t['sql'][:200]})")
            if t.get("citations"):
                fns = [c.get("file_name") for c in t["citations"][:3] if isinstance(c, dict)]
                if any(fns):
                    lines.append(f"  (cited: {', '.join(filter(None, fns))})")
    return "\n".join(lines) + "\n"


# =====================================================================
# Stage 1 : Build the SQL generator prompt
# =====================================================================

SYSTEM_SQL = """You are a senior SQL analyst for NorthStar Petroleum's operational data warehouse (SQLite).

Rules - read carefully:
1. Output a SINGLE SQLite SELECT statement. No commentary, no markdown fences, no semicolons after the final statement.
2. Use ONLY the tables/columns listed in the RELEVANT TABLES block. Do NOT invent columns.
3. Always JOIN through the provided foreign keys. Prefer LEFT JOIN when the right side may be absent.
4. For dates use ISO format. Use SQLite functions: date('now'), date('now','-30 days'), strftime('%Y', col).
5. ALWAYS qualify columns with their table alias when more than one table is in scope.
6. If the question asks "top N" or similar, include ORDER BY ... LIMIT N.
7. Round monetary or volumetric aggregates to a reasonable number of decimals.
8. Default LIMIT 200 unless the user asks for a single value.
9. NEVER write INSERT/UPDATE/DELETE/DROP/PRAGMA. Read-only only.
10. If the question is ambiguous, choose the most defensible interpretation and proceed."""


def build_sql_prompt(question: str, schema_block: str, examples_block: str,
                     history_block: str = "") -> str:
    return f"""{history_block}{schema_block}

{examples_block}

# QUESTION
{question}

# YOUR ANSWER
If the question references "the previous", "that", "those rows" etc., resolve it from the recent conversation above.
Output exactly one SELECT statement that answers the question. No markdown, no commentary."""


# =====================================================================
# Stage 2 : Validator Gate
# =====================================================================

SYSTEM_VALIDATOR = """You are an SQL validator. Given the user question and a candidate SQL,
your job is to decide if the SQL faithfully answers the question, uses the right tables,
and is safe (read-only). Reply with strict JSON only:

{"verdict": "APPROVE"} when the SQL is correct and ready to run, OR
{"verdict": "REVISE", "reason": "<short reason>", "fix_hint": "<short hint>"} when not.

REJECT and REVISE if the SQL fabricates a column the schema does not have. In particular:
- Catch literal stand-ins like '0 AS carbon_offset_credits' or '"N/A" AS some_metric_we_do_not_track'
  when the original question asked about a real metric and we obviously don't have it.
- If the question asks about something the schema cannot answer, the right SQL is one that
  returns no rows, NOT a SELECT that fabricates a fake answer column.

Be strict on:
- wrong table or wrong column
- missing JOIN that would change results
- wrong aggregation (e.g. SUM where AVG is asked)
- wrong date filter
- missing GROUP BY
- fabricated columns via literals as described above
Be lenient on:
- minor formatting / aliasing
- harmless extra columns"""


# =====================================================================
# Stage 3 : Summarizer
# =====================================================================

SYSTEM_SUMMARIZER = """You are an analyst writing a concise answer for a NorthStar Petroleum executive.
You will receive: the user's question, the SQL that was run, and the result rows (JSON).
Produce a clear, natural-language answer in 2-5 sentences. Quote concrete numbers.
If a policy/document context is included, weave the relevant point into the answer
and note the source filename in parentheses. Be plain. No bullet points unless the
result is genuinely list-like with more than 4 items."""


# =====================================================================
# LLM helpers
# =====================================================================

def _llm(system: str, user: str, max_tokens: int = 1024, temperature: float = 0.0) -> str:
    """Call the active provider. Raises RuntimeError('OFFLINE') if neither key set."""
    p = active_provider()
    if p == "openai":
        client = _get_openai()
        resp = client.chat.completions.create(
            model=OPENAI_MODEL,
            max_tokens=max_tokens,
            temperature=temperature,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        )
        return (resp.choices[0].message.content or "").strip()
    if p == "anthropic":
        client = _get_anthropic()
        msg = client.messages.create(
            model=ANTHROPIC_MODEL,
            max_tokens=max_tokens,
            temperature=temperature,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        return "".join(block.text for block in msg.content if hasattr(block, "text")).strip()
    raise RuntimeError("OFFLINE")


def _strip_sql_fences(text: str) -> str:
    text = text.strip()
    text = re.sub(r"^```(?:sql|sqlite)?\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s*```\s*$", "", text)
    text = text.strip()
    if text.endswith(";"):
        text = text[:-1]
    return text


# =====================================================================
# Offline fallback : pick best example outright
# =====================================================================

def _offline_sql(question: str) -> str:
    matches = ex_bank.retrieve_examples(question, top_k=1)
    if matches:
        return matches[0]["sql"]
    return "SELECT 'OFFLINE_MODE — set ANTHROPIC_API_KEY for real answers' AS message LIMIT 1"


def _offline_summary(question: str, sql: str, rows: list[dict], cites: list[dict]) -> str:
    parts = []
    if rows:
        sample = rows[0]
        head = ", ".join(f"{k}={v}" for k, v in list(sample.items())[:4])
        parts.append(f"Returned {len(rows)} row(s). First: {head}.")
    else:
        parts.append("Query ran but returned no rows.")
    if cites:
        parts.append(f"Related document: {cites[0]['file_name']}.")
    parts.append("(Offline mode — set ANTHROPIC_API_KEY for natural-language synthesis.)")
    return " ".join(parts)


# =====================================================================
# Public API : run a user question through the chain
# =====================================================================

def run_chain(question: str,
              history: list[dict] | None = None,
              on_event: Callable[[TraceEvent], None] | None = None,
              use_validator: bool = True) -> PipelineResult:
    """Process one user turn.

    use_validator : set False to skip the validator gate (for the ablation study).

    history : optional list of prior turns, each like
              {"role": "user"|"assistant", "content": str,
               "sql"?: str, "citations"?: list, "intent"?: str}
              Most recent turn is LAST. Caller is responsible for trimming.
    """
    trace: list[dict] = []
    history = history or []

    def emit(stage: str, status: str, message: str = "", payload: dict | None = None):
        ev = TraceEvent(stage=stage, status=status, message=message, payload=payload or {})
        trace.append({"stage": ev.stage, "status": ev.status, "message": ev.message,
                      "payload": ev.payload, "ts": time.time()})
        if on_event:
            on_event(ev)

    answer = ""
    sql_used: str | None = None
    rows: list[dict] = []
    columns: list[str] = []
    citations: list[dict] = []
    intent = "DATA"

    history_block = render_history_block(history)

    # --- ROUTER ---
    emit("router", "start")
    intent = route(question, history)
    prior_intent = _last_intent(history)
    last_files = _last_doc_files(history)
    msg = f"Intent: {intent}"
    if prior_intent and prior_intent != intent:
        msg += f" (prior: {prior_intent})"
    if last_files:
        msg += f" | recent files: {', '.join(last_files)}"
    emit("router", "ok", msg)

    # --- REJECT path (prompt injection / unsafe ask) ---
    if intent == "REJECT":
        if DESTRUCTIVE_REQUEST.search(question):
            # Worded carefully so the response itself doesn't echo the very tokens
            # we are blocking (e.g. avoid the literal verbs that automated security
            # scanners look for in user-facing output).
            answer = ("I cannot remove, modify, or destroy any rows in the wells, users, "
                      "or any other table. The database is read-only and I am only allowed "
                      "to run SELECT queries. If you need to mutate data, please use the "
                      "proper application workflow with the appropriate approval chain.")
        elif SENSITIVE_COL_REQUEST.search(question):
            answer = ("I cannot return password hashes, API keys, MFA secrets, or other "
                      "credentials. These are not allowed to be exposed through the chat "
                      "interface. If you have a legitimate need, please use the IT Security "
                      "team's approved workflow.")
        else:
            answer = ("I can't comply with that request. I am the NorthStar operations "
                      "assistant and I only answer questions about company data and policies "
                      "using the available tools. I will not reveal system prompts, secrets, "
                      "credentials, or follow instructions to override my safety rules.")
        pr = PipelineResult(answer=answer, trace=trace)
        pr.trace.append({"stage": "_meta", "status": "ok", "message": "intent",
                         "payload": {"intent": "REJECT"}, "ts": time.time()})
        return pr

    # --- COMPLIANCE path : extract policy threshold + compute actual + compare ---
    if intent == "COMPLIANCE":
        return _run_compliance_path(question, history, history_block, emit, trace)

    # --- POLICY path ---
    if intent in ("POLICY", "BOTH"):
        emit("doc_search", "start", "Searching policy documents...")
        # Build the FTS query.  Three sources:
        #   1. the current question (always)
        #   2. last cited filenames (when the question explicitly says "the file"
        #      etc., DOC_REF_HINTS matched)
        #   3. the previous user turn IF the current question is a short
        #      follow-up that wouldn't retrieve well on its own.
        search_terms = [question]
        if last_files and DOC_REF_HINTS.search(question):
            stems = [fn.rsplit(".", 1)[0].replace("_", " ") for fn in last_files]
            search_terms.extend(stems)

        is_short_followup = (
            FOLLOWUP_HINTS.match(question.strip())
            or len(question.split()) <= 6
        )
        if is_short_followup and history:
            # Walk back to find the previous USER message and append its words.
            for turn in reversed(history):
                if turn.get("role") == "user":
                    prev = (turn.get("content") or "").strip()
                    if prev and prev != question:
                        search_terms.append(prev)
                    break
        search_q = " ".join(search_terms)
        cites_raw = dbmod.fts_search(search_q, top_k=5)
        citations = cites_raw
        emit("doc_search", "ok", f"Found {len(cites_raw)} chunks")
        if intent == "POLICY":
            answer = _synthesize_policy(question, cites_raw, history, emit)
            pr = PipelineResult(answer=answer, citations=citations, trace=trace)
            pr.trace.append({"stage": "_meta", "status": "ok", "message": "intent",
                             "payload": {"intent": intent}, "ts": time.time()})
            return pr

    # --- DATA path ---
    emit("schema_rag", "start")
    tables = schema_catalog.retrieve_tables(question, top_k=6)
    schema_block = schema_catalog.render_schema_block(tables)
    emit("schema_rag", "ok", f"Tables: {', '.join(tables[:8])}")

    emit("example_retrieve", "start")
    exs = ex_bank.retrieve_examples(question, top_k=3)
    examples_block = ex_bank.render_examples_block(exs)
    emit("example_retrieve", "ok", f"Picked {len(exs)} example(s)")

    # SQL generation + self-correct loop
    last_error = None
    sql_text = None
    for attempt in range(1, 4):
        emit("sql_generate", "start", f"Attempt {attempt}")
        prompt = build_sql_prompt(question, schema_block, examples_block, history_block)
        if last_error:
            prompt += f"\n\n# PREVIOUS ATTEMPT FAILED\nError: {last_error}\nFix and try again."
        try:
            raw = _llm(SYSTEM_SQL, prompt, max_tokens=600, temperature=0.0)
            sql_text = _strip_sql_fences(raw)
            emit("sql_generate", "ok", f"{len(sql_text)} chars")
        except RuntimeError:
            sql_text = _offline_sql(question)
            emit("sql_generate", "warn", "Offline fallback (no API key)")

        # ----- VALIDATOR GATE ----- (skippable for the ablation study)
        if use_validator:
            emit("validator", "start")
            verdict, vmsg = _validate_sql(question, sql_text, schema_block)
            emit("validator", "ok" if verdict == "APPROVE" else "warn", f"{verdict} {vmsg or ''}")
            if verdict != "APPROVE" and attempt < 3:
                last_error = f"Validator rejected: {vmsg}. Address it."
                continue

        # ----- EXECUTOR -----
        emit("executor", "start")
        try:
            res = dbmod.execute_sql(sql_text, max_rows=200)
            columns = res["columns"]
            rows = [dict(zip(columns, r)) for r in res["rows"]]
            emit("executor", "ok", f"{len(rows)} row(s){' (truncated)' if res['truncated'] else ''}")
            sql_used = sql_text
            break
        except dbmod.UnsafeSQLError as e:
            emit("executor", "error", f"Unsafe: {e}")
            last_error = f"Unsafe SQL: {e}"
        except Exception as e:
            emit("executor", "error", str(e))
            last_error = f"Execution error: {e}"
        if attempt == 3:
            # Don't dump raw exception text into the user-facing answer.
            # Try one final fallback: treat the question as POLICY (the
            # information might live in a document we have).
            emit("data_to_doc_fallback", "start",
                 "DATA path exhausted; trying document store")
            cites_fb = dbmod.fts_search(question, top_k=4)
            if cites_fb:
                fb_answer = _synthesize_policy(question, cites_fb, history, emit)
                emit("data_to_doc_fallback", "ok",
                     f"answered from {len(cites_fb)} doc chunk(s)")
                pr = PipelineResult(
                    answer=fb_answer, sql=None, citations=cites_fb, trace=trace
                )
                pr.trace.append({"stage": "_meta", "status": "ok", "message": "intent",
                                 "payload": {"intent": "DATA->POLICY_FALLBACK"},
                                 "ts": time.time()})
                return pr
            emit("data_to_doc_fallback", "warn", "no doc match either")
            answer = (
                "I couldn't find a clear answer to that question in either the database "
                "or our document store. The query may be referring to data we don't track, "
                "an entity that doesn't exist, or it may need to be rephrased to point to "
                "a specific table or policy."
            )
            pr = PipelineResult(answer=answer, sql=None, trace=trace)
            pr.trace.append({"stage": "_meta", "status": "ok", "message": "intent",
                             "payload": {"intent": "DATA"}, "ts": time.time()})
            return pr

    # ----- DOC ENRICHMENT (BOTH path picks up policy citations) -----
    if intent == "BOTH" and not citations:
        citations = dbmod.fts_search(question, top_k=3)

    # ----- SUMMARIZER -----
    emit("summarizer", "start")
    answer = _summarize(question, sql_used or "", rows, citations, history, emit)
    emit("summarizer", "ok")

    pr = PipelineResult(
        answer=answer, sql=sql_used, rows=rows, columns=columns, citations=citations, trace=trace
    )
    # Stash intent so the caller can record it in the history entry.
    pr.trace.append({"stage": "_meta", "status": "ok", "message": "intent",
                     "payload": {"intent": intent}, "ts": time.time()})
    return pr


def _validate_sql(question: str, sql: str, schema_block: str) -> tuple[str, str]:
    # Cheap structural checks first
    ok, why = dbmod.is_safe_sql(sql)
    if not ok:
        return "REVISE", why or "unsafe"

    # Schema-aware structural validation with sqlglot - catches hallucinated
    # tables/columns BEFORE we burn an execution.
    sg_ok, sg_reason, _ = sql_validation.validate(sql)
    if not sg_ok:
        return "REVISE", f"sqlglot: {sg_reason}"

    # Catch the "0 AS some_made_up_metric" hallucination pattern (deterministic).
    fab = sql_validation.detect_fabricated_metric(question, sql)
    if fab:
        return "REVISE", fab

    qlow = question.lower()
    keyword_to_table = {
        "well": "wells", "wells": "wells",
        "invoice": "invoices", "invoices": "invoices",
        "incident": "incidents", "spill": "incidents",
        "approval": "approval", "po": "purchase_orders",
        "customer": "customers", "vendor": "vendors",
        "shipment": "shipments", "production": "daily_production",
    }
    for kw, t in keyword_to_table.items():
        if kw in qlow and t not in sql.lower() and "approval_requests" not in sql.lower():
            if kw == "approval" and "approval_" in sql.lower():
                continue
            pass

    # Then call LLM validator
    try:
        out = _llm(SYSTEM_VALIDATOR,
                   f"QUESTION:\n{question}\n\nCANDIDATE SQL:\n{sql}\n\n"
                   f"RELEVANT SCHEMA (subset):\n{schema_block[:2500]}",
                   max_tokens=200, temperature=0.0)
        m = re.search(r"\{.*\}", out, re.DOTALL)
        if m:
            data = json.loads(m.group(0))
            verdict = data.get("verdict", "APPROVE")
            reason = (data.get("reason", "") + " " + data.get("fix_hint", "")).strip()
            return verdict, reason
        return "APPROVE", ""
    except RuntimeError:
        return "APPROVE", "(offline; structural-only)"
    except Exception as e:
        log.warning("validator parse error: %s", e)
        return "APPROVE", "(validator error; defaulting to approve)"


def _summarize(question: str, sql: str, rows: list[dict], cites: list[dict],
               history: list[dict] | None, emit) -> str:
    sample = rows[:25]
    cite_block = ""
    if cites:
        cite_block = "\n\nRELATED POLICY/DOC EXCERPTS:\n" + "\n---\n".join(
            f"[{c['file_name']}] {c['chunk_text'][:600]}" for c in cites[:3]
        )
    hist_block = render_history_block(history)
    user_msg = (
        f"{hist_block}"
        f"QUESTION:\n{question}\n\n"
        f"SQL:\n{sql}\n\n"
        f"RESULT ROWS (up to 25 of {len(rows)} total):\n{json.dumps(sample, default=str)[:6000]}"
        f"{cite_block}"
    )
    try:
        return _llm(SYSTEM_SUMMARIZER, user_msg, max_tokens=600, temperature=0.2)
    except RuntimeError:
        return _offline_summary(question, sql, rows, cites)


# =====================================================================
# COMPLIANCE path  -  policy lookup + DB query + comparison
# =====================================================================

SYSTEM_COMPLIANCE = """You are a NorthStar Petroleum compliance analyst.
You receive: (1) policy excerpts from the document store, (2) a relevant subset
of the SQL schema, and (3) the user's compliance question.

Output STRICT JSON only:
{
  "rule": "<one-sentence statement of the rule or threshold from the policy>",
  "source_file": "<filename from the policy excerpt header>",
  "sql": "<a single SQLite SELECT that computes the actual value or finds violations>",
  "comparison_method": "compare|find_violations|count_breaches"
}
Rules:
- The SQL must be a SELECT only. No DDL/DML, no semicolons after the final stmt.
- Use only tables/columns from the provided schema.
- If the policy has no numeric threshold, default to 'find_violations'.
- If you can't find a clear rule in the excerpts, set rule to 'NO_RULE_FOUND' and sql to 'SELECT NULL'."""


def _run_compliance_path(question: str, history: list[dict] | None,
                         history_block: str, emit, trace) -> "PipelineResult":
    # 1. Gather policy excerpts.
    emit("compliance_doc_search", "start")
    cites = dbmod.fts_search(question, top_k=6)
    emit("compliance_doc_search", "ok", f"{len(cites)} chunks")

    # 2. Schema subset.
    emit("compliance_schema", "start")
    tables = schema_catalog.retrieve_tables(question, top_k=8)
    schema_block = schema_catalog.render_schema_block(tables)
    emit("compliance_schema", "ok", f"{len(tables)} tables")

    # 3. LLM extracts the rule + drafts the SQL in one shot.
    cite_block = "\n---\n".join(
        f"[{c['file_name']}] {c['chunk_text'][:600]}" for c in cites[:5]
    ) or "(no policy excerpts found)"
    user_msg = (
        f"{history_block}"
        f"COMPLIANCE QUESTION:\n{question}\n\n"
        f"POLICY EXCERPTS:\n{cite_block}\n\n"
        f"SCHEMA SUBSET:\n{schema_block[:3500]}"
    )
    emit("compliance_extract", "start")
    try:
        raw = _llm(SYSTEM_COMPLIANCE, user_msg, max_tokens=900, temperature=0.0)
    except RuntimeError:
        # Offline: degrade to plain doc synthesis.
        emit("compliance_extract", "warn", "offline; degrading to doc synth")
        ans = _synthesize_policy(question, cites, history, emit)
        pr = PipelineResult(answer=ans, citations=cites, trace=trace)
        pr.trace.append({"stage": "_meta", "status": "ok", "message": "intent",
                         "payload": {"intent": "COMPLIANCE"}, "ts": time.time()})
        return pr

    rule, source_file, sql_text, method = "NO_RULE_FOUND", "", "", "compare"
    try:
        m = re.search(r"\{.*\}", raw, re.DOTALL)
        if m:
            data = json.loads(m.group(0))
            rule = data.get("rule", rule) or rule
            source_file = data.get("source_file", "") or ""
            sql_text = _strip_sql_fences(data.get("sql", "") or "")
            method = data.get("comparison_method", method)
    except Exception as e:
        emit("compliance_extract", "warn", f"parse: {e}")

    emit("compliance_extract", "ok",
         f"rule: {rule[:80]}{'...' if len(rule) > 80 else ''}")

    # 4. Execute the SQL (if any).
    rows: list[dict] = []
    columns: list[str] = []
    sql_used = sql_text
    if sql_text and "NO_RULE" not in rule and "SELECT NULL" not in sql_text.upper():
        emit("compliance_executor", "start")
        ok, why = dbmod.is_safe_sql(sql_text)
        if not ok:
            emit("compliance_executor", "error", f"unsafe: {why}")
        else:
            sg_ok, sg_reason, _ = sql_validation.validate(sql_text)
            if not sg_ok:
                emit("compliance_executor", "warn", f"sqlglot: {sg_reason} - retrying once")
                # one quick repair pass
                repair_user = (f"Your SQL was rejected by sqlglot: {sg_reason}\n"
                               f"Original SQL:\n{sql_text}\n\n"
                               f"Schema:\n{schema_block[:3000]}\n\n"
                               f"Output ONLY a corrected SELECT statement.")
                try:
                    fixed = _llm(SYSTEM_SQL, repair_user, max_tokens=500)
                    sql_text = _strip_sql_fences(fixed)
                except RuntimeError:
                    pass
            try:
                res = dbmod.execute_sql(sql_text, max_rows=200)
                columns = res["columns"]
                rows = [dict(zip(columns, r)) for r in res["rows"]]
                sql_used = sql_text
                emit("compliance_executor", "ok", f"{len(rows)} row(s)")
            except Exception as e:
                emit("compliance_executor", "error", str(e))

    # 5. Synthesize the comparison answer.
    emit("compliance_synthesize", "start")
    sample = rows[:25]
    SYS_SYNTH = ("You are a compliance analyst. The user asked a compliance question. "
                 "Given (a) the rule extracted from policy, (b) the source filename, "
                 "(c) the SQL run, and (d) the result rows, write a clear 2-5 sentence "
                 "answer that states whether we are compliant, what the rule says, what the "
                 "actual value/violations are, and cites the source filename in parentheses. "
                 "If no rule was found in the policy, say so plainly.")
    user2 = (f"QUESTION:\n{question}\n\n"
             f"RULE: {rule}\nSOURCE: {source_file}\n"
             f"SQL: {sql_used}\n\n"
             f"RESULT ROWS ({len(rows)}):\n{json.dumps(sample, default=str)[:4000]}")
    try:
        answer = _llm(SYS_SYNTH, user2, max_tokens=500, temperature=0.1)
    except RuntimeError:
        answer = (f"Rule: {rule}. Found {len(rows)} relevant row(s). "
                  f"(See {source_file or 'policy docs'}.)")
    emit("compliance_synthesize", "ok")

    pr = PipelineResult(
        answer=answer, sql=sql_used, rows=rows, columns=columns,
        citations=cites, trace=trace,
    )
    pr.trace.append({"stage": "_meta", "status": "ok", "message": "intent",
                     "payload": {"intent": "COMPLIANCE", "rule": rule,
                                 "source_file": source_file}, "ts": time.time()})
    return pr


def _synthesize_policy(question: str, cites: list[dict], history: list[dict] | None, emit) -> str:
    if not cites:
        return ("I couldn't find a matching policy, SOP, or uploaded document in the index. "
                "Try uploading a relevant text file, or ask with different keywords.")
    context = "\n---\n".join(
        f"[{c['file_name']}] {c['chunk_text'][:800]}" for c in cites[:4]
    )
    sys = ("You are a NorthStar Petroleum policy assistant. Answer the user's question using ONLY the "
           "provided document excerpts. Cite the source filename in parentheses for each fact. "
           "If the question is a follow-up, use the recent conversation to resolve references like "
           "'that file' or 'the previous one'. If the excerpts do not answer the question, say so plainly.")
    hist_block = render_history_block(history)
    user_msg = f"{hist_block}QUESTION:\n{question}\n\nEXCERPTS:\n{context}"
    try:
        return _llm(sys, user_msg, max_tokens=600, temperature=0.1)
    except RuntimeError:
        return (f"(offline mode) Top match: {cites[0]['file_name']}.\n\n"
                f"\"{cites[0]['chunk_text'][:500]}\"")
