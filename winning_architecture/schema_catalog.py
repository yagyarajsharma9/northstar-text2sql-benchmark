"""
Schema-RAG catalog.

Hand-curated table descriptions + column hints. The retriever scores
each table against the user question using a tiny TF/keyword overlap
heuristic and returns the top-K plus their FK relations. This is fast,
deterministic, and avoids needing an embedding service for the demo.

Once Anthropic API key is provided, this catalog can be drop-in
replaced with vector embeddings (Voyage / OpenAI / Cohere) — but the
heuristic alone scores well on this 51-table schema.
"""
from __future__ import annotations
import re
from collections import Counter

TABLES: dict[str, dict] = {
    # ---- AUTH / RBAC ----
    "users": {
        "desc": "Employee user accounts. Login info, names, emails, status.",
        "cols": "user_id username email first_name last_name employee_code is_active is_locked failed_login_count last_login_at mfa_enabled",
    },
    "roles": {
        "desc": "Named roles like ADMIN, CFO, FINANCE_MGR, DRILLING_ENG.",
        "cols": "role_id role_code role_name description is_system",
    },
    "permissions": {
        "desc": "Granular permission codes (e.g. invoices:approve).",
        "cols": "permission_id permission_code resource action",
    },
    "role_permissions": {"desc": "Maps roles to permissions.", "cols": "role_id permission_id"},
    "user_roles": {"desc": "Maps users to roles.", "cols": "user_id role_id granted_by granted_at"},
    "user_sessions": {"desc": "Login sessions issued to users.", "cols": "session_id user_id ip_address issued_at expires_at revoked_at"},
    "login_audit": {
        "desc": "Authentication event log: login_success, login_fail, logout, lockout, password_reset.",
        "cols": "audit_id user_id username event_type ip_address occurred_at detail",
    },
    "mfa_devices": {"desc": "MFA / TOTP devices per user.", "cols": "device_id user_id device_type label is_primary"},

    # ---- ORG ----
    "departments": {"desc": "Organisational departments and hierarchy.", "cols": "department_id dept_code dept_name parent_dept_id location"},
    "employees": {"desc": "Employee records linked to user accounts. Hire date, manager chain, job title, salary band.",
                  "cols": "employee_id user_id department_id manager_id job_title employment_type hire_date work_location"},
    "delegations": {"desc": "Delegation of authority / approval rights.",
                    "cols": "delegation_id delegator_id delegate_id scope reason starts_at ends_at is_active"},

    # ---- APPROVAL CHAIN ----
    "approval_workflows": {"desc": "Defines approval chains for invoices, POs, contracts, drilling AFE, permits.",
                           "cols": "workflow_id workflow_code workflow_name entity_type min_amount max_amount"},
    "approval_steps": {"desc": "Steps within an approval workflow. Role required, SLA hours.",
                       "cols": "step_id workflow_id step_order step_name role_required user_required sla_hours"},
    "approval_requests": {
        "desc": "Approval request instances. Has creator_id, validator_id, final_approver_id, status (Submitted/InReview/Approved/Rejected/Cancelled), amount.",
        "cols": "request_id workflow_id entity_type entity_id title amount creator_id validator_id final_approver_id status submitted_at completed_at due_at",
    },
    "approval_actions": {"desc": "Each Submit/Approve/Reject/Validate action taken on a request.",
                         "cols": "action_id request_id step_id actor_id action comment occurred_at"},

    # ---- COUNTERPARTIES ----
    "customers": {"desc": "Real customers (Phillips 66, Shell Trading, Reliance, etc).",
                  "cols": "customer_id customer_code legal_name country region credit_rating credit_limit relationship_manager_id is_active"},
    "customer_contacts": {"desc": "Contacts at customer companies.", "cols": "contact_id customer_id first_name last_name title email phone is_primary"},
    "vendors": {"desc": "Service / equipment vendors (Halliburton, Schlumberger, etc).",
                "cols": "vendor_id vendor_code legal_name category country rating is_preferred is_active payment_terms"},
    "contracts": {"desc": "Master sales/services contracts with customers or vendors.",
                  "cols": "contract_id contract_number counterparty_type customer_id vendor_id contract_type title total_value start_date end_date status"},

    # ---- UPSTREAM ----
    "fields": {"desc": "Oil/gas fields (Eagle Ford, Bakken, Mars, Brent, Ghawar, Athabasca).",
               "cols": "field_id field_code field_name basin country region onshore_offshore api_gravity estimated_reserves_mmboe is_producing"},
    "reservoirs": {"desc": "Reservoir/formation properties per field.",
                   "cols": "reservoir_id field_id reservoir_name formation depth_m pressure_psi temperature_c porosity_pct permeability_md api_gravity"},
    "wells": {"desc": "Wells. Type (Producer/Injector/Exploration), status (Producing/ShutIn/Suspended/Drilling), depth, location.",
              "cols": "well_id field_id reservoir_id well_code well_name well_type well_status spud_date completion_date total_depth_m latitude longitude operator_user_id"},
    "well_completions": {"desc": "Completion details (perforation, casing) and cost.",
                         "cols": "completion_id well_id completion_date completion_type contractor_vendor_id casing_size_in tubing_size_in cost_usd"},
    "well_tests": {"desc": "Well test results: flow rate, GOR, water cut, BHP.",
                   "cols": "test_id well_id test_date test_type duration_hours flow_rate_bopd gas_rate_mscfd water_cut_pct bhp_psi"},
    "drilling_rigs": {"desc": "Drilling rigs (Land/Jackup/Semisubmersible/Drillship).",
                      "cols": "rig_id rig_code rig_name rig_type contractor_vendor_id horsepower max_depth_m day_rate_usd is_active"},
    "drilling_operations": {"desc": "Drilling operation campaigns. AFE amount vs actual cost.",
                            "cols": "operation_id well_id rig_id start_date end_date planned_days actual_days afe_amount actual_cost"},
    "daily_production": {
        "desc": "Daily production by well: oil_bbl, gas_mscf, water_bbl. Has reporter, validator. Validated flag.",
        "cols": "production_id well_id production_date oil_bbl gas_mscf water_bbl runtime_hours choke_size_64ths tubing_pressure_psi reported_by_user_id validated_by_user_id is_validated",
    },

    # ---- MIDSTREAM / DOWNSTREAM ----
    "pipelines": {"desc": "Crude/Gas/NGL/Refined pipelines.",
                  "cols": "pipeline_id pipeline_code pipeline_name product diameter_in length_km capacity_bbld origin destination"},
    "pipeline_segments": {"desc": "Pipeline segments with integrity status.",
                          "cols": "segment_id pipeline_id segment_number start_km end_km material wall_thickness_mm last_inspection_date integrity_status"},
    "storage_tanks": {"desc": "Storage tank inventory.", "cols": "tank_id tank_code location product capacity_bbl current_volume_bbl status"},
    "refineries": {"desc": "Refineries and capacities.", "cols": "refinery_id refinery_code refinery_name location capacity_bpd nelson_complexity"},
    "products": {"desc": "Product catalog: WTI, Brent, NG, NGL, RBOB, ULSD, JetA, LPG.", "cols": "product_id product_code product_name category unit_of_measure"},
    "crude_assays": {"desc": "Crude oil assays (API, sulfur, TAN, salt).",
                     "cols": "assay_id field_id sample_date api_gravity sulfur_pct pour_point_c viscosity_cst tan_mgkoh_g salt_ptb"},
    "shipments": {"desc": "Sales shipments to customers (vessel, BL date, ETA, port, volume, price).",
                  "cols": "shipment_id shipment_number contract_id customer_id product_id volume_bbl price_per_bbl total_value load_port discharge_port vessel_name bl_date eta status"},

    # ---- EQUIPMENT / MAINTENANCE ----
    "equipment": {"desc": "Equipment items: pumps, compressors, separators, generators.",
                  "cols": "equipment_id equipment_tag equipment_type manufacturer model install_date location_well_id criticality status"},
    "work_orders": {"desc": "Maintenance work orders (Preventive/Corrective/Emergency).",
                    "cols": "wo_id wo_number equipment_id well_id wo_type priority description requested_by_user_id assigned_to_user_id vendor_id status requested_at completed_at estimated_cost actual_cost"},
    "inspections": {"desc": "Equipment / pipeline inspections with finding severity.",
                    "cols": "inspection_id equipment_id pipeline_segment_id inspection_date inspection_type inspector_user_id finding_summary finding_severity"},

    # ---- HSE ----
    "incidents": {"desc": "HSE incidents: NearMiss, FirstAid, MTC, LTI, Fatality, Spill, Fire, GasRelease. Severity SIF1-SIF5.",
                  "cols": "incident_id incident_number occurred_at location well_id incident_type severity description reported_by_user_id investigated_by_user_id root_cause closed_at cost_estimate"},
    "environmental_readings": {"desc": "Environmental sensor readings (CO2, CH4, SO2, H2S, NOx, PM2.5, VOC). Has exceedance flag.",
                               "cols": "reading_id location well_id reading_date parameter value unit threshold is_exceedance sensor_tag"},

    # ---- FINANCE ----
    "cost_centers": {"desc": "Cost centers tied to departments / fields.", "cols": "cost_center_id cc_code cc_name department_id field_id"},
    "exchange_rates": {"desc": "Daily FX rates (USD to EUR/GBP/CAD/JPY/etc).", "cols": "rate_id from_currency to_currency rate_date rate"},
    "invoices": {
        "desc": "AR/AP invoices. Status: Draft/Submitted/Approved/Paid/PartiallyPaid/Overdue/Disputed.",
        "cols": "invoice_id invoice_number invoice_type customer_id vendor_id contract_id cost_center_id invoice_date due_date subtotal tax_amount total_amount currency_code status created_by_user_id approved_by_user_id approval_request_id",
    },
    "invoice_items": {"desc": "Invoice line items.", "cols": "item_id invoice_id line_number description product_id quantity unit_price line_total well_id"},
    "payments": {"desc": "Payments against invoices.",
                 "cols": "payment_id invoice_id payment_date amount currency_code payment_method reference"},
    "purchase_orders": {"desc": "Purchase orders to vendors. Approval workflow.",
                        "cols": "po_id po_number vendor_id cost_center_id requested_by_user_id approved_by_user_id approval_request_id issue_date expected_date total_amount status"},
    "po_items": {"desc": "PO line items with received quantities.",
                 "cols": "po_item_id po_id line_number description product_id quantity unit_price line_total received_qty"},

    # ---- COMPLIANCE / DOCS / AUDIT ----
    "permits": {"desc": "Regulatory permits (Drilling/Environmental/Pipeline/Construction/Operating).",
                "cols": "permit_id permit_number permit_type issuing_authority well_id field_id issued_date expiry_date status fee_paid"},
    "external_links": {"desc": "Pointers to external systems (SCADA, ERP, SharePoint, S3, LIMS, GIS, CRM, CMMS).",
                       "cols": "link_id entity_type entity_id link_type system_name url external_id last_synced_at"},
    "document_references": {"desc": "Catalog of documents (PDFs, reports). Has storage_uri (S3/SharePoint/file).",
                            "cols": "document_id entity_type entity_id document_name document_type storage_uri uploaded_by_user_id uploaded_at is_confidential"},
    "document_extracts": {"desc": "Extracted text content from policy/SOP/contract/report files.",
                          "cols": "extract_id document_id source_path file_name document_category related_entity_type word_count summary keywords"},
    "document_chunks": {"desc": "Chunked text for RAG. Joined with FTS5 (document_chunks_fts) for keyword search.",
                        "cols": "chunk_id extract_id chunk_index chunk_text char_start char_end token_estimate"},
    "audit_log": {"desc": "Generic audit log of CRUD/approve actions per user.",
                  "cols": "audit_id actor_user_id entity_type entity_id action old_value new_value occurred_at"},
    "notifications": {"desc": "User notifications (Email/SMS/Push/InApp).",
                      "cols": "notification_id recipient_user_id channel subject body related_entity_type related_entity_id is_read sent_at read_at"},
}


