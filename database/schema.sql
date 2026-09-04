-- =====================================================================
-- NorthStar Petroleum Corp.  -- Enterprise SQLite schema
-- Hackathon build : 8-team collaboration
-- 51 tables : Auth + RBAC + Approval Chains + Upstream/Midstream/Downstream
--             + HSE + Finance + Compliance + External Integrations + Audit
-- =====================================================================

PRAGMA foreign_keys = ON;
PRAGMA journal_mode = WAL;

-- ---------------------------------------------------------------------
-- Section 1 : IDENTITY, AUTH & RBAC
-- ---------------------------------------------------------------------

CREATE TABLE users (
    user_id              INTEGER PRIMARY KEY AUTOINCREMENT,
    username             TEXT NOT NULL UNIQUE,
    email                TEXT NOT NULL UNIQUE,
    password_hash        TEXT NOT NULL,                    -- bcrypt
    password_salt        TEXT NOT NULL,
    first_name           TEXT NOT NULL,
    last_name            TEXT NOT NULL,
    phone                TEXT,
    employee_code        TEXT UNIQUE,
    is_active            INTEGER NOT NULL DEFAULT 1,
    is_locked            INTEGER NOT NULL DEFAULT 0,
    failed_login_count   INTEGER NOT NULL DEFAULT 0,
    last_login_at        TEXT,
    password_changed_at  TEXT,
    must_change_password INTEGER NOT NULL DEFAULT 0,
    mfa_enabled          INTEGER NOT NULL DEFAULT 0,
    timezone             TEXT DEFAULT 'UTC',
    locale               TEXT DEFAULT 'en-US',
    created_at           TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at           TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX ix_users_email ON users(email);
CREATE INDEX ix_users_active ON users(is_active);

CREATE TABLE roles (
    role_id      INTEGER PRIMARY KEY AUTOINCREMENT,
    role_code    TEXT NOT NULL UNIQUE,
    role_name    TEXT NOT NULL,
    description  TEXT,
    is_system    INTEGER NOT NULL DEFAULT 0,
    created_at   TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE permissions (
    permission_id   INTEGER PRIMARY KEY AUTOINCREMENT,
    permission_code TEXT NOT NULL UNIQUE,
    resource        TEXT NOT NULL,        -- e.g. 'invoices', 'wells'
    action          TEXT NOT NULL,        -- e.g. 'create','read','update','delete','approve'
    description     TEXT
);

CREATE TABLE role_permissions (
    role_id        INTEGER NOT NULL REFERENCES roles(role_id) ON DELETE CASCADE,
    permission_id  INTEGER NOT NULL REFERENCES permissions(permission_id) ON DELETE CASCADE,
    granted_at     TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (role_id, permission_id)
);

CREATE TABLE user_roles (
    user_id     INTEGER NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    role_id     INTEGER NOT NULL REFERENCES roles(role_id) ON DELETE CASCADE,
    granted_by  INTEGER REFERENCES users(user_id),
    granted_at  TEXT NOT NULL DEFAULT (datetime('now')),
    expires_at  TEXT,
    PRIMARY KEY (user_id, role_id)
);

CREATE TABLE user_sessions (
    session_id      TEXT PRIMARY KEY,                -- uuid
    user_id         INTEGER NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    ip_address      TEXT,
    user_agent      TEXT,
    issued_at       TEXT NOT NULL DEFAULT (datetime('now')),
    expires_at      TEXT NOT NULL,
    revoked_at      TEXT,
    last_seen_at    TEXT
);
CREATE INDEX ix_sessions_user ON user_sessions(user_id);

CREATE TABLE login_audit (
    audit_id     INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id      INTEGER REFERENCES users(user_id),
    username     TEXT,                                  -- recorded even if user not found
    ip_address   TEXT,
    user_agent   TEXT,
    event_type   TEXT NOT NULL CHECK(event_type IN ('login_success','login_fail','logout','mfa_challenge','mfa_fail','password_reset','lockout')),
    detail       TEXT,
    occurred_at  TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX ix_login_audit_user ON login_audit(user_id);
CREATE INDEX ix_login_audit_time ON login_audit(occurred_at);

CREATE TABLE mfa_devices (
    device_id     INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id       INTEGER NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    device_type   TEXT NOT NULL CHECK(device_type IN ('totp','sms','email','webauthn')),
    secret        TEXT,                                  -- encrypted
    label         TEXT,
    is_primary    INTEGER NOT NULL DEFAULT 0,
    verified_at   TEXT,
    created_at    TEXT NOT NULL DEFAULT (datetime('now'))
);

-- ---------------------------------------------------------------------
-- Section 2 : ORG STRUCTURE
-- ---------------------------------------------------------------------

CREATE TABLE departments (
    department_id     INTEGER PRIMARY KEY AUTOINCREMENT,
    dept_code         TEXT NOT NULL UNIQUE,
    dept_name         TEXT NOT NULL,
    parent_dept_id    INTEGER REFERENCES departments(department_id),
    cost_center_code  TEXT,
    head_user_id      INTEGER REFERENCES users(user_id),
    location          TEXT,
    created_at        TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE employees (
    employee_id      INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id          INTEGER UNIQUE REFERENCES users(user_id),
    department_id    INTEGER REFERENCES departments(department_id),
    manager_id       INTEGER REFERENCES employees(employee_id),
    job_title        TEXT NOT NULL,
    job_grade        TEXT,
    employment_type  TEXT CHECK(employment_type IN ('FullTime','Contractor','Consultant','Intern')),
    hire_date        TEXT NOT NULL,
    termination_date TEXT,
    salary_band      TEXT,
    work_location    TEXT,
    badge_number     TEXT UNIQUE,
    emergency_contact TEXT,
    created_at       TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX ix_employees_dept ON employees(department_id);
CREATE INDEX ix_employees_mgr ON employees(manager_id);

-- ---------------------------------------------------------------------
-- Section 3 : APPROVAL CHAINS  (creator -> validator -> approver)
-- ---------------------------------------------------------------------

CREATE TABLE approval_workflows (
    workflow_id    INTEGER PRIMARY KEY AUTOINCREMENT,
    workflow_code  TEXT NOT NULL UNIQUE,
    workflow_name  TEXT NOT NULL,
    entity_type    TEXT NOT NULL,                -- 'invoice','purchase_order','well_drilling','contract','permit'
    description    TEXT,
    is_active      INTEGER NOT NULL DEFAULT 1,
    min_amount     REAL,
    max_amount     REAL,
    created_at     TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE approval_steps (
    step_id        INTEGER PRIMARY KEY AUTOINCREMENT,
    workflow_id    INTEGER NOT NULL REFERENCES approval_workflows(workflow_id) ON DELETE CASCADE,
    step_order     INTEGER NOT NULL,
    step_name      TEXT NOT NULL,
    role_required  INTEGER REFERENCES roles(role_id),
    user_required  INTEGER REFERENCES users(user_id),
    department_id  INTEGER REFERENCES departments(department_id),
    sla_hours      INTEGER DEFAULT 48,
    is_parallel    INTEGER NOT NULL DEFAULT 0,
    is_optional    INTEGER NOT NULL DEFAULT 0,
    UNIQUE(workflow_id, step_order)
);

CREATE TABLE approval_requests (
    request_id      INTEGER PRIMARY KEY AUTOINCREMENT,
    workflow_id     INTEGER NOT NULL REFERENCES approval_workflows(workflow_id),
    entity_type     TEXT NOT NULL,
    entity_id       INTEGER NOT NULL,
    title           TEXT NOT NULL,
    description     TEXT,
    amount          REAL,
    currency_code   TEXT DEFAULT 'USD',
    creator_id      INTEGER NOT NULL REFERENCES users(user_id),
    validator_id    INTEGER REFERENCES users(user_id),    -- secondary check
    final_approver_id INTEGER REFERENCES users(user_id),
    current_step    INTEGER DEFAULT 1,
    status          TEXT NOT NULL CHECK(status IN ('Draft','Submitted','InReview','Approved','Rejected','Cancelled','Expired')),
    submitted_at    TEXT,
    completed_at    TEXT,
    due_at          TEXT,
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at      TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX ix_approval_status ON approval_requests(status);
CREATE INDEX ix_approval_creator ON approval_requests(creator_id);

CREATE TABLE approval_actions (
    action_id      INTEGER PRIMARY KEY AUTOINCREMENT,
    request_id     INTEGER NOT NULL REFERENCES approval_requests(request_id) ON DELETE CASCADE,
    step_id        INTEGER REFERENCES approval_steps(step_id),
    actor_id       INTEGER NOT NULL REFERENCES users(user_id),
    delegated_from INTEGER REFERENCES users(user_id),
    action         TEXT NOT NULL CHECK(action IN ('Submit','Approve','Reject','RequestInfo','Validate','Cancel','Reassign')),
    comment        TEXT,
    occurred_at    TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX ix_actions_request ON approval_actions(request_id);

CREATE TABLE delegations (
    delegation_id INTEGER PRIMARY KEY AUTOINCREMENT,
    delegator_id  INTEGER NOT NULL REFERENCES users(user_id),
    delegate_id   INTEGER NOT NULL REFERENCES users(user_id),
    scope         TEXT NOT NULL,    -- 'all','approvals','signing'
    reason        TEXT,
    starts_at     TEXT NOT NULL,
    ends_at       TEXT NOT NULL,
    is_active     INTEGER NOT NULL DEFAULT 1,
    created_at    TEXT NOT NULL DEFAULT (datetime('now'))
);

-- ---------------------------------------------------------------------
-- Section 4 : EXTERNAL PARTIES (Customers, Vendors, Contracts)
-- ---------------------------------------------------------------------

CREATE TABLE customers (
    customer_id    INTEGER PRIMARY KEY AUTOINCREMENT,
    customer_code  TEXT NOT NULL UNIQUE,
    legal_name     TEXT NOT NULL,
    trading_name   TEXT,
    industry       TEXT,
    country        TEXT,
    region         TEXT,
    city           TEXT,
    address_line1  TEXT,
    address_line2  TEXT,
    postal_code    TEXT,
    tax_id         TEXT,
    duns_number    TEXT,
    credit_rating  TEXT,
    credit_limit   REAL,
    payment_terms  TEXT,
    currency_code  TEXT DEFAULT 'USD',
    relationship_manager_id INTEGER REFERENCES users(user_id),
    is_active      INTEGER NOT NULL DEFAULT 1,
    onboarded_at   TEXT NOT NULL DEFAULT (datetime('now')),
    notes          TEXT
);

CREATE TABLE customer_contacts (
    contact_id     INTEGER PRIMARY KEY AUTOINCREMENT,
    customer_id    INTEGER NOT NULL REFERENCES customers(customer_id) ON DELETE CASCADE,
    first_name     TEXT NOT NULL,
    last_name      TEXT NOT NULL,
    title          TEXT,
    email          TEXT,
    phone          TEXT,
    is_primary     INTEGER NOT NULL DEFAULT 0,
    role_in_account TEXT,
    created_at     TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE vendors (
    vendor_id     INTEGER PRIMARY KEY AUTOINCREMENT,
    vendor_code   TEXT NOT NULL UNIQUE,
    legal_name    TEXT NOT NULL,
    category      TEXT,                           -- 'drilling_services','equipment','logistics','it','consulting'
    country       TEXT,
    tax_id        TEXT,
    bank_account  TEXT,
    swift_code    TEXT,
    payment_terms TEXT,
    currency_code TEXT DEFAULT 'USD',
    rating        REAL CHECK(rating >= 0 AND rating <= 5),
    is_preferred  INTEGER NOT NULL DEFAULT 0,
    is_active     INTEGER NOT NULL DEFAULT 1,
    onboarded_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE contracts (
    contract_id      INTEGER PRIMARY KEY AUTOINCREMENT,
    contract_number  TEXT NOT NULL UNIQUE,
    counterparty_type TEXT NOT NULL CHECK(counterparty_type IN ('Customer','Vendor')),
    customer_id      INTEGER REFERENCES customers(customer_id),
    vendor_id        INTEGER REFERENCES vendors(vendor_id),
    contract_type    TEXT,                       -- 'CrudeSale','GasSupply','DrillingServices','PipelineTransport','Lease'
    title            TEXT NOT NULL,
    total_value      REAL,
    currency_code    TEXT DEFAULT 'USD',
    start_date       TEXT NOT NULL,
    end_date         TEXT,
    status           TEXT NOT NULL CHECK(status IN ('Draft','Active','Suspended','Expired','Terminated')),
    governing_law    TEXT,
    signed_by_user_id INTEGER REFERENCES users(user_id),
    created_at       TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX ix_contracts_status ON contracts(status);

-- ---------------------------------------------------------------------
-- Section 5 : UPSTREAM (Fields, Wells, Reservoirs, Production)
-- ---------------------------------------------------------------------

CREATE TABLE fields (
    field_id       INTEGER PRIMARY KEY AUTOINCREMENT,
    field_code     TEXT NOT NULL UNIQUE,
    field_name     TEXT NOT NULL,
    basin          TEXT,
    country        TEXT,
    region         TEXT,
    onshore_offshore TEXT CHECK(onshore_offshore IN ('Onshore','Offshore')),
    discovery_date TEXT,
    operator       TEXT,
    working_interest_pct REAL,
    estimated_reserves_mmboe REAL,
    is_producing   INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE reservoirs (
    reservoir_id    INTEGER PRIMARY KEY AUTOINCREMENT,
    field_id        INTEGER NOT NULL REFERENCES fields(field_id),
    reservoir_name  TEXT NOT NULL,
    formation       TEXT,
    depth_m         REAL,
    pressure_psi    REAL,
    temperature_c   REAL,
    porosity_pct    REAL,
    permeability_md REAL,
    api_gravity     REAL,
    h2s_ppm         REAL,
    co2_pct         REAL
);

CREATE TABLE wells (
    well_id        INTEGER PRIMARY KEY AUTOINCREMENT,
    field_id       INTEGER NOT NULL REFERENCES fields(field_id),
    reservoir_id   INTEGER REFERENCES reservoirs(reservoir_id),
    well_code      TEXT NOT NULL UNIQUE,
    well_name      TEXT NOT NULL,
    well_type      TEXT CHECK(well_type IN ('Producer','Injector','Exploration','Appraisal','Disposal')),
    well_status    TEXT CHECK(well_status IN ('Drilling','Producing','ShutIn','Suspended','Abandoned','Completed')),
    spud_date      TEXT,
    completion_date TEXT,
    total_depth_m  REAL,
    latitude       REAL,
    longitude      REAL,
    operator_user_id INTEGER REFERENCES users(user_id)
);
CREATE INDEX ix_wells_field ON wells(field_id);
CREATE INDEX ix_wells_status ON wells(well_status);

CREATE TABLE well_completions (
    completion_id  INTEGER PRIMARY KEY AUTOINCREMENT,
    well_id        INTEGER NOT NULL REFERENCES wells(well_id),
    completion_date TEXT NOT NULL,
    completion_type TEXT,                        -- 'OpenHole','Cased','Perforated','Hydraulic Fractured'
    contractor_vendor_id INTEGER REFERENCES vendors(vendor_id),
    casing_size_in REAL,
    tubing_size_in REAL,
    perforation_top_m REAL,
    perforation_bottom_m REAL,
    cost_usd       REAL
);

CREATE TABLE well_tests (
    test_id        INTEGER PRIMARY KEY AUTOINCREMENT,
    well_id        INTEGER NOT NULL REFERENCES wells(well_id),
    test_date      TEXT NOT NULL,
    test_type      TEXT,                          -- 'DST','PLT','BHP','Build-up'
    duration_hours REAL,
    flow_rate_bopd REAL,
    gas_rate_mscfd REAL,
    water_cut_pct  REAL,
    bhp_psi        REAL,
    operator_user_id INTEGER REFERENCES users(user_id)
);

CREATE TABLE drilling_rigs (
    rig_id         INTEGER PRIMARY KEY AUTOINCREMENT,
    rig_code       TEXT NOT NULL UNIQUE,
    rig_name       TEXT NOT NULL,
    rig_type       TEXT,                          -- 'Land','Jackup','Semisubmersible','Drillship'
    contractor_vendor_id INTEGER REFERENCES vendors(vendor_id),
    horsepower     INTEGER,
    max_depth_m    REAL,
    day_rate_usd   REAL,
    is_active      INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE drilling_operations (
    operation_id   INTEGER PRIMARY KEY AUTOINCREMENT,
    well_id        INTEGER NOT NULL REFERENCES wells(well_id),
    rig_id         INTEGER NOT NULL REFERENCES drilling_rigs(rig_id),
    start_date     TEXT NOT NULL,
    end_date       TEXT,
    planned_days   INTEGER,
    actual_days    INTEGER,
    afe_amount     REAL,                          -- Authorisation For Expenditure
    actual_cost    REAL,
    well_supervisor_id INTEGER REFERENCES users(user_id),
    drilling_engineer_id INTEGER REFERENCES users(user_id),
    status         TEXT
);

CREATE TABLE daily_production (
    production_id  INTEGER PRIMARY KEY AUTOINCREMENT,
    well_id        INTEGER NOT NULL REFERENCES wells(well_id),
    production_date TEXT NOT NULL,
    oil_bbl        REAL DEFAULT 0,
    gas_mscf       REAL DEFAULT 0,
    water_bbl      REAL DEFAULT 0,
    runtime_hours  REAL DEFAULT 24,
    choke_size_64ths INTEGER,
    tubing_pressure_psi REAL,
    casing_pressure_psi REAL,
    reported_by_user_id INTEGER REFERENCES users(user_id),
    validated_by_user_id INTEGER REFERENCES users(user_id),
    is_validated   INTEGER NOT NULL DEFAULT 0,
    UNIQUE(well_id, production_date)
);
CREATE INDEX ix_prod_date ON daily_production(production_date);
CREATE INDEX ix_prod_well_date ON daily_production(well_id, production_date);

-- ---------------------------------------------------------------------
-- Section 6 : MIDSTREAM / DOWNSTREAM
-- ---------------------------------------------------------------------

CREATE TABLE pipelines (
    pipeline_id    INTEGER PRIMARY KEY AUTOINCREMENT,
    pipeline_code  TEXT NOT NULL UNIQUE,
    pipeline_name  TEXT NOT NULL,
    product        TEXT,                          -- 'Crude','Gas','NGL','Refined'
    diameter_in    REAL,
    length_km      REAL,
    capacity_bbld  REAL,
    origin         TEXT,
    destination    TEXT,
    operator       TEXT,
    commissioned_date TEXT
);

CREATE TABLE pipeline_segments (
    segment_id     INTEGER PRIMARY KEY AUTOINCREMENT,
    pipeline_id    INTEGER NOT NULL REFERENCES pipelines(pipeline_id),
    segment_number INTEGER NOT NULL,
    start_km       REAL,
    end_km         REAL,
    material       TEXT,
    wall_thickness_mm REAL,
    last_inspection_date TEXT,
    integrity_status TEXT CHECK(integrity_status IN ('Good','Monitoring','Repair','Replaced'))
);

CREATE TABLE storage_tanks (
    tank_id        INTEGER PRIMARY KEY AUTOINCREMENT,
    tank_code      TEXT NOT NULL UNIQUE,
    location       TEXT,
    product        TEXT,
    capacity_bbl   REAL,
    current_volume_bbl REAL,
    last_gauge_date TEXT,
    status         TEXT
);

CREATE TABLE refineries (
    refinery_id    INTEGER PRIMARY KEY AUTOINCREMENT,
    refinery_code  TEXT NOT NULL UNIQUE,
    refinery_name  TEXT NOT NULL,
    location       TEXT,
    capacity_bpd   REAL,
    nelson_complexity REAL,
    commissioned_date TEXT
);

CREATE TABLE products (
    product_id     INTEGER PRIMARY KEY AUTOINCREMENT,
    product_code   TEXT NOT NULL UNIQUE,
    product_name   TEXT NOT NULL,
    category       TEXT,                          -- 'Crude','Gas','Gasoline','Diesel','JetA','LPG','Asphalt'
    unit_of_measure TEXT,
    standard_density REAL
);

CREATE TABLE crude_assays (
    assay_id       INTEGER PRIMARY KEY AUTOINCREMENT,
    field_id       INTEGER REFERENCES fields(field_id),
    sample_date    TEXT NOT NULL,
    api_gravity    REAL,
    sulfur_pct     REAL,
    pour_point_c   REAL,
    viscosity_cst  REAL,
    tan_mgkoh_g    REAL,
    salt_ptb       REAL,
    lab_vendor_id  INTEGER REFERENCES vendors(vendor_id)
);

CREATE TABLE shipments (
    shipment_id    INTEGER PRIMARY KEY AUTOINCREMENT,
    shipment_number TEXT NOT NULL UNIQUE,
    contract_id    INTEGER REFERENCES contracts(contract_id),
    customer_id    INTEGER REFERENCES customers(customer_id),
    product_id     INTEGER REFERENCES products(product_id),
    volume_bbl     REAL,
    price_per_bbl  REAL,
    total_value    REAL,
    currency_code  TEXT DEFAULT 'USD',
    load_port      TEXT,
    discharge_port TEXT,
    vessel_name    TEXT,
    bl_date        TEXT,                          -- Bill of Lading
    eta            TEXT,
    actual_arrival TEXT,
    status         TEXT,
    created_by_user_id INTEGER REFERENCES users(user_id)
);

-- ---------------------------------------------------------------------
-- Section 7 : EQUIPMENT, MAINTENANCE, INSPECTIONS
-- ---------------------------------------------------------------------

CREATE TABLE equipment (
    equipment_id   INTEGER PRIMARY KEY AUTOINCREMENT,
    equipment_tag  TEXT NOT NULL UNIQUE,
    equipment_type TEXT,                          -- 'Pump','Compressor','Heater','Separator','Valve','Generator'
    manufacturer   TEXT,
    model          TEXT,
    serial_number  TEXT,
    install_date   TEXT,
    location_well_id INTEGER REFERENCES wells(well_id),
    location_refinery_id INTEGER REFERENCES refineries(refinery_id),
    criticality    TEXT CHECK(criticality IN ('Low','Medium','High','Critical')),
    status         TEXT,
    next_pm_date   TEXT
);

CREATE TABLE work_orders (
    wo_id          INTEGER PRIMARY KEY AUTOINCREMENT,
    wo_number      TEXT NOT NULL UNIQUE,
    equipment_id   INTEGER REFERENCES equipment(equipment_id),
    well_id        INTEGER REFERENCES wells(well_id),
    wo_type        TEXT CHECK(wo_type IN ('Preventive','Corrective','Emergency','Inspection','Project')),
    priority       TEXT CHECK(priority IN ('Low','Medium','High','Critical')),
    description    TEXT NOT NULL,
    requested_by_user_id INTEGER REFERENCES users(user_id),
    assigned_to_user_id  INTEGER REFERENCES users(user_id),
    vendor_id      INTEGER REFERENCES vendors(vendor_id),
    status         TEXT CHECK(status IN ('Open','InProgress','OnHold','Completed','Cancelled')),
    requested_at   TEXT NOT NULL DEFAULT (datetime('now')),
    started_at     TEXT,
    completed_at   TEXT,
    estimated_cost REAL,
    actual_cost    REAL
);
CREATE INDEX ix_wo_status ON work_orders(status);

CREATE TABLE inspections (
    inspection_id  INTEGER PRIMARY KEY AUTOINCREMENT,
    equipment_id   INTEGER REFERENCES equipment(equipment_id),
    pipeline_segment_id INTEGER REFERENCES pipeline_segments(segment_id),
    inspection_date TEXT NOT NULL,
    inspection_type TEXT,
    inspector_user_id INTEGER REFERENCES users(user_id),
    finding_summary TEXT,
    finding_severity TEXT CHECK(finding_severity IN ('None','Low','Medium','High','Critical')),
    next_inspection_date TEXT,
    report_external_link_id INTEGER
);

-- ---------------------------------------------------------------------
-- Section 8 : HSE (Health, Safety, Environment)
-- ---------------------------------------------------------------------

CREATE TABLE incidents (
    incident_id    INTEGER PRIMARY KEY AUTOINCREMENT,
    incident_number TEXT NOT NULL UNIQUE,
    occurred_at    TEXT NOT NULL,
    location       TEXT,
    well_id        INTEGER REFERENCES wells(well_id),
    refinery_id    INTEGER REFERENCES refineries(refinery_id),
    incident_type  TEXT CHECK(incident_type IN ('NearMiss','FirstAid','MTC','LTI','Fatality','Spill','Fire','GasRelease','Equipment')),
    severity       TEXT CHECK(severity IN ('SIF1','SIF2','SIF3','SIF4','SIF5')),
    description    TEXT,
    reported_by_user_id INTEGER REFERENCES users(user_id),
    investigated_by_user_id INTEGER REFERENCES users(user_id),
    root_cause     TEXT,
    corrective_actions TEXT,
    closed_at      TEXT,
    cost_estimate  REAL
);
CREATE INDEX ix_incidents_time ON incidents(occurred_at);

CREATE TABLE environmental_readings (
    reading_id     INTEGER PRIMARY KEY AUTOINCREMENT,
    location       TEXT NOT NULL,
    well_id        INTEGER REFERENCES wells(well_id),
    reading_date   TEXT NOT NULL,
    parameter      TEXT NOT NULL,                 -- 'CO2','CH4','SO2','H2S','NOx','PM2.5','VOC'
    value          REAL,
    unit           TEXT,
    threshold      REAL,
    is_exceedance  INTEGER NOT NULL DEFAULT 0,
    sensor_tag     TEXT,
    recorded_by_user_id INTEGER REFERENCES users(user_id)
);
CREATE INDEX ix_env_param_date ON environmental_readings(parameter, reading_date);

-- ---------------------------------------------------------------------
-- Section 9 : FINANCE
-- ---------------------------------------------------------------------

CREATE TABLE cost_centers (
    cost_center_id   INTEGER PRIMARY KEY AUTOINCREMENT,
    cc_code          TEXT NOT NULL UNIQUE,
    cc_name          TEXT NOT NULL,
    department_id    INTEGER REFERENCES departments(department_id),
    field_id         INTEGER REFERENCES fields(field_id),
    is_active        INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE exchange_rates (
    rate_id        INTEGER PRIMARY KEY AUTOINCREMENT,
    from_currency  TEXT NOT NULL,
    to_currency    TEXT NOT NULL,
    rate_date      TEXT NOT NULL,
    rate           REAL NOT NULL,
    source         TEXT,
    UNIQUE(from_currency, to_currency, rate_date)
);

CREATE TABLE invoices (
    invoice_id     INTEGER PRIMARY KEY AUTOINCREMENT,
    invoice_number TEXT NOT NULL UNIQUE,
    invoice_type   TEXT NOT NULL CHECK(invoice_type IN ('AR','AP')),
    customer_id    INTEGER REFERENCES customers(customer_id),
    vendor_id      INTEGER REFERENCES vendors(vendor_id),
    contract_id    INTEGER REFERENCES contracts(contract_id),
    cost_center_id INTEGER REFERENCES cost_centers(cost_center_id),
    invoice_date   TEXT NOT NULL,
    due_date       TEXT NOT NULL,
    subtotal       REAL NOT NULL,
    tax_amount     REAL DEFAULT 0,
    total_amount   REAL NOT NULL,
    currency_code  TEXT DEFAULT 'USD',
    status         TEXT CHECK(status IN ('Draft','Submitted','Approved','Paid','PartiallyPaid','Overdue','Disputed','Cancelled')),
    created_by_user_id INTEGER REFERENCES users(user_id),
    approved_by_user_id INTEGER REFERENCES users(user_id),
    approval_request_id INTEGER REFERENCES approval_requests(request_id),
    notes          TEXT,
    created_at     TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX ix_invoices_status ON invoices(status);
CREATE INDEX ix_invoices_date ON invoices(invoice_date);

CREATE TABLE invoice_items (
    item_id        INTEGER PRIMARY KEY AUTOINCREMENT,
    invoice_id     INTEGER NOT NULL REFERENCES invoices(invoice_id) ON DELETE CASCADE,
    line_number    INTEGER NOT NULL,
    description    TEXT NOT NULL,
    product_id     INTEGER REFERENCES products(product_id),
    quantity       REAL NOT NULL,
    unit_price     REAL NOT NULL,
    line_total     REAL NOT NULL,
    well_id        INTEGER REFERENCES wells(well_id),
    UNIQUE(invoice_id, line_number)
);

CREATE TABLE payments (
    payment_id     INTEGER PRIMARY KEY AUTOINCREMENT,
    invoice_id     INTEGER NOT NULL REFERENCES invoices(invoice_id),
    payment_date   TEXT NOT NULL,
    amount         REAL NOT NULL,
    currency_code  TEXT DEFAULT 'USD',
    payment_method TEXT,                          -- 'Wire','ACH','Check','Card'
    reference      TEXT,
    received_by_user_id INTEGER REFERENCES users(user_id)
);

CREATE TABLE purchase_orders (
    po_id           INTEGER PRIMARY KEY AUTOINCREMENT,
    po_number       TEXT NOT NULL UNIQUE,
    vendor_id       INTEGER NOT NULL REFERENCES vendors(vendor_id),
    cost_center_id  INTEGER REFERENCES cost_centers(cost_center_id),
    requested_by_user_id INTEGER REFERENCES users(user_id),
    approved_by_user_id  INTEGER REFERENCES users(user_id),
    approval_request_id  INTEGER REFERENCES approval_requests(request_id),
    issue_date      TEXT NOT NULL,
    expected_date   TEXT,
    total_amount    REAL NOT NULL,
    currency_code   TEXT DEFAULT 'USD',
    status          TEXT CHECK(status IN ('Draft','PendingApproval','Approved','Rejected','PartiallyReceived','Closed','Cancelled')),
    notes           TEXT
);

CREATE TABLE po_items (
    po_item_id     INTEGER PRIMARY KEY AUTOINCREMENT,
    po_id          INTEGER NOT NULL REFERENCES purchase_orders(po_id) ON DELETE CASCADE,
    line_number    INTEGER NOT NULL,
    description    TEXT NOT NULL,
    product_id     INTEGER REFERENCES products(product_id),
    quantity       REAL NOT NULL,
    unit_price     REAL NOT NULL,
    line_total     REAL NOT NULL,
    received_qty   REAL DEFAULT 0,
    UNIQUE(po_id, line_number)
);

-- ---------------------------------------------------------------------
-- Section 10 : COMPLIANCE / EXTERNAL / DOCUMENTS / AUDIT
-- ---------------------------------------------------------------------

CREATE TABLE permits (
    permit_id      INTEGER PRIMARY KEY AUTOINCREMENT,
    permit_number  TEXT NOT NULL UNIQUE,
    permit_type    TEXT,                          -- 'Drilling','Environmental','Pipeline','Construction','Operating'
    issuing_authority TEXT,
    well_id        INTEGER REFERENCES wells(well_id),
    field_id       INTEGER REFERENCES fields(field_id),
    issued_date    TEXT,
    expiry_date    TEXT,
    status         TEXT CHECK(status IN ('Pending','Active','Expired','Revoked')),
    holder_user_id INTEGER REFERENCES users(user_id),
    fee_paid       REAL,
    notes          TEXT
);

CREATE TABLE external_links (
    link_id        INTEGER PRIMARY KEY AUTOINCREMENT,
    entity_type    TEXT NOT NULL,                 -- 'invoice','well','contract','incident','inspection'
    entity_id      INTEGER NOT NULL,
    link_type      TEXT,                          -- 'SCADA','ERP','SharePoint','S3','LIMS','GIS'
    system_name    TEXT,
    url            TEXT,
    external_id    TEXT,
    last_synced_at TEXT,
    is_active      INTEGER NOT NULL DEFAULT 1
);
CREATE INDEX ix_extlinks_entity ON external_links(entity_type, entity_id);

CREATE TABLE document_references (
    document_id    INTEGER PRIMARY KEY AUTOINCREMENT,
    entity_type    TEXT NOT NULL,
    entity_id      INTEGER NOT NULL,
    document_name  TEXT NOT NULL,
    document_type  TEXT,                          -- 'Contract','PermitPDF','Drawing','LabReport','InspectionReport'
    storage_uri    TEXT,                          -- s3://, sharepoint://, file://
    file_size_bytes INTEGER,
    mime_type      TEXT,
    uploaded_by_user_id INTEGER REFERENCES users(user_id),
    uploaded_at    TEXT NOT NULL DEFAULT (datetime('now')),
    is_confidential INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE audit_log (
    audit_id       INTEGER PRIMARY KEY AUTOINCREMENT,
    actor_user_id  INTEGER REFERENCES users(user_id),
    entity_type    TEXT NOT NULL,
    entity_id      INTEGER,
    action         TEXT NOT NULL,
    old_value      TEXT,
    new_value      TEXT,
    ip_address     TEXT,
    occurred_at    TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX ix_audit_entity ON audit_log(entity_type, entity_id);
CREATE INDEX ix_audit_time ON audit_log(occurred_at);

CREATE TABLE notifications (
    notification_id INTEGER PRIMARY KEY AUTOINCREMENT,
    recipient_user_id INTEGER NOT NULL REFERENCES users(user_id),
    channel         TEXT CHECK(channel IN ('Email','SMS','Push','InApp')),
    subject         TEXT,
    body            TEXT,
    related_entity_type TEXT,
    related_entity_id   INTEGER,
    is_read         INTEGER NOT NULL DEFAULT 0,
    sent_at         TEXT NOT NULL DEFAULT (datetime('now')),
    read_at         TEXT
);
CREATE INDEX ix_notif_user ON notifications(recipient_user_id, is_read);

-- ---------------------------------------------------------------------
-- Section 11 : DOCUMENT PROCESSING  (text extraction + RAG chunks)
-- Text docs are read from disk, content extracted, stored here so the
-- AI assistant can search/recall them alongside structured data.
-- ---------------------------------------------------------------------

CREATE TABLE document_extracts (
    extract_id        INTEGER PRIMARY KEY AUTOINCREMENT,
    document_id       INTEGER REFERENCES document_references(document_id),
    source_path       TEXT NOT NULL,                 -- absolute file path or s3://
    file_name         TEXT NOT NULL,
    document_category TEXT,                          -- 'Policy','SOP','Contract','Manual','Report','Memo','Permit'
    related_entity_type TEXT,                        -- e.g. 'well','contract','incident'
    related_entity_id   INTEGER,
    char_count        INTEGER,
    word_count        INTEGER,
    language          TEXT DEFAULT 'en',
    extracted_text    TEXT NOT NULL,
    summary           TEXT,
    keywords          TEXT,                          -- comma separated
    extraction_method TEXT DEFAULT 'plaintext',
    extracted_by_user_id INTEGER REFERENCES users(user_id),
    extracted_at      TEXT NOT NULL DEFAULT (datetime('now')),
    is_indexed        INTEGER NOT NULL DEFAULT 0,
    UNIQUE(source_path)
);
CREATE INDEX ix_doc_extract_cat ON document_extracts(document_category);
CREATE INDEX ix_doc_extract_entity ON document_extracts(related_entity_type, related_entity_id);

CREATE TABLE document_chunks (
    chunk_id          INTEGER PRIMARY KEY AUTOINCREMENT,
    extract_id        INTEGER NOT NULL REFERENCES document_extracts(extract_id) ON DELETE CASCADE,
    chunk_index       INTEGER NOT NULL,
    chunk_text        TEXT NOT NULL,
    char_start        INTEGER,
    char_end          INTEGER,
    token_estimate    INTEGER,
    embedding_model   TEXT,                          -- e.g. 'voyage-3', 'text-embedding-3-large'
    embedding_blob    BLOB,                          -- vector bytes; NULL if not embedded yet
    created_at        TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(extract_id, chunk_index)
);
CREATE INDEX ix_chunks_extract ON document_chunks(extract_id);

-- Lightweight FTS5 virtual table for keyword search over chunks.
-- (Populated by the ingest script after rows are inserted.)
CREATE VIRTUAL TABLE document_chunks_fts USING fts5(
    chunk_text,
    content='document_chunks',
    content_rowid='chunk_id',
    tokenize='porter unicode61'
);

-- =====================================================================
-- End of schema. 53 tables (51 relational + 1 extracts + 1 chunks + FTS).
-- =====================================================================
