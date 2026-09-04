"""Verify the fabricated-column detector catches the case it's meant to."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from winning_architecture import sql_validation

CASES = [
    # (question, sql, expect_caught)
    ("Show me the carbon_offset_credits balance for each well.",
     "SELECT w.well_id, w.well_code, 0 AS carbon_offset_credits FROM wells w LIMIT 200",
     True),
    ("List ESG scope-3 emissions per refinery.",
     "SELECT r.refinery_code, 0 AS scope_3_emissions FROM refineries r",
     True),
    # Real query that should NOT trigger
    ("How many wells are producing in Eagle Ford?",
     "SELECT COUNT(w.well_id) AS producing_wells FROM wells w "
     "JOIN fields f ON f.field_id = w.field_id WHERE w.well_status='Producing' AND f.field_code='PERM-EAG'",
     False),
    # Real aggregate aliasing - must NOT trigger
    ("Total invoice amount in 2025",
     "SELECT SUM(total_amount) AS total_invoice FROM invoices WHERE invoice_date BETWEEN '2025-01-01' AND '2025-12-31'",
     False),
    # Counted result with literal 0 fallback - real case (no fabrication)
    ("How many wells are in the Brent field?",
     "SELECT COUNT(*) AS well_count FROM wells w JOIN fields f ON f.field_id=w.field_id WHERE f.field_code='NS-BRENT'",
     False),
]

ok = 0
for q, sql, expected in CASES:
    reason = sql_validation.detect_fabricated_metric(q, sql)
    caught = reason is not None
    pass_ = caught == expected
    mark = "OK" if pass_ else "FAIL"
    print(f"[{mark}] expected_caught={expected}  caught={caught}")
    print(f"    Q: {q}")
    if reason:
        print(f"    REASON: {reason}")
    print()
    ok += pass_
print(f"{ok}/{len(CASES)} unit cases passed")
