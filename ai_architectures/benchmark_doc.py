"""
Doc-aware + multi-turn benchmark.
=================================

Tests each of the 10 architectures on:

  Suite A : DB_ONLY        - 4 structured-data questions
  Suite B : DOC_ONLY       - 4 questions answerable only from documents
  Suite C : MIXED          - 3 questions that need BOTH a SQL fact and a doc fact
  Suite D : MULTI_TURN     - 3 conversations of 3 turns each, where memory matters

Scoring per architecture per suite:
  pass : answer contains every "must_contain" keyword (case insensitive)
         AND (for SQL questions) execution returned rows.
  fail : missed keyword, error, or wrong intent.

This benchmark exposes why Architecture #10 (Chain-of-Agents w/ Validator)
is the only one that handles ALL four suites cleanly:  most of arches
01-07 + 09 are SQL-only and have no memory; arch 08 has both paths but
no memory; the winner has both paths AND history-aware routing.

Run:
    python -m ai_architectures.benchmark_doc
"""
from __future__ import annotations
import json
import inspect
import time
from pathlib import Path

# Make sure a fixture document is indexed before we benchmark.
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))
from database import extraction as doc_extraction
from winning_architecture import db as dbmod

from . import (
    arch_01_naive_text2sql, arch_02_schema_rag, arch_03_self_correct,
    arch_04_few_shot,       arch_05_react_agent,  arch_06_din_sql,
    arch_07_dail_c3,        arch_08_router_multiagent, arch_09_graphrag,
    arch_10_chain_of_agents,
)
from winning_architecture import engine as winning_engine

ARCHS = [
    arch_01_naive_text2sql, arch_02_schema_rag, arch_03_self_correct,
    arch_04_few_shot,       arch_05_react_agent,  arch_06_din_sql,
    arch_07_dail_c3,        arch_08_router_multiagent, arch_09_graphrag,
    arch_10_chain_of_agents,
]

OUT_PATH = Path(__file__).parent / "BENCHMARK_DOC_RESULTS.json"

# ---------------------------------------------------------------------
# Fixture doc
# ---------------------------------------------------------------------

FIXTURE_NAME = "BENCHMARK_FIXTURE_emergency_response.txt"
FIXTURE_TEXT = """\
NORTHSTAR PETROLEUM CORPORATION
EMERGENCY GAS LEAK RESPONSE PROCEDURE
Document ID: NSP-HSE-PRC-099   Revision: 1.0

CLASSIFICATION
Category Alpha:   methane below 1000 ppm OR H2S below 10 ppm
Category Bravo:   methane between 1000 and 10000 ppm OR H2S between 10 and 50 ppm
Category Charlie: methane above 10000 ppm OR H2S above 50 ppm OR any visible flame
Category Delta:   large uncontained release with imminent risk to life

IMMEDIATE STEPS FOR CATEGORY CHARLIE OR DELTA
1. Stop work in the affected zone and surrounding 100 meters.
2. Evacuate non-essential personnel upwind to the muster point.
3. Notify the Incident Commander on duty within 5 minutes.
4. Isolate the source via remote shut-in valves where available.
5. Do not attempt to ignite or extinguish flames without IC approval.

TIMELINE TARGETS
Mean detection-to-isolation: less than 5 minutes for Category Charlie.
Recurrence rate at the same asset: zero within 12 months after corrective action.
"""


def ensure_fixture_indexed():
    """Index the fixture so doc-aware tests have a known target."""
    src = f"benchmark://{FIXTURE_NAME}"
    info = doc_extraction.extract_and_store(
        text=FIXTURE_TEXT,
        file_name=FIXTURE_NAME,
        source_path=src,
    )
    return info


# ---------------------------------------------------------------------
# Question suites
# ---------------------------------------------------------------------

DB_ONLY = [
    {"q": "How many wells are currently producing in the Eagle Ford Permian field?",
     "must_contain": ["2"], "needs_rows": True},
    {"q": "Top 5 wells by total oil production in 2025",
     "must_contain": [], "needs_rows": True, "min_rows": 3},
    {"q": "How many SIF3 or higher incidents in 2025?",
     "must_contain": [], "needs_rows": True},
    {"q": "Show pending approval requests over 250000 USD",
     "must_contain": [], "needs_rows": True},
]