# Foreign-key relationships used to expand context when a top table is selected.
RELATIONS: dict[str, list[str]] = {
    "wells":               ["fields", "reservoirs", "daily_production", "well_tests", "well_completions", "drilling_operations"],
    "daily_production":    ["wells", "users"],
    "invoices":            ["customers", "vendors", "contracts", "invoice_items", "payments", "approval_requests", "cost_centers"],
    "purchase_orders":     ["vendors", "po_items", "approval_requests", "cost_centers"],
    "approval_requests":   ["approval_workflows", "approval_steps", "approval_actions", "users"],
    "approval_actions":    ["approval_requests", "users"],
    "incidents":           ["wells", "users"],
    "shipments":           ["customers", "contracts", "products"],
    "users":               ["user_roles", "roles", "employees"],
    "employees":           ["users", "departments"],
    "contracts":           ["customers", "vendors"],
    "permits":             ["wells", "fields"],
    "drilling_operations": ["wells", "drilling_rigs"],
    "work_orders":         ["equipment", "wells", "vendors", "users"],
    "inspections":         ["equipment", "pipeline_segments", "users"],
    "pipeline_segments":   ["pipelines"],
    "environmental_readings":["wells"],
}


_TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9_]{2,}")
_STOP = {"the","of","and","to","in","a","is","for","on","by","with","this","that",
         "be","as","at","or","an","are","from","it","not","show","list","find","what",
         "which","who","how","many","much","tell","give","total","sum","count","each",
         "all","over","last","year","month","day","days","please","get","me"}


