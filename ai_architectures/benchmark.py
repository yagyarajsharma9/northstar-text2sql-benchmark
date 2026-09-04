"""
Benchmark harness : run all 10 architectures against a fixed Q-set
and print a comparison table.

Run:  python -m ai_architectures.benchmark
"""
from __future__ import annotations
import json
import time
from pathlib import Path

from . import (
    arch_01_naive_text2sql,
    arch_02_schema_rag,
    arch_03_self_correct,
    arch_04_few_shot,
    arch_05_react_agent,
    arch_06_din_sql,
    arch_07_dail_c3,
    arch_08_router_multiagent,
    arch_09_graphrag,
    arch_10_chain_of_agents,
)

ARCHS = [
    arch_01_naive_text2sql, arch_02_schema_rag, arch_03_self_correct,
    arch_04_few_shot,       arch_05_react_agent,  arch_06_din_sql,
    arch_07_dail_c3,        arch_08_router_multiagent, arch_09_graphrag,
    arch_10_chain_of_agents,
]

QUESTIONS = [
    "How many wells are currently producing in the Eagle Ford Permian field?",
    "Top 5 wells by total oil production in 2025",
    "Show pending approval requests over 250000 USD",
    "Which invoices are overdue and over 100k USD?",
    "How many SIF3 or higher incidents in 2025?",
    "Average daily oil production per field in the last 90 days",
    "Pipeline segments needing repair",
    "Top 10 customers by shipment value this year",
]


def fmt_row(arch: str, ok: int, n: int, avg_ms: float, notes: str = "") -> str:
    return f"{arch:<28s}  {ok:>2d}/{n:<2d}  {avg_ms:>7.1f} ms   {notes}"


def main():
    out_dir = Path(__file__).parent
    out_path = out_dir / "BENCHMARK_RESULTS.json"

    results: dict = {"questions": QUESTIONS, "runs": {}}
    print(f"Running {len(ARCHS)} architectures x {len(QUESTIONS)} questions ...\n")

    for mod in ARCHS:
        name = mod.NAME
        print(f"[{name}]")
        runs = []
        for q in QUESTIONS:
            try:
                r = mod.run(q)
            except Exception as e:
                r = {"arch": name, "question": q, "success": False,
                     "error": str(e), "elapsed_ms": 0, "row_count": 0}
            runs.append(r)
            mark = "OK" if r.get("success") else "X "
            print(f"  {mark} {q[:60]:<62s} rows={r.get('row_count',0):<3d}  "
                  f"{r.get('elapsed_ms',0):>6.0f}ms")
        results["runs"][name] = runs
        print()

    print("\n" + "=" * 78)
    print(f"{'Architecture':<28s}  Pass   Avg Time    Notes")
    print("-" * 78)
    for arch_name, runs in results["runs"].items():
        ok = sum(1 for r in runs if r.get("success"))
        n = len(runs)
        avg = sum(r.get("elapsed_ms", 0) for r in runs) / max(n, 1)
        print(fmt_row(arch_name, ok, n, avg))
    print("=" * 78)

    out_path.write_text(json.dumps(results, indent=2, default=str))
    print(f"\nWrote {out_path}")


if __name__ == "__main__":
    main()
