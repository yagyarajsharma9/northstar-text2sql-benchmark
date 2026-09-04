"""Pull out the winner's failures and the spread vs other archs."""
import json
from pathlib import Path

p = Path("C:/Users/Administrator/Desktop/Aiwrapper/ai_architectures/BENCHMARK_ROUND3_RESULTS.json")
data = json.loads(p.read_text())

WINNER = "10_chain_of_agents"

print("=" * 90)
print("WHERE THE WINNER LOST POINTS")
print("=" * 90)
for suite_name, runs in data["suites"].items():
    arch_runs = runs.get(WINNER, [])
    failed = [r for r in arch_runs if not r["success"]]
    if not failed:
        continue
    print(f"\n[{suite_name}] {len(failed)} failure(s):")
    for r in failed:
        q = r.get("question", "")[:90]
        fails = r.get("fails", [])
        print(f"  Q: {q}")
        print(f"     FAILS: {fails}")
        ans = (r.get("answer") or "").replace("\n", " ")[:160]
        print(f"     ANS:   {ans}")
        if r.get("sql"):
            sql = r["sql"][:160]
            print(f"     SQL:   {sql}")

print("\n" + "=" * 90)
print("PER-SUITE SPREAD vs ALL OTHERS (winner advantage)")
print("=" * 90)
others = [k for k in data["summary"] if k != WINNER]
for s in ("HARD_SQL", "HARD_DOC", "COMPLIANCE", "ADVERSARIAL", "SECURITY", "LONG_MULTI_TURN"):
    w_ok, w_n = data["summary"][WINNER]["per_suite"][s]
    other_avg = sum(data["summary"][o]["per_suite"][s][0] for o in others) / len(others)
    print(f"  {s:<18s}  winner={w_ok}/{w_n}  others_avg={other_avg:.1f}/{w_n}  "
          f"advantage=+{w_ok - other_avg:.1f}")
