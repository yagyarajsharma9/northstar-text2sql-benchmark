"""Ablation: does the Validator Gate in the chain-of-agents architecture help?
Run the chain on the gold set with the gate ON and with it OFF, score both, report the difference.
Needs OPENAI_API_KEY. Writes 03 ablation_validator.json.
"""
import json, sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE)); sys.path.insert(0, str(ROOT))
try:
    from dotenv import load_dotenv; load_dotenv(dotenv_path=str(ROOT / ".env"))
except Exception:
    pass

from ai_architectures import common  # noqa: ensures package import path
from winning_architecture import engine
from gold_questions import GOLD
import score

GOLD_RS = json.loads((HERE / "gold_resultsets.json").read_text())


def pred_from_pr(pr):
    sql = pr.sql
    return {"sql": sql, "answer": pr.answer or "",
            "refused": (not sql) and not bool(pr.rows)}


def one_pass(use_validator):
    scored = []
    for q in GOLD:
        try:
            pr = engine.run_chain(q["question"], use_validator=use_validator)
            pred = pred_from_pr(pr)
        except Exception as e:
            pred = {"sql": None, "answer": f"ERROR: {e}", "refused": False}
        scored.append(score.score_one(q, GOLD_RS[q["id"]], pred))
    return score.aggregate(scored)


def main():
    on = one_pass(True)
    print("validator ON :", json.dumps(on))
    off = one_pass(False)
    print("validator OFF:", json.dumps(off))
    delta = {k: (None if on.get(k) is None or off.get(k) is None
                 else round(on[k] - off[k], 3)) for k in on if k != "n"}
    out = {"validator_on": on, "validator_off": off, "on_minus_off": delta}
    (HERE / "ablation_validator.json").write_text(json.dumps(out, indent=1))
    print("\nON - OFF (positive = gate helps that metric):")
    print(json.dumps(delta, indent=1))
    print("wrote ablation_validator.json")


if __name__ == "__main__":
    main()