def _tokens(text: str) -> list[str]:
    return [t.lower() for t in _TOKEN_RE.findall(text) if t.lower() not in _STOP]


def retrieve_tables(question: str, top_k: int = 6) -> list[str]:
    """Return top-K table names most relevant to the question."""
    qtokens = Counter(_tokens(question))
    if not qtokens:
        # default safety set
        return ["wells", "daily_production", "invoices", "approval_requests", "users", "incidents"]
    scores: dict[str, int] = {}
    for name, info in TABLES.items():
        haystack = f"{name} {info['desc']} {info['cols']}".lower()
        toks = Counter(_TOKEN_RE.findall(haystack))
        score = sum(min(qtokens[t], toks[t]) for t in qtokens if t in toks)
        # boost on direct table-name match
        if name.lower() in question.lower():
            score += 5
        scores[name] = score
    ranked = [n for n, s in sorted(scores.items(), key=lambda x: x[1], reverse=True) if s > 0]
    selected = ranked[:top_k]
    # expand with related tables
    expanded = list(selected)
    for t in selected:
        for rel in RELATIONS.get(t, []):
            if rel not in expanded:
                expanded.append(rel)
        if len(expanded) >= top_k * 2:
            break
    return expanded[: top_k * 2]


def render_schema_block(table_names: list[str]) -> str:
    """Render the chosen tables as a compact spec the SQL agent can read."""
    lines = ["# RELEVANT TABLES (subset of full 51-table schema)"]
    for t in table_names:
        info = TABLES.get(t)
        if not info:
            continue
        lines.append(f"\n## {t}")
        lines.append(f"  -- {info['desc']}")
        lines.append(f"  columns: {info['cols']}")
        if t in RELATIONS:
            lines.append(f"  joins:   {', '.join(RELATIONS[t])}")
    return "\n".join(lines)
