"""Execute every gold SQL against the database, capture the gold result set and the tables the
query reads, and save it. Also verifies that every gold_sql runs. Run: python benchmark/build_gold.py
"""
import sqlite3, json, re
from pathlib import Path
from gold_questions import GOLD

DB = str(Path(__file__).resolve().parent.parent / "database" / "oilgas.db")
OUT = Path(__file__).resolve().parent / "gold_resultsets.json"

TABLE_RE = re.compile(r"\b(?:from|join)\s+([a-zA-Z_][a-zA-Z0-9_]*)", re.IGNORECASE)


def tables_in(sql):
    if not sql:
        return []
    return sorted(set(m.lower() for m in TABLE_RE.findall(sql)))


def run(sql):
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    cur = con.execute(sql)
    cols = [d[0] for d in cur.description] if cur.description else []
    rows = [dict(r) for r in cur.fetchall()]
    con.close()
    return cols, rows


def main():
    out = {}
    errors = []
    for q in GOLD:
        rec = {"id": q["id"], "category": q["category"], "role": q["role"],
               "expects": q["expects"], "tables": tables_in(q.get("gold_sql"))}
        if q.get("gold_sql"):
            try:
                cols, rows = run(q["gold_sql"])
                rec["gold_columns"] = cols
                rec["gold_rowcount"] = len(rows)
                rec["gold_rows"] = rows   # full result set, so exact-match scoring is correct
            except Exception as e:
                errors.append((q["id"], str(e)))
                rec["error"] = str(e)
        out[q["id"]] = rec
    OUT.write_text(json.dumps(out, indent=1, default=str))

    ok = sum(1 for q in GOLD if q.get("gold_sql") and "error" not in out[q["id"]])
    refuse = sum(1 for q in GOLD if q["expects"] == "refuse")
    print(f"gold questions: {len(GOLD)}  (answerable ok: {ok}, refuse: {refuse})")
    if errors:
        print("SQL ERRORS:")
        for i, e in errors:
            print(f"  {i}: {e}")
    else:
        print("all gold SQL executed cleanly.")
    # show a few gold rowcounts
    for q in GOLD:
        if q.get("gold_sql"):
            r = out[q["id"]]
            print(f"  {q['id']:5} {q['category']:16} rows={r.get('gold_rowcount','ERR'):>4}  tables={r['tables']}")
    print("wrote", OUT.name)


if __name__ == "__main__":
    main()
