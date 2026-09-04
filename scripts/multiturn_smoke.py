"""
Multi-turn smoke test : the exact user scenario.
   1. Upload a fresh policy file
   2. Ask about that file
   3. Pivot to a database question
   4. Pivot BACK to the file with a vague follow-up ("what about that file again?")
   5. Continue with another file question
"""
import json
import requests
import uuid
from pathlib import Path

BASE = "http://127.0.0.1:8000"
SID = uuid.uuid4().hex
print(f"session_id = {SID}\n")

# 1. upload
fixture = Path(__file__).parent / "fixture_emergency_doc.txt"
fixture.write_text(
    "NORTHSTAR PETROLEUM CORPORATION\n"
    "EMERGENCY GAS LEAK RESPONSE PROCEDURE\n"
    "Document ID: NSP-HSE-PRC-099   Revision: 1.0\n"
    "\n"
    "CLASSIFICATION:\n"
    "Category Alpha:   methane below 1000 ppm OR H2S below 10 ppm\n"
    "Category Bravo:   methane 1000-10000 ppm OR H2S 10-50 ppm\n"
    "Category Charlie: methane above 10000 ppm OR H2S above 50 ppm OR visible flame\n"
    "Category Delta:   large uncontained release with imminent risk to life\n"
    "\n"
    "IMMEDIATE STEPS for Category Charlie or Delta:\n"
    "1. Stop work in the affected zone and surrounding 100 meters.\n"
    "2. Evacuate non-essential personnel upwind to the muster point.\n"
    "3. Notify the Incident Commander on duty within 5 minutes.\n"
    "4. Isolate the source via remote shut-in valves where available.\n"
    "5. Do not attempt to ignite or extinguish flames without IC approval.\n"
    "\n"
    "TIMELINE TARGETS:\n"
    "Mean detection-to-isolation: less than 5 minutes for Charlie.\n"
    "Recurrence rate same asset:  zero within 12 months after corrective action.\n",
    encoding="utf-8"
)

print("=" * 80)
print(f"TURN 1: upload {fixture.name}")
print("=" * 80)
with open(fixture, "rb") as f:
    r = requests.post(f"{BASE}/api/upload?session_id={SID}",
                      files={"file": (fixture.name, f, "text/plain")})
info = r.json()
print(f"  -> indexed extract_id={info['extract_id']}, chunks={info['chunk_count']}")
print()


def chat(q):
    r = requests.post(f"{BASE}/api/chat", json={"question": q, "session_id": SID})
    return r.json()


turns = [
    "What are the immediate steps for a Category Charlie gas leak according to the procedure I just uploaded?",
    "Now show me how many SIF3 or higher incidents we had in 2025",
    "What about that file again - what is Category Bravo defined as?",
    "And what is the timeline target for detection-to-isolation in Category Charlie?",
    "Compare that target with the average resolution time we have for incidents in our database (just give me the number of incidents with cost over 100k)",
]

for i, q in enumerate(turns, start=2):
    print("=" * 80)
    print(f"TURN {i}: {q}")
    print("=" * 80)
    r = chat(q)
    print("ANSWER:")
    print(r.get("answer", "(none)"))
    if r.get("sql"):
        print(f"\nSQL: {r['sql']}")
    if r.get("rows"):
        print(f"ROWS ({len(r['rows'])}): first={r['rows'][0]}")
    if r.get("citations"):
        cites = list({c["file_name"] for c in r["citations"]})
        print(f"CITATIONS: {cites}")
    # Pull intent from trace
    intent = next((ev["payload"].get("intent")
                   for ev in r.get("trace", [])[::-1] if ev.get("stage") == "_meta"),
                  "?")
    print(f"INTENT: {intent}")
    print()

# Show final session history snapshot
print("=" * 80)
print("FINAL SESSION HISTORY")
print("=" * 80)
hist = requests.get(f"{BASE}/api/session/{SID}").json()
for i, h in enumerate(hist["history"], 1):
    role = h["role"].upper()
    snippet = (h.get("content") or "").replace("\n", " ")[:140]
    extra = ""
    if h.get("sql"):
        extra += f"  sql={h['sql'][:60]}..."
    if h.get("citations"):
        fns = [c["file_name"] for c in h["citations"][:2]]
        extra += f"  cited={fns}"
    if h.get("intent"):
        extra += f"  intent={h['intent']}"
    print(f"  [{i}] {role:9s}: {snippet}{extra}")