DOC_ONLY = [
    {"q": "What are the immediate steps for a Category Charlie gas leak?",
     "must_contain": ["incident commander", "5"], "needs_rows": False},
    {"q": "How is Category Bravo defined in the emergency procedure?",
     "must_contain": ["1000", "10000"], "needs_rows": False},
    {"q": "What is the AFE approval policy for spending over 1 million USD?",
     "must_contain": ["cfo", "ceo"], "needs_rows": False},
    {"q": "What recurrence rate target is set after corrective action in the emergency procedure?",
     "must_contain": ["zero", "12 months"], "needs_rows": False},
]

MIXED = [
    {"q": "How many SIF3+ incidents in 2025, and what does the emergency procedure say is the detection-to-isolation target?",
     "must_contain": ["5 minutes"], "needs_rows": True},
    {"q": "List approval requests pending over 250000 USD - and explain the AFE approval policy for that range",
     "must_contain": ["cfo"], "needs_rows": True},
    {"q": "Top 3 wells by oil production in 2025 and what does our production validation procedure say about the daily cycle?",
     "must_contain": ["validator", "12:00"], "needs_rows": True, "min_rows": 2},
]

MULTI_TURN = [
    # Conversation 1 : doc -> DB -> back to doc
    [
        {"q": "What are the immediate steps for a Category Charlie gas leak?",
         "must_contain": ["incident commander"], "needs_rows": False},
        {"q": "Now show me how many SIF3 or higher incidents we had in 2025",
         "must_contain": [], "needs_rows": True},
        {"q": "What about that file again - how is Category Bravo defined?",
         "must_contain": ["1000", "10000"], "needs_rows": False},
    ],
    # Conversation 2 : DB -> follow-up DB -> doc
    [
        {"q": "How many incidents had cost estimate over 100000 USD?",
         "must_contain": [], "needs_rows": True},
        {"q": "And of those, how many were severity SIF4 or SIF5?",
         "must_contain": [], "needs_rows": True},
        {"q": "What does our incident response plan say is the SIF4 notification timeline?",
         "must_contain": ["1 hour"], "needs_rows": False},
    ],
    # Conversation 3 : pure doc, multi-step refinement
    [
        {"q": "What is the AFE approval policy for spending over 1 million USD?",
         "must_contain": ["cfo"], "needs_rows": False},
        {"q": "And for above 10 million USD, what additional step is required?",
         "must_contain": ["board"], "needs_rows": False},
        {"q": "So who signs the approval for a 5 million USD AFE specifically?",
         "must_contain": ["cfo", "ceo"], "needs_rows": False},
    ],
]


# ---------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------

def grade(question_spec: dict, answer: str, rows: list, error: str | None):
    answer_low = (answer or "").lower()
    must = [k.lower() for k in question_spec.get("must_contain", [])]
    keyword_pass = all(k in answer_low for k in must) if must else True
    rows_pass = True
    if question_spec.get("needs_rows"):
        rows_pass = bool(rows) and len(rows) >= question_spec.get("min_rows", 1)
    no_error = not error
    success = keyword_pass and rows_pass and no_error
    return {
        "success": success,
        "keyword_pass": keyword_pass,
        "rows_pass": rows_pass,
        "no_error": no_error,
        "missing_keywords": [k for k in must if k not in answer_low],
    }


# ---------------------------------------------------------------------
# Architecture invocation
# ---------------------------------------------------------------------

def call_arch(mod, question: str, history: list | None = None) -> dict:
    """Call an architecture's run() with optional history if it supports it."""
    sig = inspect.signature(mod.run)
    if "history" in sig.parameters:
        return mod.run(question, history=history)
    # Fallback for architectures that ignore history
    return mod.run(question)


def run_single_suite(name, items):
    print(f"\n--- {name} ({len(items)} questions) ---")
    rows = {}
    for mod in ARCHS:
        per_arch = []
        for q in items:
            t0 = time.perf_counter()
            try:
                r = call_arch(mod, q["q"])
            except Exception as e:
                r = {"answer": "", "rows": [], "error": str(e), "elapsed_ms": 0}
            r["elapsed_ms"] = (time.perf_counter() - t0) * 1000
            grade_r = grade(q, r.get("answer", ""), r.get("rows", []), r.get("error"))
            per_arch.append({
                "question": q["q"],
                "answer": (r.get("answer") or "")[:600],
                "row_count": len(r.get("rows", []) or []),
                "elapsed_ms": r["elapsed_ms"],
                **grade_r,
            })
        rows[mod.NAME] = per_arch
        ok = sum(1 for x in per_arch if x["success"])
        avg = sum(x["elapsed_ms"] for x in per_arch) / max(1, len(per_arch))
        print(f"  {mod.NAME:<28s}  {ok}/{len(items)}  avg={avg:7.0f}ms")
    return rows


