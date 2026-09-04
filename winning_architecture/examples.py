"""
Example bank for few-shot NL2SQL  (Vanna.ai-style).

Hand-curated NL/SQL pairs covering the high-value oil & gas query patterns.
A simple keyword overlap retriever picks 2-3 closest examples to inject
into the SQL generator's prompt.
"""
from __future__ import annotations
import re
from collections import Counter

EXAMPLES: list[dict] = [
    {
        "q": "How many wells do we have producing in the Permian Eagle Ford field?",
        "sql": """
SELECT f.field_name, COUNT(w.well_id) AS producing_wells
FROM wells w
JOIN fields f ON f.field_id = w.field_id
WHERE w.well_status = 'Producing' AND f.field_code = 'PERM-EAG'
GROUP BY f.field_name;
""".strip(),
    },
    {
        "q": "Top 5 wells by total oil production in 2025",
        "sql": """
SELECT w.well_code, w.well_name, ROUND(SUM(p.oil_bbl), 1) AS total_oil_bbl
FROM daily_production p
JOIN wells w ON w.well_id = p.well_id
WHERE p.production_date BETWEEN '2025-01-01' AND '2025-12-31'
GROUP BY w.well_id
ORDER BY total_oil_bbl DESC
LIMIT 5;
""".strip(),
    },
    {
        "q": "Average daily oil production per field for the last 90 days",
        "sql": """
SELECT f.field_name,
       ROUND(AVG(p.oil_bbl), 1) AS avg_daily_oil_bbl,
       COUNT(DISTINCT w.well_id) AS active_wells
FROM daily_production p
JOIN wells w ON w.well_id = p.well_id
JOIN fields f ON f.field_id = w.field_id
WHERE p.production_date >= date('now','-90 days')
GROUP BY f.field_id
ORDER BY avg_daily_oil_bbl DESC;
""".strip(),
    },
    {
        "q": "Which invoices are overdue and over 100k USD?",
        "sql": """
SELECT i.invoice_number, i.invoice_type,
       COALESCE(c.legal_name, v.legal_name) AS counterparty,
       i.total_amount, i.due_date, i.status
FROM invoices i
LEFT JOIN customers c ON c.customer_id = i.customer_id
LEFT JOIN vendors   v ON v.vendor_id   = i.vendor_id
WHERE i.status = 'Overdue' AND i.total_amount > 100000
ORDER BY i.total_amount DESC;
""".strip(),
    },
    {
        "q": "Show pending approval requests over 250k USD with the creator and approver",
        "sql": """
SELECT ar.request_id, ar.title, ar.amount, ar.status,
       cu.username AS creator,
       fa.username AS final_approver,
       ar.submitted_at
FROM approval_requests ar
JOIN users cu ON cu.user_id = ar.creator_id
LEFT JOIN users fa ON fa.user_id = ar.final_approver_id
WHERE ar.status IN ('Submitted','InReview') AND ar.amount > 250000
ORDER BY ar.submitted_at;
""".strip(),
    },
    {
        "q": "Who approved invoice INV-2024-000123?",
        "sql": """
SELECT i.invoice_number, u.username AS approved_by, i.approved_by_user_id,
       i.status, i.total_amount, ar.status AS approval_status
FROM invoices i
LEFT JOIN users u ON u.user_id = i.approved_by_user_id
LEFT JOIN approval_requests ar ON ar.request_id = i.approval_request_id
WHERE i.invoice_number = 'INV-2024-000123';
""".strip(),
    },
    {
        "q": "Failed login attempts in the last 30 days, grouped by user",
        "sql": """
SELECT la.username, COUNT(*) AS fail_count, MAX(la.occurred_at) AS last_fail
FROM login_audit la
WHERE la.event_type IN ('login_fail','lockout')
  AND la.occurred_at >= datetime('now','-30 days')
GROUP BY la.username
ORDER BY fail_count DESC
LIMIT 20;
""".strip(),
    },
    {
        "q": "List incidents in 2025 with severity SIF3 or higher",
        "sql": """
SELECT i.incident_number, i.occurred_at, i.incident_type, i.severity,
       i.location, w.well_code, ru.username AS reporter
FROM incidents i
LEFT JOIN wells w ON w.well_id = i.well_id
LEFT JOIN users ru ON ru.user_id = i.reported_by_user_id
WHERE i.severity IN ('SIF3','SIF4','SIF5')
  AND i.occurred_at BETWEEN '2025-01-01' AND '2025-12-31'
ORDER BY i.occurred_at DESC;
""".strip(),
    },
    {
        "q": "Total purchase orders by vendor category in 2025",
        "sql": """
SELECT v.category, COUNT(*) AS po_count, ROUND(SUM(po.total_amount), 0) AS total_usd
FROM purchase_orders po
JOIN vendors v ON v.vendor_id = po.vendor_id
WHERE po.issue_date BETWEEN '2025-01-01' AND '2025-12-31'
GROUP BY v.category
ORDER BY total_usd DESC;
""".strip(),
    },
    {
        "q": "Which pipeline segments have integrity status of Repair or worse?",
        "sql": """
SELECT p.pipeline_code, p.pipeline_name, ps.segment_number, ps.start_km, ps.end_km,
       ps.integrity_status, ps.last_inspection_date
FROM pipeline_segments ps
JOIN pipelines p ON p.pipeline_id = ps.pipeline_id
WHERE ps.integrity_status IN ('Repair','Replaced')
ORDER BY p.pipeline_code, ps.segment_number;
""".strip(),
    },
    {
        "q": "How many environmental exceedances of methane (CH4) in Q4 2025?",
        "sql": """
SELECT COUNT(*) AS exceedance_count, MIN(reading_date) AS first_event, MAX(reading_date) AS last_event
FROM environmental_readings
WHERE parameter = 'CH4' AND is_exceedance = 1
  AND reading_date BETWEEN '2025-10-01' AND '2025-12-31';
""".strip(),
    },
    {
        "q": "AFE versus actual cost for drilling operations in 2025, with variance",
        "sql": """
SELECT do.operation_id, w.well_code,
       do.afe_amount, do.actual_cost,
       ROUND((do.actual_cost - do.afe_amount) * 100.0 / do.afe_amount, 1) AS variance_pct
FROM drilling_operations do
JOIN wells w ON w.well_id = do.well_id
WHERE do.start_date BETWEEN '2025-01-01' AND '2025-12-31'
ORDER BY variance_pct DESC;
""".strip(),
    },
    {
        "q": "Top 10 customers by total shipment value this year",
        "sql": """
SELECT c.legal_name, COUNT(s.shipment_id) AS shipments,
       ROUND(SUM(s.total_value), 0) AS total_revenue_usd
FROM shipments s
JOIN customers c ON c.customer_id = s.customer_id
WHERE s.bl_date >= date('now','start of year')
GROUP BY c.customer_id
ORDER BY total_revenue_usd DESC
LIMIT 10;
""".strip(),
    },
    {
        "q": "List active permits expiring in the next 60 days",
        "sql": """
SELECT permit_number, permit_type, issuing_authority, expiry_date, status
FROM permits
WHERE status = 'Active'
  AND expiry_date BETWEEN date('now') AND date('now','+60 days')
ORDER BY expiry_date;
""".strip(),
    },
    {
        "q": "Open work orders by priority for the operations team",
        "sql": """
SELECT priority, COUNT(*) AS open_count
FROM work_orders
WHERE status IN ('Open','InProgress','OnHold')
GROUP BY priority
ORDER BY CASE priority WHEN 'Critical' THEN 1 WHEN 'High' THEN 2 WHEN 'Medium' THEN 3 ELSE 4 END;
""".strip(),
    },
    {
        "q": "Approval action history for the largest invoice last quarter",
        "sql": """
WITH biggest AS (
  SELECT i.invoice_id, i.invoice_number, i.total_amount, i.approval_request_id
  FROM invoices i
  WHERE i.invoice_date >= date('now','-90 days')
  ORDER BY i.total_amount DESC
  LIMIT 1
)
SELECT b.invoice_number, b.total_amount, aa.action, u.username AS actor, aa.comment, aa.occurred_at
FROM biggest b
JOIN approval_actions aa ON aa.request_id = b.approval_request_id
JOIN users u ON u.user_id = aa.actor_id
ORDER BY aa.occurred_at;
""".strip(),
    },
]


_TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9_]{2,}")
_STOP = {"the","of","and","to","in","a","is","for","on","by","with","this","that",
         "be","as","at","or","an","are","from","it","not","show","list","find","what",
         "which","who","how","many","much","tell","give","total","sum","count","each",
         "all","over","last","year","month","please","get","me"}


def retrieve_examples(question: str, top_k: int = 3) -> list[dict]:
    qtok = Counter(t.lower() for t in _TOKEN_RE.findall(question) if t.lower() not in _STOP)
    if not qtok:
        return EXAMPLES[:top_k]
    scored = []
    for ex in EXAMPLES:
        etok = Counter(t.lower() for t in _TOKEN_RE.findall(ex["q"]) if t.lower() not in _STOP)
        score = sum(min(qtok[t], etok[t]) for t in qtok if t in etok)
        scored.append((score, ex))
    scored.sort(key=lambda x: x[0], reverse=True)
    return [ex for s, ex in scored[:top_k] if s > 0] or EXAMPLES[:top_k]


def render_examples_block(exs: list[dict]) -> str:
    if not exs:
        return ""
    parts = ["# FEW-SHOT EXAMPLES (similar questions)"]
    for i, ex in enumerate(exs, 1):
        parts.append(f"\nExample {i}:")
        parts.append(f"Q: {ex['q']}")
        parts.append(f"SQL:\n{ex['sql']}")
    return "\n".join(parts)
