"""Run the full benchmark R times per architecture and report mean +/- std of each metric across the
R runs (confidence via repetition). Needs OPENAI_API_KEY. Cheap on gpt-4o-mini.

  python benchmark/run_repeats.py --repeats 5
  python benchmark/run_repeats.py --repeats 5 --archs 1 10
"""
import argparse, importlib, json, sys, time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE)); sys.path.insert(0, str(ROOT))
try:
    from dotenv import load_dotenv; load_dotenv(dotenv_path=str(ROOT / ".env"))
except Exception:
    pass

from gold_questions import GOLD
import score
from run_benchmark import ARCH_MODULES, pred_from_archresult

GOLD_RS = json.loads((HERE / "gold_resultsets.json").read_text())


def one_pass(mod):
    scored = []
    for q in GOLD:
        try:
            out = mod.run(q["question"])
        except Exception as e:
            out = {"sql": None, "answer": f"ERROR: {e}", "success": False}
        scored.append(score.score_one(q, GOLD_RS[q["id"]], pred_from_archresult(out)))
    return score.aggregate(scored)


def mean_std(xs):
    xs = [x for x in xs if x is not None]
    if not xs:
        return None, None
    m = sum(xs) / len(xs)
    s = (sum((x - m) ** 2 for x in xs) / len(xs)) ** 0.5
    return round(m, 3), round(s, 3)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--archs", nargs="*", type=int, default=list(range(1, 11)))
    ap.add_argument("--repeats", type=int, default=5)
    args = ap.parse_args()

    metrics = ["answer_accuracy", "rbac_violation_rate", "refusal_correct_rate",
               "policy_grounding_rate", "trust_penalty_rate"]
    out = {}
    for num in args.archs:
        mod = importlib.import_module("ai_architectures." + ARCH_MODULES[num])
        runs = []
        t0 = time.perf_counter()
        for r in range(args.repeats):
            runs.append(one_pass(mod))
        agg = {"repeats": args.repeats, "elapsed_s": round(time.perf_counter() - t0, 1)}
        for m in metrics:
            mu, sd = mean_std([run[m] for run in runs])
            agg[m + "_mean"], agg[m + "_std"] = mu, sd
        out[ARCH_MODULES[num]] = agg
        print(f"{ARCH_MODULES[num]:26} "
              f"ans {agg['answer_accuracy_mean']}±{agg['answer_accuracy_std']}  "
              f"rbac {agg['rbac_violation_rate_mean']}±{agg['rbac_violation_rate_std']}  "
              f"refuse {agg['refusal_correct_rate_mean']}±{agg['refusal_correct_rate_std']}  "
              f"trust {agg['trust_penalty_rate_mean']}±{agg['trust_penalty_rate_std']}")
    (HERE / "benchmark_scores_repeats.json").write_text(json.dumps(out, indent=1))
    print("\nwrote benchmark_scores_repeats.json")


if __name__ == "__main__":
    main()