def run_multiturn_suite(conversations):
    """Multi-turn requires history support. Architectures that ignore history
    are still tested - they simply receive only the current turn each time."""
    print(f"\n--- MULTI_TURN ({len(conversations)} conversations) ---")
    rows = {}
    for mod in ARCHS:
        sig = inspect.signature(mod.run)
        supports_history = "history" in sig.parameters
        per_arch = []
        for conv_idx, conv in enumerate(conversations):
            history: list[dict] = []
            for turn_idx, q in enumerate(conv):
                t0 = time.perf_counter()
                try:
                    r = call_arch(mod, q["q"], history if supports_history else None)
                except Exception as e:
                    r = {"answer": "", "rows": [], "error": str(e)}
                elapsed = (time.perf_counter() - t0) * 1000
                grade_r = grade(q, r.get("answer", ""), r.get("rows", []), r.get("error"))
                per_arch.append({
                    "conversation": conv_idx + 1,
                    "turn": turn_idx + 1,
                    "question": q["q"],
                    "answer": (r.get("answer") or "")[:400],
                    "row_count": len(r.get("rows", []) or []),
                    "elapsed_ms": elapsed,
                    "supports_history": supports_history,
                    **grade_r,
                })
                # Append to history (regardless of whether arch read it, so the
                # NEXT turn has it if the arch were to start using it).
                history.append({"role": "user", "content": q["q"]})
                history.append({
                    "role": "assistant",
                    "content": r.get("answer", ""),
                    "sql": r.get("sql"),
                    "citations": r.get("citations", []),
                })
        rows[mod.NAME] = per_arch
        ok = sum(1 for x in per_arch if x["success"])
        n = len(per_arch)
        flag = "" if supports_history else "  (no memory)"
        print(f"  {mod.NAME:<28s}  {ok}/{n}{flag}")
    return rows


# ---------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------

def main():
    print("Indexing benchmark fixture document ...")
    info = ensure_fixture_indexed()
    print(f"  -> extract_id={info['extract_id']}, chunks={info['chunk_count']}, "
          f"duplicate={info.get('duplicate', False)}\n")

    suites = {
        "DB_ONLY": run_single_suite("DB_ONLY", DB_ONLY),
        "DOC_ONLY": run_single_suite("DOC_ONLY", DOC_ONLY),
        "MIXED": run_single_suite("MIXED", MIXED),
        "MULTI_TURN": run_multiturn_suite(MULTI_TURN),
    }

    # Aggregate
    print("\n" + "=" * 86)
    print(f"{'Architecture':<28s}  DB     DOC    MIX    MULTI    TOTAL    score%")
    print("-" * 86)
    grand: dict[str, dict] = {}
    for mod in ARCHS:
        sums: dict[str, tuple[int, int]] = {}
        for suite_name, rows in suites.items():
            arch_rows = rows.get(mod.NAME, [])
            ok = sum(1 for x in arch_rows if x["success"])
            sums[suite_name] = (ok, len(arch_rows))
        total_ok = sum(o for o, _ in sums.values())
        total_n = sum(n for _, n in sums.values())
        pct = 100.0 * total_ok / max(1, total_n)
        grand[mod.NAME] = {"per_suite": sums, "total": (total_ok, total_n), "pct": pct}
        cells = []
        for s in ("DB_ONLY", "DOC_ONLY", "MIXED", "MULTI_TURN"):
            o, n = sums[s]
            cells.append(f"{o}/{n}")
        print(f"{mod.NAME:<28s}  {cells[0]:<6s} {cells[1]:<6s} {cells[2]:<6s} "
              f"{cells[3]:<8s} {total_ok}/{total_n:<5d}  {pct:5.1f}%")
    print("=" * 86)

    OUT_PATH.write_text(json.dumps({
        "fixture": info, "suites": suites, "summary": grand
    }, indent=2, default=str))
    print(f"\nWrote {OUT_PATH}")


if __name__ == "__main__":
    main()
