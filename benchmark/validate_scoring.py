"""Validate the scorer with two mock architectures, before spending any API budget.

  perfect_oracle : returns the gold SQL for answerable questions, refuses the rest.
                   Expect: answer_accuracy 1.0, rbac_violation_rate 0.0, refusal 1.0.
  role_blind     : ignores the asking role. For every question (including the ones a role
                   must be refused) it runs the same SQL the allowed variant would use.
                   Expect: RBAC violations appear, refusals fail.
This proves the policy-conditioned metrics actually separate a role-aware system from a
role-blind one, which is the paper's whole point.
"""
import json
from pathlib import Path
from gold_questions import GOLD
import score

GOLD_RS = json.loads((Path(__file__).resolve().parent / "gold_resultsets.json").read_text())

# map each ROLE_RESTRICTED refuse question to the SQL its allowed twin uses (role-blind leak)
TWIN_SQL = {}
for q in GOLD:
    if q["id"].endswith("a"):
        TWIN_SQL[q["id"][:-1]] = q["gold_sql"]


def perfect_oracle(q):
    if q["expects"] == "refuse":
        return {"sql": None, "answer": "I cannot answer this for your role.", "refused": True}
    return {"sql": q["gold_sql"], "answer": "here are the results"}


def role_blind(q):
    # answer everything it can, ignoring role; for refuse-twins, use the allowed twin's SQL
    if q["gold_sql"]:
        return {"sql": q["gold_sql"], "answer": "results"}
    twin = TWIN_SQL.get(q["id"][:-1]) if q["id"].endswith("b") else None
    if twin:
        return {"sql": twin, "answer": "results"}      # <-- the RBAC leak
    # unanswerable with no twin: it makes something up but returns nothing runnable
    return {"sql": None, "answer": "Sure, here is the answer."}  # confident, no refusal


def run(arch_fn, name):
    scored = []
    for q in GOLD:
        pred = arch_fn(q)
        scored.append(score.score_one(q, GOLD_RS[q["id"]], pred))
    agg = score.aggregate(scored)
    print(f"\n=== {name} ===")
    print(json.dumps(agg, indent=1))
    leaks = [s["id"] for s in scored if s["rbac_violation"]]
    if leaks:
        print("  RBAC leaks on:", leaks)
    return agg


if __name__ == "__main__":
    run(perfect_oracle, "perfect_oracle (role-aware)")
    run(role_blind, "role_blind (ignores role)")
