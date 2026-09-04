"""Quick end-to-end smoke test of the live LLM pipeline."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from winning_architecture import engine

print(f"PROVIDER: {engine.active_provider()}")
print(f"MODEL:    {engine.active_model()}")
print()

QUESTIONS = [
    "How many wells are currently producing in the Eagle Ford Permian field?",
    "What is the AFE approval policy for spending over 1 million USD?",
]

for q in QUESTIONS:
    print("=" * 78)
    print(f"Q: {q}")
    print("=" * 78)
    r = engine.run_chain(q)
    print("\nANSWER:\n" + (r.answer or "(none)"))
    if r.sql:
        print("\nSQL:\n" + r.sql)
    print(f"\nROWS: {len(r.rows)}")
    if r.rows:
        for row in r.rows[:3]:
            print("  ", row)
    if r.citations:
        print(f"\nCITATIONS: {[c['file_name'] for c in r.citations[:3]]}")
    print("\nTRACE:")
    for t in r.trace:
        print(f"  {t['status']:5s}  {t['stage']:20s}  {t.get('message','')}")
    print()
