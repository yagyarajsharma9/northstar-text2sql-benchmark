"""Run the 10 architectures on the gold set and score them with the policy-conditioned metrics.

Needs ANTHROPIC_API_KEY in the environment / .env (the architectures call Claude). Without a key
they fall back to an offline example bank that only covers the original demo questions, so the
scores will be meaningless: set the key before trusting output.

Usage:
  python benchmark/run_benchmark.py                 # all 10 architectures, 1 run
  python benchmark/run_benchmark.py --archs 1 10    # only arch_01 and arch_10
  python benchmark/run_benchmark.py --repeats 5     # 5 repeated runs, report mean

Each architecture is role-blind: run(question) has no role argument. The benchmark asks each
question AS a given role (from the gold set) and scores whether the architecture respected that
role. This is the point: SQL correctness and role safety are different axes.
"""
import argparse, importlib, json, sys, time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT))
try:
    from dotenv import load_dotenv
    load_dotenv(dotenv_path=str(ROOT / ".env"))
except Exception:
    pass

from gold_questions import GOLD
import score

GOLD_RS = json.loads((HERE / "gold_resultsets.json").read_text())
ARCH_MODULES = {
    1: "arch_01_naive_text2sql", 2: "arch_02_schema_rag", 3: "arch_03_self_correct",
    4: "arch_04_few_shot", 5: "arch_05_react_agent", 6: "arch_06_din_sql",
    7: "arch_07_dail_c3", 8: "arch_08_router_multiagent", 9: "arch_09_graphrag",
    10: "arch_10_chain_of_agents",
}


def pred_from_archresult(r):
    """Adapt an architecture's run() dict to the scorer's pred shape."""
    return {"sql": r.get("sql"), "answer": r.get("answer") or "",
            "refused": (not r.get("sql")) and not r.get("success", False)}


def run_arch(num, repeats):
    mod = importlib.import_module("ai_architectures." + ARCH_MODULES[num])
    per_q_runs = {}
    for rep in range(repeats):
        for q in GOLD:
            try:
                out = mod.run(q["question"])
            except Exception as e:
                out = {"sql": None, "answer": f"ERROR: {e}", "success": False}
            s = score.score_one(q, GOLD_RS[q["id"]], pred_from_archresult(out))
            per_q_runs.setdefault(q["id"], []).append(s)
    # majority/any aggregation across repeats: use the first run's flags for structure,
    # average the booleans across repeats for stability
    scored = []
    for q in GOLD:
        runs = per_q_runs[q["id"]]
        base = dict(runs[0])
        for k in ("answer_correct", "rbac_violation", "refused_correctly", "trust_penalty"):
            base[k] = sum(bool(r[k]) for r in runs) / len(runs) >= 0.5
        if base["category"] == "POLICY_GROUNDED":
            base["policy_grounded"] = base["answer_correct"]
        scored.append(base)
    return score.aggregate(scored), scored


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--archs", nargs="*", type=int, default=list(range(1, 11)))
    ap.add_argument("--repeats", type=int, default=1)
    args = ap.parse_args()

    import os
    if not (os.environ.get("OPENAI_API_KEY") or os.environ.get("ANTHROPIC_API_KEY")):
        print("WARNING: no OPENAI_API_KEY or ANTHROPIC_API_KEY set. Architectures will use the "
              "offline fallback and scores will NOT be meaningful. Set a key, then re-run.\n")

    results = {}
    for num in args.archs:
        t0 = time.perf_counter()
        try:
            agg, _ = run_arch(num, args.repeats)
            agg["elapsed_s"] = round(time.perf_counter() - t0, 1)
            results[ARCH_MODULES[num]] = agg
            print(f"{ARCH_MODULES[num]:26} {json.dumps(agg)}")
        except Exception as e:
            print(f"{ARCH_MODULES[num]:26} FAILED: {e}")
    out = HERE / "benchmark_scores.json"
    out.write_text(json.dumps(results, indent=1))
    print("\nwrote", out.name)


if __name__ == "__main__":
    main()
