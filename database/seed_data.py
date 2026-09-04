"""
NorthStar Petroleum Corp. - Database Seeder
============================================
Generates 3 years of realistic data across 51 tables.

Run:  python seed_data.py
Out:  oilgas.db (SQLite)
"""

from __future__ import annotations
import os
import sys
import math
import random
import sqlite3
import hashlib
import secrets
import datetime as dt
from pathlib import Path
from dataclasses import dataclass

try:
    from faker import Faker
except ImportError:
    print("ERROR: pip install faker", file=sys.stderr)
    sys.exit(1)

try:
    import bcrypt
    HAS_BCRYPT = True
except ImportError:
    HAS_BCRYPT = False  # fall back to sha256 hash for portability

HERE = Path(__file__).parent
DB_PATH = HERE / "oilgas.db"
SCHEMA_PATH = HERE / "schema.sql"

# ---- Reproducibility ----
SEED = 20260501
random.seed(SEED)
fake = Faker()
Faker.seed(SEED)

# ---- Date window : 3 years ----
END_DATE = dt.date(2026, 4, 30)
START_DATE = END_DATE - dt.timedelta(days=3 * 365)
ALL_DAYS = [START_DATE + dt.timedelta(days=i) for i in range((END_DATE - START_DATE).days + 1)]

NOW_ISO = dt.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")


# =====================================================================
# Helpers
# =====================================================================

def isod(d: dt.date | dt.datetime) -> str:
    return d.strftime("%Y-%m-%d %H:%M:%S") if isinstance(d, dt.datetime) else d.strftime("%Y-%m-%d")


def hash_password(plain: str, salt: str) -> str:
    if HAS_BCRYPT:
        return bcrypt.hashpw((plain + salt).encode(), bcrypt.gensalt(rounds=4)).decode()
    return hashlib.sha256((plain + salt).encode()).hexdigest()


def gen_salt() -> str:
    return secrets.token_hex(8)


def weighted_choice(pairs):
    items, weights = zip(*pairs)
    return random.choices(items, weights=weights, k=1)[0]


# =====================================================================
# Build database
# =====================================================================

def init_db() -> sqlite3.Connection:
    if DB_PATH.exists():
        DB_PATH.unlink()
    conn = sqlite3.connect(DB_PATH)
    conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
    conn.commit()
    return conn


# =====================================================================
# Reference data
# =====================================================================

ROLES = [
    ("ADMIN", "System Administrator", "Full system access", 1),
    ("CEO", "Chief Executive Officer", "Executive approval", 1),
    ("CFO", "Chief Financial Officer", "Financial executive", 1),
    ("COO", "Chief Operating Officer", "Operations executive", 1),
    ("FINANCE_MGR", "Finance Manager", "Approves invoices, POs", 0),
    ("FINANCE_ANALYST", "Finance Analyst", "Creates invoices, POs", 0),
    ("OPS_MGR", "Operations Manager", "Approves operational requests", 0),
    ("DRILLING_ENG", "Drilling Engineer", "Manages drilling operations", 0),
    ("PROD_ENG", "Production Engineer", "Manages production data", 0),
    ("RESERVOIR_ENG", "Reservoir Engineer", "Reservoir analysis", 0),
    ("FIELD_SUPERVISOR", "Field Supervisor", "Field operations", 0),
    ("HSE_MGR", "HSE Manager", "Health/Safety/Env oversight", 0),
    ("HSE_OFFICER", "HSE Officer", "Reports incidents", 0),
    ("PROCUREMENT_MGR", "Procurement Manager", "Approves vendor POs", 0),
    ("LEGAL_COUNSEL", "Legal Counsel", "Reviews contracts", 0),
    ("HR_MGR", "HR Manager", "Manages personnel", 0),
    ("AUDITOR", "Internal Auditor", "Read-only audit access", 0),
    ("VALIDATOR", "Data Validator", "Validates entries before approval", 0),
    ("VIEWER", "Read-only Viewer", "Read access", 0),
    ("API_USER", "API Service Account", "External integrations", 0),
]

PERMISSIONS = [
    ("invoices:create", "invoices", "create"),
    ("invoices:read", "invoices", "read"),
    ("invoices:update", "invoices", "update"),
    ("invoices:approve", "invoices", "approve"),
    ("invoices:delete", "invoices", "delete"),
    ("po:create", "purchase_orders", "create"),
    ("po:approve", "purchase_orders", "approve"),
    ("po:read", "purchase_orders", "read"),
    ("contracts:create", "contracts", "create"),
    ("contracts:approve", "contracts", "approve"),
    ("contracts:read", "contracts", "read"),
    ("wells:read", "wells", "read"),
    ("wells:update", "wells", "update"),
    ("production:create", "daily_production", "create"),
    ("production:validate", "daily_production", "validate"),
    ("production:read", "daily_production", "read"),
    ("incidents:create", "incidents", "create"),
    ("incidents:investigate", "incidents", "investigate"),
    ("permits:manage", "permits", "manage"),
    ("audit:read", "audit_log", "read"),
    ("users:manage", "users", "manage"),
    ("workorders:create", "work_orders", "create"),
    ("workorders:approve", "work_orders", "approve"),
]

ROLE_PERM_MAP = {
    "ADMIN":          [p[0] for p in PERMISSIONS],
    "CEO":            ["invoices:approve", "po:approve", "contracts:approve", "audit:read"],
    "CFO":            ["invoices:approve", "po:approve", "contracts:approve", "invoices:read", "po:read", "audit:read"],
    "COO":            ["wells:update", "workorders:approve", "incidents:investigate", "po:approve"],
    "FINANCE_MGR":    ["invoices:approve", "invoices:create", "invoices:read", "invoices:update", "po:approve", "po:read"],
    "FINANCE_ANALYST":["invoices:create", "invoices:read", "po:create", "po:read"],
    "OPS_MGR":        ["wells:read", "wells:update", "workorders:approve", "production:read"],
    "DRILLING_ENG":   ["wells:read", "wells:update", "workorders:create"],
    "PROD_ENG":       ["wells:read", "production:create", "production:read", "production:validate"],
    "RESERVOIR_ENG":  ["wells:read", "production:read"],
    "FIELD_SUPERVISOR":["wells:read", "production:create", "incidents:create", "workorders:create"],
    "HSE_MGR":        ["incidents:create", "incidents:investigate", "permits:manage"],
    "HSE_OFFICER":    ["incidents:create"],
    "PROCUREMENT_MGR":["po:approve", "po:create", "po:read"],
    "LEGAL_COUNSEL":  ["contracts:approve", "contracts:create", "contracts:read"],
    "HR_MGR":         ["users:manage"],
    "AUDITOR":        ["audit:read", "invoices:read", "po:read", "contracts:read"],
    "VALIDATOR":      ["production:validate", "invoices:read"],
    "VIEWER":         ["wells:read", "invoices:read", "po:read"],
    "API_USER":       ["wells:read", "production:read", "invoices:read"],
}

DEPARTMENTS = [
    ("EXEC",   "Executive Office",        None,           "Houston, TX"),
    ("FIN",    "Finance & Accounting",    "EXEC",         "Houston, TX"),
    ("PROC",   "Procurement",             "FIN",          "Houston, TX"),
    ("OPS",    "Operations",              "EXEC",         "Houston, TX"),
    ("UPS",    "Upstream Operations",     "OPS",          "Midland, TX"),
    ("MID",    "Midstream Operations",    "OPS",          "Houston, TX"),
    ("DOWN",   "Downstream Operations",   "OPS",          "Beaumont, TX"),
    ("DRILL",  "Drilling Engineering",    "UPS",          "Midland, TX"),
    ("RES",    "Reservoir Engineering",   "UPS",          "Houston, TX"),
    ("PROD",   "Production Engineering",  "UPS",          "Midland, TX"),
    ("HSE",    "Health Safety Env",       "OPS",          "Houston, TX"),
    ("LEGAL",  "Legal & Compliance",      "EXEC",         "Houston, TX"),
    ("HR",     "Human Resources",         "EXEC",         "Houston, TX"),
    ("IT",     "Information Technology",  "EXEC",         "Houston, TX"),
    ("AUDIT",  "Internal Audit",          "EXEC",         "Houston, TX"),
]

OIL_FIELD_DEFS = [
    # (code,    name,                    basin,            country, region,    on_off,    api_grav, est_reserves)
    ("PERM-EAG", "Eagle Ford Permian",  "Permian Basin",  "USA",   "TX",      "Onshore", 36.5, 1250.0),
    ("BAK-WIL",  "Bakken Williston",    "Williston Basin","USA",   "ND",      "Onshore", 41.0,  680.0),
    ("GOM-MAR",  "Mars Deepwater",      "Gulf of Mexico", "USA",   "GoM",     "Offshore",30.5, 2100.0),
    ("NS-BRENT", "Brent North Sea",     "North Sea",      "UK",    "NorthSea","Offshore",38.0,  450.0),
    ("MID-GHAR", "Ghawar South",        "Arabian",        "Saudi Arabia","Eastern","Onshore",34.0, 8800.0),
    ("CAN-ATH",  "Athabasca Oil Sands", "WCSB",           "Canada","Alberta", "Onshore", 9.0,  3400.0),
]

PIPELINE_DEFS = [
    ("PL-CRUDE-01", "Permian to Houston Crude",    "Crude",   42, 720, 600000, "Midland TX", "Houston TX"),
    ("PL-CRUDE-02", "Bakken Express",              "Crude",   30, 1900,510000, "Tioga ND",   "Patoka IL"),
    ("PL-GAS-01",   "Gulf Gas Trunk",              "Gas",     36, 480, 1200000,"Mars Platform","Port Fourchon LA"),
    ("PL-NGL-01",   "Permian NGL",                 "NGL",     20, 540, 250000, "Midland TX", "Mont Belvieu TX"),
    ("PL-REF-01",   "Refined Products South",      "Refined", 24, 350, 320000, "Beaumont TX","Atlanta GA"),
]

REFINERY_DEFS = [
    ("REF-BMT", "Beaumont Refinery", "Beaumont, TX",  365000, 12.5, "1985-06-01"),
    ("REF-COR", "Corpus Christi",    "Corpus Christi, TX", 290000, 10.8, "1990-01-01"),
    ("REF-EDM", "Edmonton Strathcona","Edmonton, AB", 195000,  9.2, "1978-09-15"),
]

PRODUCT_DEFS = [
    ("WTI",    "WTI Crude Oil",      "Crude",    "BBL",  0.85),
    ("BRENT",  "Brent Crude Oil",    "Crude",    "BBL",  0.83),
    ("MARS",   "Mars Blend",         "Crude",    "BBL",  0.88),
    ("NG",     "Natural Gas",        "Gas",      "MMBTU",0.001),
    ("NGL",    "Natural Gas Liquids","NGL",      "BBL",  0.55),
    ("RBOB",   "Gasoline RBOB",      "Gasoline", "BBL",  0.74),
    ("ULSD",   "Ultra Low Sulfur Diesel","Diesel","BBL", 0.85),
    ("JETA",   "Jet A Kerosene",     "JetA",     "BBL",  0.81),
    ("LPG",    "Liquefied Petroleum","LPG",      "BBL",  0.51),
    ("ASPHALT","Asphalt",            "Asphalt",  "TON",  1.03),
]

VENDOR_CATEGORIES = ["drilling_services","equipment","logistics","it","consulting","chemicals","inspection","catering"]
VENDOR_NAMES = [
    "Halliburton Energy Services", "Schlumberger NV", "Baker Hughes Inc",
    "Weatherford Intl", "NOV Inc", "Transocean Ltd", "Diamond Offshore",
    "Patterson-UTI Drilling", "Helmerich & Payne", "Nabors Industries",
    "Parker Wellbore", "Precision Drilling", "Tetra Technologies",
    "Core Laboratories", "Intertek Group", "Bureau Veritas",
    "DNV GL", "ABS Group", "Lloyds Register", "TUV Rheinland",
    "ExxonMobil Chemical", "Dow Chemical", "BASF", "Solvay",
    "Caterpillar Inc", "Komatsu", "John Deere Industrial", "Volvo CE",
    "AVEVA Group", "Honeywell Process Solutions", "Emerson Automation", "Yokogawa",
    "Accenture Energy", "McKinsey", "Deloitte Consulting", "Bain Capital Energy",
    "Kuehne+Nagel Oil Logistics", "DHL Industrial", "Maersk Tankers", "Frontline Tankers",
]

CUSTOMER_NAMES = [
    "Phillips 66 Company", "Marathon Petroleum", "Valero Energy",
    "Sinopec Trading", "Shell Trading USA", "BP Products NA",
    "TotalEnergies Trading", "Reliance Industries Ltd", "Indian Oil Corporation",
    "PetroChina Intl", "Vitol SA", "Trafigura Group", "Glencore Energy",
    "Mercuria Energy", "Gunvor Group", "Koch Supply & Trading",
    "PEMEX Trading", "Saudi Aramco Trading", "ADNOC Distribution",
    "Equinor Marketing", "Eni Trading", "Repsol Trading",
]

INCIDENT_TYPES = ["NearMiss","FirstAid","MTC","LTI","Spill","Fire","GasRelease","Equipment"]
INCIDENT_WEIGHTS = [40,        25,       12,    5,    8,      3,    4,           3]

ENV_PARAMS = [
    ("CO2",   "ppm",    420.0,  500.0),
    ("CH4",   "ppm",    1.85,   2.5),
    ("SO2",   "ppb",    5.0,    20.0),
    ("H2S",   "ppm",    0.5,    5.0),
    ("NOx",   "ppb",    20.0,   80.0),
    ("PM2.5", "ug/m3",  10.0,   35.0),
    ("VOC",   "ppb",    15.0,   60.0),
]

EXTERNAL_SYSTEMS = [
    ("SCADA",      "OSIsoft PI",        "https://pi.northstar-petro.com/asset/"),
    ("ERP",        "SAP S/4HANA",       "https://sap.northstar-petro.com/object/"),
    ("SharePoint", "MS SharePoint",     "https://northstar.sharepoint.com/sites/ops/"),
    ("S3",         "AWS S3",            "s3://northstar-docs/"),
    ("LIMS",       "LabWare LIMS",      "https://lims.northstar-petro.com/sample/"),
    ("GIS",        "Esri ArcGIS",       "https://gis.northstar-petro.com/feature/"),
    ("CRM",        "Salesforce",        "https://northstar.my.salesforce.com/"),
    ("CMMS",       "IBM Maximo",        "https://maximo.northstar-petro.com/wo/"),
]


# =====================================================================
# Seeder functions
# =====================================================================

def seed_roles_perms(c):
    print("  -> roles, permissions, role_permissions")
    role_id = {}
    for code, name, desc, sysflag in ROLES:
        cur = c.execute("INSERT INTO roles(role_code,role_name,description,is_system) VALUES(?,?,?,?)",
                        (code, name, desc, sysflag))
        role_id[code] = cur.lastrowid
    perm_id = {}
    for code, res, act in PERMISSIONS:
        cur = c.execute("INSERT INTO permissions(permission_code,resource,action) VALUES(?,?,?)", (code, res, act))
        perm_id[code] = cur.lastrowid
    for rcode, plist in ROLE_PERM_MAP.items():
        for pcode in plist:
            c.execute("INSERT INTO role_permissions(role_id,permission_id) VALUES(?,?)",
                      (role_id[rcode], perm_id[pcode]))
    return role_id, perm_id


def seed_departments(c):
    print("  -> departments")
    dept_id = {}
    for code, name, parent_code, location in DEPARTMENTS:
        parent_id = dept_id.get(parent_code) if parent_code else None
        cc_code = f"CC-{code}"
        cur = c.execute("""INSERT INTO departments(dept_code,dept_name,parent_dept_id,cost_center_code,location)
                           VALUES(?,?,?,?,?)""", (code, name, parent_id, cc_code, location))
        dept_id[code] = cur.lastrowid
    return dept_id


@dataclass
class UserRow:
    user_id: int
    username: str
    email: str
    role_codes: list
    department_code: str
    employee_id: int | None = None


def seed_users(c, role_id, dept_id):
    print("  -> users + employees + user_roles + mfa_devices")
    users = []
    # Define the executive layer first so reporting lines work.
    seed_users_data = [
        # (username,         first,    last,     dept,     roles,                          job_title)
        ("admin.root",       "Root",   "Admin",  "IT",     ["ADMIN"],                      "Platform Administrator"),
        ("rachel.mendoza",   "Rachel", "Mendoza","EXEC",   ["CEO"],                        "Chief Executive Officer"),
        ("david.chen",       "David",  "Chen",   "FIN",    ["CFO"],                        "Chief Financial Officer"),
        ("priya.iyer",       "Priya",  "Iyer",   "OPS",    ["COO"],                        "Chief Operating Officer"),
        ("james.okafor",     "James",  "Okafor", "FIN",    ["FINANCE_MGR"],                "Finance Manager"),
        ("emma.larsson",     "Emma",   "Larsson","FIN",    ["FINANCE_MGR"],                "Senior Finance Manager"),
        ("noah.rivera",      "Noah",   "Rivera", "FIN",    ["FINANCE_ANALYST"],            "Finance Analyst"),
        ("olivia.tanaka",    "Olivia", "Tanaka", "FIN",    ["FINANCE_ANALYST"],            "Finance Analyst"),
        ("liam.bauer",       "Liam",   "Bauer",  "FIN",    ["FINANCE_ANALYST","VALIDATOR"],"Finance Analyst"),
        ("ava.singh",        "Ava",    "Singh",  "PROC",   ["PROCUREMENT_MGR"],            "Procurement Manager"),
        ("william.kim",      "William","Kim",    "PROC",   ["PROCUREMENT_MGR"],            "Procurement Lead"),
        ("sophia.alvarez",   "Sophia", "Alvarez","PROC",   ["FINANCE_ANALYST"],            "Procurement Analyst"),
        ("lucas.murphy",     "Lucas",  "Murphy", "OPS",    ["OPS_MGR"],                    "Operations Manager"),
        ("mia.dubois",       "Mia",    "Dubois", "UPS",    ["OPS_MGR"],                    "Upstream Manager"),
        ("ethan.zhao",       "Ethan",  "Zhao",   "MID",    ["OPS_MGR"],                    "Midstream Manager"),
        ("isabella.nasser",  "Isabella","Nasser","DOWN",   ["OPS_MGR"],                    "Downstream Manager"),
        ("amir.haddad",      "Amir",   "Haddad", "DRILL",  ["DRILLING_ENG"],               "Senior Drilling Engineer"),
        ("zoe.patel",        "Zoe",    "Patel",  "DRILL",  ["DRILLING_ENG"],               "Drilling Engineer"),
        ("hugo.fernandes",   "Hugo",   "Fernandes","DRILL",["DRILLING_ENG"],               "Drilling Engineer"),
        ("luna.svensson",    "Luna",   "Svensson","RES",   ["RESERVOIR_ENG"],              "Senior Reservoir Engineer"),
        ("mateo.rossi",      "Mateo",  "Rossi",  "RES",    ["RESERVOIR_ENG"],              "Reservoir Engineer"),
        ("aria.kowalski",    "Aria",   "Kowalski","PROD",  ["PROD_ENG"],                   "Senior Production Engineer"),
        ("benjamin.ahmed",   "Benjamin","Ahmed", "PROD",   ["PROD_ENG"],                   "Production Engineer"),
        ("charlotte.wagner", "Charlotte","Wagner","PROD",  ["PROD_ENG","VALIDATOR"],       "Production Engineer"),
        ("daniel.osei",      "Daniel", "Osei",   "PROD",   ["PROD_ENG"],                   "Production Engineer"),
        ("ella.martinez",    "Ella",   "Martinez","PROD",  ["FIELD_SUPERVISOR"],           "Field Supervisor"),
        ("finn.olsen",       "Finn",   "Olsen",  "PROD",   ["FIELD_SUPERVISOR"],           "Field Supervisor"),
        ("grace.kapoor",     "Grace",  "Kapoor", "PROD",   ["FIELD_SUPERVISOR"],           "Field Supervisor"),
        ("henry.nakamura",   "Henry",  "Nakamura","HSE",   ["HSE_MGR"],                    "HSE Manager"),
        ("ivy.brennan",      "Ivy",    "Brennan","HSE",    ["HSE_OFFICER"],                "HSE Officer"),
        ("jasper.kone",      "Jasper", "Kone",   "HSE",    ["HSE_OFFICER"],                "HSE Officer"),
        ("kira.takahashi",   "Kira",   "Takahashi","LEGAL",["LEGAL_COUNSEL"],              "General Counsel"),
        ("leo.ferreira",     "Leo",    "Ferreira","LEGAL", ["LEGAL_COUNSEL"],              "Legal Counsel"),
        ("maya.bergstrom",   "Maya",   "Bergstrom","HR",   ["HR_MGR"],                     "HR Manager"),
        ("nora.dimitri",     "Nora",   "Dimitri","HR",     ["HR_MGR"],                     "HR Business Partner"),
        ("oscar.nguyen",     "Oscar",  "Nguyen", "IT",     ["ADMIN"],                      "IT Director"),
        ("pia.larsen",       "Pia",    "Larsen", "IT",     ["ADMIN"],                      "DevOps Lead"),
        ("quinn.hassan",     "Quinn",  "Hassan", "AUDIT",  ["AUDITOR"],                    "Internal Auditor"),
        ("ryan.cole",        "Ryan",   "Cole",   "AUDIT",  ["AUDITOR"],                    "Senior Auditor"),
        ("sara.popov",       "Sara",   "Popov",  "MID",    ["FIELD_SUPERVISOR"],           "Pipeline Supervisor"),
        ("tomas.silva",      "Tomas",  "Silva",  "MID",    ["FIELD_SUPERVISOR"],           "Terminal Supervisor"),
        ("uma.bhatt",        "Uma",    "Bhatt",  "DOWN",   ["FIELD_SUPERVISOR"],           "Refinery Supervisor"),
        ("victor.romano",    "Victor", "Romano", "DOWN",   ["FIELD_SUPERVISOR"],           "Refinery Engineer"),
        ("wendy.park",       "Wendy",  "Park",   "PROC",   ["VIEWER"],                     "Procurement Coordinator"),
        ("xavier.cruz",      "Xavier", "Cruz",   "FIN",    ["VIEWER"],                     "AP Clerk"),
        ("yui.morita",       "Yui",    "Morita", "FIN",    ["VIEWER"],                     "AR Clerk"),
        ("zane.holm",        "Zane",   "Holm",   "IT",     ["API_USER"],                   "API Service Account"),
        ("ahmad.fahmi",      "Ahmad",  "Fahmi",  "DRILL",  ["DRILLING_ENG"],               "Drilling Supervisor"),
        ("beatrice.lin",     "Beatrice","Lin",   "RES",    ["RESERVOIR_ENG"],              "Reservoir Analyst"),
        ("cesar.gonzalez",   "Cesar",  "Gonzalez","PROD",  ["PROD_ENG"],                   "Production Analyst"),
        ("delphine.rousseau","Delphine","Rousseau","HSE",  ["HSE_OFFICER"],                "HSE Specialist"),
    ]

    rows = []
    for i, (uname, fn, ln, dcode, rcodes, title) in enumerate(seed_users_data, start=1):
        salt = gen_salt()
        pwd_hash = hash_password("ChangeMe!2026", salt)
        emp_code = f"EMP{1000+i:05d}"
        last_login = isod(fake.date_time_between(start_date=END_DATE - dt.timedelta(days=14), end_date=END_DATE))
        pwd_changed = isod(fake.date_time_between(start_date=START_DATE, end_date=END_DATE))
        cur = c.execute("""INSERT INTO users(username,email,password_hash,password_salt,first_name,last_name,
                            phone,employee_code,is_active,last_login_at,password_changed_at,mfa_enabled,
                            timezone,locale,created_at,updated_at)
                           VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                        (uname, f"{uname}@northstar-petro.com", pwd_hash, salt, fn, ln,
                         fake.phone_number(), emp_code, 1, last_login, pwd_changed,
                         1 if random.random() < 0.7 else 0, "America/Chicago", "en-US", NOW_ISO, NOW_ISO))
        uid = cur.lastrowid
        for rc in rcodes:
            c.execute("INSERT INTO user_roles(user_id,role_id,granted_at) VALUES(?,?,?)",
                      (uid, role_id[rc], pwd_changed))
        if random.random() < 0.7:
            c.execute("""INSERT INTO mfa_devices(user_id,device_type,secret,label,is_primary,verified_at)
                         VALUES(?,?,?,?,?,?)""",
                      (uid, "totp", secrets.token_hex(20), "Authenticator App", 1, pwd_changed))
        rows.append(UserRow(uid, uname, f"{uname}@northstar-petro.com", rcodes, dcode))
    return rows


def seed_employees(c, users: list[UserRow], dept_id):
    print("  -> employees + manager chain")
    # First pass: create employees
    for u in users:
        hire_date = fake.date_between(start_date=dt.date(2010, 1, 1), end_date=dt.date(2024, 6, 30))
        emp_type = weighted_choice([("FullTime", 85), ("Contractor", 12), ("Consultant", 3)])
        cur = c.execute("""INSERT INTO employees(user_id,department_id,job_title,job_grade,
                            employment_type,hire_date,salary_band,work_location,badge_number,
                            emergency_contact)
                           VALUES(?,?,?,?,?,?,?,?,?,?)""",
                        (u.user_id, dept_id[u.department_code], "Staff",
                         random.choice(["G7","G8","G9","G10","G11","G12","G13","G14","G15"]),
                         emp_type, isod(hire_date),
                         random.choice(["B1","B2","B3","B4","B5"]),
                         random.choice(["Houston, TX","Midland, TX","Beaumont, TX","Edmonton, AB","Aberdeen, UK","Dubai, UAE"]),
                         f"BDG-{u.user_id:05d}", fake.phone_number()))
        u.employee_id = cur.lastrowid

    # Second pass: assign manager_id roughly by seniority order (lower user_id == more senior)
    sorted_users = sorted(users, key=lambda u: u.user_id)
    for i, u in enumerate(sorted_users):
        if i == 0:
            continue
        # Manager : someone earlier in the list with same or parent department.
        candidates = [m for m in sorted_users[:i] if m.user_id != u.user_id]
        manager = random.choice(candidates) if candidates else None
        if manager:
            c.execute("UPDATE employees SET manager_id=? WHERE employee_id=?",
                      (manager.employee_id, u.employee_id))


def seed_login_audit(c, users):
    print("  -> login_audit (3 years of login activity)")
    rows = []
    for u in users:
        # Mostly successful logins, occasional failures, weekly rhythm
        d = START_DATE
        while d <= END_DATE:
            if d.weekday() < 5 and random.random() < 0.85:  # workday login
                hour = random.randint(6, 10)
                minute = random.randint(0, 59)
                ts = dt.datetime.combine(d, dt.time(hour, minute))
                # 4% chance fail-then-success same day
                if random.random() < 0.04:
                    rows.append((u.user_id, u.username, fake.ipv4(), fake.user_agent(),
                                 "login_fail", "wrong password", isod(ts)))
                    ts = ts + dt.timedelta(minutes=2)
                rows.append((u.user_id, u.username, fake.ipv4(), fake.user_agent(),
                             "login_success", None, isod(ts)))
                # Logout end of day
                logout_ts = dt.datetime.combine(d, dt.time(random.randint(17, 19), random.randint(0, 59)))
                rows.append((u.user_id, u.username, fake.ipv4(), fake.user_agent(),
                             "logout", None, isod(logout_ts)))
            d += dt.timedelta(days=1)
            # speed up - skip ~4 days each iter
            d += dt.timedelta(days=random.randint(2, 5))

    # plus a few targeted lockouts
    for _ in range(40):
        u = random.choice(users)
        ts = fake.date_time_between(start_date=START_DATE, end_date=END_DATE)
        for _ in range(5):
            rows.append((u.user_id, u.username, fake.ipv4(), fake.user_agent(),
                         "login_fail", "invalid credentials", isod(ts)))
            ts += dt.timedelta(minutes=1)
        rows.append((u.user_id, u.username, fake.ipv4(), fake.user_agent(),
                     "lockout", "too many failures", isod(ts)))

    c.executemany("""INSERT INTO login_audit(user_id,username,ip_address,user_agent,event_type,detail,occurred_at)
                     VALUES(?,?,?,?,?,?,?)""", rows)
    print(f"     login_audit rows: {len(rows):,}")


def seed_user_sessions(c, users):
    print("  -> user_sessions (active + recent)")
    import uuid
    rows = []
    for u in users:
        # 5-15 historical sessions per user
        for _ in range(random.randint(5, 15)):
            issued = fake.date_time_between(start_date=START_DATE, end_date=END_DATE)
            ttl = random.choice([1, 4, 8, 12, 24])
            expires = issued + dt.timedelta(hours=ttl)
            revoked = expires if random.random() < 0.6 else None
            rows.append((str(uuid.uuid4()), u.user_id, fake.ipv4(), fake.user_agent(),
                         isod(issued), isod(expires), isod(revoked) if revoked else None,
                         isod(expires - dt.timedelta(minutes=random.randint(5, 60)))))
    c.executemany("""INSERT INTO user_sessions(session_id,user_id,ip_address,user_agent,issued_at,expires_at,revoked_at,last_seen_at)
                     VALUES(?,?,?,?,?,?,?,?)""", rows)


def seed_approval_workflows(c, role_id):
    print("  -> approval_workflows + approval_steps")
    workflows = [
        ("WF-INV-LOW",  "Invoice Approval (under 50k)",     "invoice",       0,      50000),
        ("WF-INV-MED",  "Invoice Approval (50k-250k)",      "invoice",       50000,  250000),
        ("WF-INV-HIGH", "Invoice Approval (over 250k)",     "invoice",       250000, 100000000),
        ("WF-PO-LOW",   "PO Approval (under 100k)",         "purchase_order",0,      100000),
        ("WF-PO-HIGH",  "PO Approval (over 100k)",          "purchase_order",100000, 100000000),
        ("WF-CONTRACT", "Contract Approval",                "contract",      0,      100000000),
        ("WF-WELL-AFE", "Well Drilling AFE Approval",       "well_drilling", 0,      100000000),
        ("WF-PERMIT",   "Regulatory Permit",                "permit",        0,      100000000),
    ]
    wf_id = {}
    for code, name, etype, mn, mx in workflows:
        cur = c.execute("""INSERT INTO approval_workflows(workflow_code,workflow_name,entity_type,
                            description,is_active,min_amount,max_amount)
                           VALUES(?,?,?,?,?,?,?)""", (code, name, etype, name, 1, mn, mx))
        wf_id[code] = cur.lastrowid

    steps = [
        # workflow      step  name                     role               sla
        ("WF-INV-LOW",   1,  "Validation",             "VALIDATOR",        24),
        ("WF-INV-LOW",   2,  "Finance Manager Approve","FINANCE_MGR",      48),
        ("WF-INV-MED",   1,  "Validation",             "VALIDATOR",        24),
        ("WF-INV-MED",   2,  "Finance Manager Approve","FINANCE_MGR",      48),
        ("WF-INV-MED",   3,  "CFO Sign-off",           "CFO",              72),
        ("WF-INV-HIGH",  1,  "Validation",             "VALIDATOR",        24),
        ("WF-INV-HIGH",  2,  "Finance Manager Review", "FINANCE_MGR",      48),
        ("WF-INV-HIGH",  3,  "CFO Approval",           "CFO",              72),
        ("WF-INV-HIGH",  4,  "CEO Sign-off",           "CEO",              96),
        ("WF-PO-LOW",    1,  "Procurement Review",     "PROCUREMENT_MGR",  48),
        ("WF-PO-LOW",    2,  "Finance Manager",        "FINANCE_MGR",      48),
        ("WF-PO-HIGH",   1,  "Procurement Review",     "PROCUREMENT_MGR",  48),
        ("WF-PO-HIGH",   2,  "CFO Approval",           "CFO",              72),
        ("WF-PO-HIGH",   3,  "CEO Sign-off",           "CEO",              96),
        ("WF-CONTRACT",  1,  "Legal Review",           "LEGAL_COUNSEL",    72),
        ("WF-CONTRACT",  2,  "CFO Review",             "CFO",              72),
        ("WF-CONTRACT",  3,  "CEO Sign-off",           "CEO",              96),
        ("WF-WELL-AFE",  1,  "Drilling Engineering",   "DRILLING_ENG",     48),
        ("WF-WELL-AFE",  2,  "Operations Manager",     "OPS_MGR",          72),
        ("WF-WELL-AFE",  3,  "COO Approval",           "COO",              96),
        ("WF-WELL-AFE",  4,  "CFO Approval",           "CFO",              96),
        ("WF-PERMIT",    1,  "HSE Manager Review",     "HSE_MGR",          48),
        ("WF-PERMIT",    2,  "Legal Review",           "LEGAL_COUNSEL",    72),
        ("WF-PERMIT",    3,  "COO Sign-off",           "COO",              96),
    ]
    for code, ord_, name, rcode, sla in steps:
        c.execute("""INSERT INTO approval_steps(workflow_id,step_order,step_name,role_required,sla_hours)
                     VALUES(?,?,?,?,?)""", (wf_id[code], ord_, name, role_id[rcode], sla))
    return wf_id


def seed_customers_vendors_contracts(c, users):
    print("  -> customers + customer_contacts")
    customers = []
    for i, name in enumerate(CUSTOMER_NAMES, start=1):
        rm = random.choice([u for u in users if "FINANCE_MGR" in u.role_codes or "OPS_MGR" in u.role_codes])
        cur = c.execute("""INSERT INTO customers(customer_code,legal_name,trading_name,industry,country,region,city,
                            address_line1,postal_code,tax_id,duns_number,credit_rating,credit_limit,payment_terms,
                            currency_code,relationship_manager_id,is_active,onboarded_at,notes)
                           VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                        (f"CUST-{i:04d}", name, name.split()[0], "Oil Refining/Trading",
                         random.choice(["USA","UK","Singapore","UAE","Switzerland","Netherlands","India","China"]),
                         fake.state_abbr(), fake.city(), fake.street_address(), fake.postcode(),
                         fake.bothify(text="??-########"), fake.numerify(text="#########"),
                         random.choice(["AAA","AA","A","BBB","BB"]),
                         random.choice([5_000_000, 10_000_000, 25_000_000, 50_000_000, 100_000_000]),
                         random.choice(["Net 15","Net 30","Net 45","Net 60"]), "USD",
                         rm.user_id, 1, isod(fake.date_between(start_date=dt.date(2018,1,1), end_date=START_DATE)),
                         fake.sentence(nb_words=8)))
        cid = cur.lastrowid
        customers.append((cid, name))
        # 1-3 contacts each
        for k in range(random.randint(1, 3)):
            c.execute("""INSERT INTO customer_contacts(customer_id,first_name,last_name,title,email,phone,is_primary,role_in_account)
                         VALUES(?,?,?,?,?,?,?,?)""",
                      (cid, fake.first_name(), fake.last_name(),
                       random.choice(["VP Trading","Head of Procurement","Commercial Manager","Logistics Director","Credit Controller"]),
                       fake.company_email(), fake.phone_number(), 1 if k == 0 else 0,
                       random.choice(["Decision Maker","Procurement","Operations","Finance"])))

    print("  -> vendors")
    vendors = []
    for i, name in enumerate(VENDOR_NAMES, start=1):
        cur = c.execute("""INSERT INTO vendors(vendor_code,legal_name,category,country,tax_id,bank_account,swift_code,
                            payment_terms,currency_code,rating,is_preferred,is_active,onboarded_at)
                           VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                        (f"VEND-{i:04d}", name, random.choice(VENDOR_CATEGORIES),
                         random.choice(["USA","UK","Norway","Germany","France","Canada","Singapore","UAE"]),
                         fake.bothify(text="??-########"), fake.iban(), fake.swift(),
                         random.choice(["Net 30","Net 45","Net 60","Net 90"]), "USD",
                         round(random.uniform(3.0, 5.0), 1),
                         1 if random.random() < 0.4 else 0, 1,
                         isod(fake.date_between(start_date=dt.date(2015,1,1), end_date=START_DATE))))
        vendors.append((cur.lastrowid, name, random.choice(VENDOR_CATEGORIES)))

    print("  -> contracts")
    contract_types_cust = ["CrudeSale","RefinedSale","GasSupply","PipelineTransport"]
    contract_types_vend = ["DrillingServices","Equipment","Logistics","Consulting","Maintenance"]
    contracts = []
    for k in range(80):
        side = random.choice(["Customer","Vendor"])
        if side == "Customer":
            cid, cname = random.choice(customers)
            ctype = random.choice(contract_types_cust)
            value = random.uniform(500_000, 50_000_000)
            cust_arg, vend_arg = cid, None
            title = f"{ctype} Master Agreement - {cname}"
        else:
            vid, vname, _ = random.choice(vendors)
            ctype = random.choice(contract_types_vend)
            value = random.uniform(100_000, 25_000_000)
            cust_arg, vend_arg = None, vid
            title = f"{ctype} Services Contract - {vname}"
        start = fake.date_between(start_date=START_DATE, end_date=END_DATE - dt.timedelta(days=180))
        end = start + dt.timedelta(days=random.randint(180, 365 * 3))
        signer = random.choice([u for u in users if "CEO" in u.role_codes or "CFO" in u.role_codes or "LEGAL_COUNSEL" in u.role_codes])
        status = "Active" if end > END_DATE else random.choice(["Expired","Active","Terminated"])
        cur = c.execute("""INSERT INTO contracts(contract_number,counterparty_type,customer_id,vendor_id,
                            contract_type,title,total_value,currency_code,start_date,end_date,status,governing_law,
                            signed_by_user_id)
                           VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                        (f"CON-{2023+random.randint(0,3)}-{k+1:04d}", side, cust_arg, vend_arg, ctype, title,
                         round(value, 2), "USD", isod(start), isod(end), status,
                         random.choice(["State of Texas, USA","English Law","Singapore","Switzerland"]),
                         signer.user_id))
        contracts.append(cur.lastrowid)

    return customers, vendors, contracts


def seed_upstream(c, users):
    print("  -> fields, reservoirs, wells")
    fields = []
    for code, name, basin, country, region, on_off, api, reserves in OIL_FIELD_DEFS:
        cur = c.execute("""INSERT INTO fields(field_code,field_name,basin,country,region,onshore_offshore,
                            discovery_date,operator,working_interest_pct,estimated_reserves_mmboe,is_producing)
                           VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                        (code, name, basin, country, region, on_off,
                         isod(fake.date_between(start_date=dt.date(1975,1,1), end_date=dt.date(2018,1,1))),
                         "NorthStar Petroleum",
                         round(random.uniform(40, 100), 2), reserves, 1))
        fields.append((cur.lastrowid, code, api))

    print("  -> reservoirs")
    reservoir_id_by_field = {}
    for fid, fcode, api_grav in fields:
        for k in range(random.randint(1, 3)):
            cur = c.execute("""INSERT INTO reservoirs(field_id,reservoir_name,formation,depth_m,pressure_psi,
                                temperature_c,porosity_pct,permeability_md,api_gravity,h2s_ppm,co2_pct)
                               VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                            (fid, f"{fcode}-RES-{k+1}",
                             random.choice(["Eagle Ford","Wolfcamp","Bakken","Three Forks","Spraberry","Bone Spring","Brent","Statfjord","Arab D","McMurray"]),
                             round(random.uniform(1500, 4500), 1), round(random.uniform(2500, 7500), 1),
                             round(random.uniform(60, 140), 1), round(random.uniform(8, 28), 2),
                             round(random.uniform(0.1, 500), 2), api_grav + random.uniform(-2, 2),
                             round(random.uniform(0, 200), 2), round(random.uniform(0, 8), 2)))
            reservoir_id_by_field.setdefault(fid, []).append(cur.lastrowid)

    print("  -> wells")
    wells = []
    drilling_engineers = [u for u in users if "DRILLING_ENG" in u.role_codes]
    prod_engineers = [u for u in users if "PROD_ENG" in u.role_codes]
    well_count_per_field = {fid: random.randint(3, 6) for fid, _, _ in fields}
    well_idx = 0
    for fid, fcode, api in fields:
        for w in range(well_count_per_field[fid]):
            well_idx += 1
            wtype = weighted_choice([("Producer", 70), ("Injector", 15), ("Exploration", 8), ("Appraisal", 5), ("Disposal", 2)])
            # ~30% of wells have 2025 drilling activity, the rest are spread
            # across 2018-2024. Without this split, the seed produces near-zero
            # 2025 drilling ops because spud dates dominate the date math.
            if random.random() < 0.30:
                spud = fake.date_between(start_date=dt.date(2024, 9, 1),
                                         end_date=dt.date(2025, 9, 30))
            else:
                spud = fake.date_between(start_date=dt.date(2018, 1, 1),
                                         end_date=dt.date(2024, 8, 31))
            comp = spud + dt.timedelta(days=random.randint(45, 180))
            status = weighted_choice([("Producing", 65), ("ShutIn", 12), ("Suspended", 8), ("Drilling", 5), ("Abandoned", 5), ("Completed", 5)])
            op = random.choice(prod_engineers)
            cur = c.execute("""INSERT INTO wells(field_id,reservoir_id,well_code,well_name,well_type,well_status,
                                spud_date,completion_date,total_depth_m,latitude,longitude,operator_user_id)
                               VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
                            (fid, random.choice(reservoir_id_by_field.get(fid, [None])),
                             f"{fcode}-W{w+1:03d}", f"{fcode} Well {w+1}",
                             wtype, status, isod(spud), isod(comp),
                             round(random.uniform(1800, 4500), 1),
                             round(random.uniform(25, 65), 6), round(random.uniform(-110, 5), 6),
                             op.user_id))
            wells.append((cur.lastrowid, fid, fcode, status, comp, api))
    return fields, wells


def seed_drilling(c, users, wells, vendors):
    print("  -> drilling_rigs")
    drilling_vendors = [v for v in vendors if v[2] in ("drilling_services","equipment")]
    rigs = []
    for i in range(15):
        v = random.choice(drilling_vendors) if drilling_vendors else random.choice(vendors)
        cur = c.execute("""INSERT INTO drilling_rigs(rig_code,rig_name,rig_type,contractor_vendor_id,
                            horsepower,max_depth_m,day_rate_usd,is_active)
                           VALUES(?,?,?,?,?,?,?,?)""",
                        (f"RIG-{i+1:03d}", f"NorthStar Rig {i+1}",
                         random.choice(["Land","Land","Jackup","Semisubmersible","Drillship"]),
                         v[0], random.choice([1500, 2000, 3000, 5000]),
                         round(random.uniform(3500, 12000), 0),
                         round(random.uniform(35000, 950000), 0), 1))
        rigs.append(cur.lastrowid)

    print("  -> drilling_operations")
    drilling_engineers = [u for u in users if "DRILLING_ENG" in u.role_codes]
    field_supervisors = [u for u in users if "FIELD_SUPERVISOR" in u.role_codes]
    for wid, fid, fcode, status, comp, api in wells:
        if status in ("Drilling","Producing","ShutIn","Suspended","Completed","Abandoned"):
            rig = random.choice(rigs)
            sup = random.choice(field_supervisors)
            eng = random.choice(drilling_engineers)
            start = comp - dt.timedelta(days=random.randint(45, 180))
            planned = random.randint(60, 150)
            actual = planned + random.randint(-20, 40)
            afe = random.uniform(3_000_000, 18_000_000)
            actual_cost = afe * random.uniform(0.85, 1.25)
            c.execute("""INSERT INTO drilling_operations(well_id,rig_id,start_date,end_date,planned_days,
                          actual_days,afe_amount,actual_cost,well_supervisor_id,drilling_engineer_id,status)
                         VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                      (wid, rig, isod(start), isod(comp), planned, actual,
                       round(afe, 2), round(actual_cost, 2),
                       sup.user_id, eng.user_id, "Completed"))


def seed_well_completions(c, wells, vendors):
    print("  -> well_completions")
    drilling_vendors = [v for v in vendors if v[2] in ("drilling_services","equipment")]
    for wid, fid, fcode, status, comp, api in wells:
        if status not in ("Drilling",):
            ctype = random.choice(["OpenHole","Cased","Perforated","Hydraulic Fractured"])
            v = random.choice(drilling_vendors) if drilling_vendors else None
            top = round(random.uniform(1500, 3500), 1)
            bot = top + random.uniform(50, 350)
            c.execute("""INSERT INTO well_completions(well_id,completion_date,completion_type,
                          contractor_vendor_id,casing_size_in,tubing_size_in,perforation_top_m,perforation_bottom_m,cost_usd)
                         VALUES(?,?,?,?,?,?,?,?,?)""",
                      (wid, isod(comp), ctype,
                       v[0] if v else None,
                       round(random.choice([7.0, 8.625, 9.625, 10.75]), 3),
                       round(random.choice([2.875, 3.5, 4.5, 5.5]), 3),
                       top, bot,
                       round(random.uniform(300_000, 2_500_000), 2)))


def seed_well_tests(c, wells, users):
    print("  -> well_tests")
    rows = []
    prod_engineers = [u for u in users if "PROD_ENG" in u.role_codes]
    for wid, fid, fcode, status, comp, api in wells:
        if status not in ("Producing", "ShutIn", "Completed"):
            continue
        # 4-12 tests over 3 years per producing well
        n = random.randint(4, 12)
        for _ in range(n):
            test_date = fake.date_between(start_date=max(comp, START_DATE), end_date=END_DATE)
            ttype = random.choice(["DST","PLT","BHP","Build-up"])
            flow = random.uniform(50, 2500)
            gas = random.uniform(50, 5000)
            water_cut = random.uniform(0, 60)
            bhp = random.uniform(800, 4500)
            op = random.choice(prod_engineers)
            rows.append((wid, isod(test_date), ttype, random.uniform(2, 72),
                         round(flow, 1), round(gas, 1), round(water_cut, 1), round(bhp, 1), op.user_id))
    c.executemany("""INSERT INTO well_tests(well_id,test_date,test_type,duration_hours,flow_rate_bopd,
                      gas_rate_mscfd,water_cut_pct,bhp_psi,operator_user_id)
                     VALUES(?,?,?,?,?,?,?,?,?)""", rows)


def seed_daily_production(c, wells, users):
    print("  -> daily_production (this is the big one - 3 years of daily data)")
    prod_engineers = [u for u in users if "PROD_ENG" in u.role_codes]
    validators = [u for u in users if "VALIDATOR" in u.role_codes or "PROD_ENG" in u.role_codes]
    rows = []
    for wid, fid, fcode, status, comp, api in wells:
        if status not in ("Producing","ShutIn","Suspended","Completed"):
            continue
        # Decline curve: initial rate decreases over time
        prod_start = max(comp, START_DATE)
        if prod_start >= END_DATE:
            continue
        days_producing = (END_DATE - prod_start).days
        ip_oil = random.uniform(150, 2500)   # initial production
        decline = random.uniform(0.0003, 0.0015)  # daily decline factor
        gas_oil_ratio = random.uniform(200, 2500)
        wc_start = random.uniform(0, 0.15)

        d = prod_start
        idx = 0
        while d <= END_DATE:
            if status == "ShutIn" and random.random() < 0.4:
                d += dt.timedelta(days=1); idx += 1; continue
            if status == "Suspended" and random.random() < 0.6:
                d += dt.timedelta(days=1); idx += 1; continue
            # Random downtime ~2% days
            runtime = 24.0
            if random.random() < 0.02:
                runtime = random.uniform(0, 18)
            oil = ip_oil * math.exp(-decline * idx) * (runtime / 24.0) * random.uniform(0.92, 1.08)
            gas = oil * gas_oil_ratio / 1000.0 * random.uniform(0.95, 1.05)
            water_cut = min(0.95, wc_start + (idx / max(days_producing, 1)) * 0.6)
            water = oil * water_cut / max(1 - water_cut, 0.05)
            reporter = random.choice(prod_engineers)
            validator = random.choice(validators) if random.random() < 0.92 else None
            rows.append((wid, isod(d), round(oil, 2), round(gas, 2), round(water, 2),
                         round(runtime, 2), random.choice([16,24,32,48,64,80]),
                         round(random.uniform(150, 2500), 1), round(random.uniform(50, 1800), 1),
                         reporter.user_id, validator.user_id if validator else None,
                         1 if validator else 0))
            d += dt.timedelta(days=1); idx += 1

    # Bulk insert in chunks
    print(f"     daily_production rows: {len(rows):,} ... inserting")
    chunk = 5000
    for i in range(0, len(rows), chunk):
        c.executemany("""INSERT INTO daily_production(well_id,production_date,oil_bbl,gas_mscf,water_bbl,
                          runtime_hours,choke_size_64ths,tubing_pressure_psi,casing_pressure_psi,
                          reported_by_user_id,validated_by_user_id,is_validated)
                         VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""", rows[i:i+chunk])


def seed_midstream_downstream(c, vendors, fields):
    print("  -> pipelines + segments")
    pipelines = []
    for code, name, prod, dia, length, cap, origin, dest in PIPELINE_DEFS:
        cur = c.execute("""INSERT INTO pipelines(pipeline_code,pipeline_name,product,diameter_in,length_km,
                            capacity_bbld,origin,destination,operator,commissioned_date)
                           VALUES(?,?,?,?,?,?,?,?,?,?)""",
                        (code, name, prod, dia, length, cap, origin, dest, "NorthStar Midstream",
                         isod(fake.date_between(start_date=dt.date(1985,1,1), end_date=dt.date(2015,1,1)))))
        pid = cur.lastrowid
        pipelines.append(pid)
        # 5-12 segments
        n_seg = random.randint(5, 12)
        seg_len = length / n_seg
        for s in range(n_seg):
            c.execute("""INSERT INTO pipeline_segments(pipeline_id,segment_number,start_km,end_km,material,
                          wall_thickness_mm,last_inspection_date,integrity_status)
                         VALUES(?,?,?,?,?,?,?,?)""",
                      (pid, s+1, round(s*seg_len,1), round((s+1)*seg_len,1),
                       random.choice(["X65 Steel","X70 Steel","API 5L X60","Carbon Steel"]),
                       round(random.uniform(8, 22), 1),
                       isod(fake.date_between(start_date=dt.date(2022,1,1), end_date=END_DATE)),
                       weighted_choice([("Good", 70), ("Monitoring", 22), ("Repair", 6), ("Replaced", 2)])))

    print("  -> storage_tanks")
    for i in range(20):
        c.execute("""INSERT INTO storage_tanks(tank_code,location,product,capacity_bbl,current_volume_bbl,
                      last_gauge_date,status)
                     VALUES(?,?,?,?,?,?,?)""",
                  (f"TANK-{i+1:03d}",
                   random.choice(["Cushing OK","Houston TX","Beaumont TX","Mont Belvieu TX","Patoka IL","Edmonton AB"]),
                   random.choice(["Crude","Gasoline","Diesel","JetA","NGL"]),
                   random.choice([100000, 250000, 500000, 750000, 1000000]),
                   round(random.uniform(50000, 900000), 1),
                   isod(fake.date_between(start_date=END_DATE - dt.timedelta(days=30), end_date=END_DATE)),
                   random.choice(["InService","Maintenance","Cleaning"])))

    print("  -> refineries + products")
    for code, name, loc, cap, ncx, comm in REFINERY_DEFS:
        c.execute("""INSERT INTO refineries(refinery_code,refinery_name,location,capacity_bpd,nelson_complexity,commissioned_date)
                     VALUES(?,?,?,?,?,?)""", (code, name, loc, cap, ncx, comm))
    products = []
    for code, name, cat, uom, sd in PRODUCT_DEFS:
        cur = c.execute("""INSERT INTO products(product_code,product_name,category,unit_of_measure,standard_density)
                           VALUES(?,?,?,?,?)""", (code, name, cat, uom, sd))
        products.append((cur.lastrowid, code))

    print("  -> crude_assays")
    inspection_vendors = [v for v in vendors if v[2] == "inspection"] or vendors
    for fid, fcode, api in fields:
        for _ in range(random.randint(6, 20)):
            v = random.choice(inspection_vendors)
            c.execute("""INSERT INTO crude_assays(field_id,sample_date,api_gravity,sulfur_pct,pour_point_c,
                          viscosity_cst,tan_mgkoh_g,salt_ptb,lab_vendor_id)
                         VALUES(?,?,?,?,?,?,?,?,?)""",
                      (fid, isod(fake.date_between(start_date=START_DATE, end_date=END_DATE)),
                       round(api + random.uniform(-1.5, 1.5), 2),
                       round(random.uniform(0.05, 3.5), 3),
                       round(random.uniform(-30, 15), 1),
                       round(random.uniform(2, 200), 2),
                       round(random.uniform(0.05, 2.5), 3),
                       round(random.uniform(0.5, 50), 2),
                       v[0]))
    return products


def seed_shipments(c, users, customers, contracts, products):
    print("  -> shipments")
    creators = [u for u in users if "OPS_MGR" in u.role_codes or "FINANCE_ANALYST" in u.role_codes]
    rows = []
    for k in range(350):
        cust_id, cust_name = random.choice(customers)
        prod_id, _ = random.choice(products)
        contract_id = random.choice(contracts) if contracts else None
        vol = random.uniform(50_000, 800_000)
        price = random.uniform(55, 95)  # USD per bbl
        bl_date = fake.date_between(start_date=START_DATE, end_date=END_DATE)
        eta = bl_date + dt.timedelta(days=random.randint(7, 45))
        actual = eta + dt.timedelta(days=random.choice([-2, -1, 0, 0, 0, 1, 2, 5]))
        rows.append((f"SHIP-{2023+random.randint(0,3)}-{k+1:05d}", contract_id, cust_id, prod_id,
                     round(vol, 1), round(price, 2), round(vol*price, 2), "USD",
                     random.choice(["Houston TX","Corpus Christi TX","Beaumont TX","Sullom Voe UK","Ras Tanura"]),
                     random.choice(["Rotterdam","Singapore","Yokohama","Mumbai","Ningbo","Algeciras","Houston"]),
                     fake.bothify(text="MV ?????? ##").upper(),
                     isod(bl_date), isod(eta), isod(actual) if actual <= END_DATE else None,
                     "Delivered" if actual <= END_DATE else "InTransit",
                     random.choice(creators).user_id))
    c.executemany("""INSERT INTO shipments(shipment_number,contract_id,customer_id,product_id,volume_bbl,price_per_bbl,
                      total_value,currency_code,load_port,discharge_port,vessel_name,bl_date,eta,actual_arrival,status,
                      created_by_user_id)
                     VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", rows)


def seed_equipment(c, wells):
    print("  -> equipment")
    eq_types = ["Pump","Compressor","Heater","Separator","Valve","Generator","Pig Launcher","Heat Exchanger"]
    rows = []
    for i in range(180):
        w = random.choice(wells) if random.random() < 0.7 else None
        rows.append((f"EQ-{i+1:05d}", random.choice(eq_types),
                     random.choice(["Caterpillar","Honeywell","Emerson","Schneider","ABB","Siemens","Sulzer","Flowserve"]),
                     fake.bothify(text="Model-####"), fake.bothify(text="SN??-#######"),
                     isod(fake.date_between(start_date=dt.date(2010,1,1), end_date=dt.date(2024,1,1))),
                     w[0] if w else None, None,
                     weighted_choice([("Low", 35), ("Medium", 40), ("High", 18), ("Critical", 7)]),
                     random.choice(["InService","Standby","Maintenance","OutOfService"]),
                     isod(fake.date_between(start_date=END_DATE, end_date=END_DATE + dt.timedelta(days=180)))))
    c.executemany("""INSERT INTO equipment(equipment_tag,equipment_type,manufacturer,model,serial_number,install_date,
                      location_well_id,location_refinery_id,criticality,status,next_pm_date)
                     VALUES(?,?,?,?,?,?,?,?,?,?,?)""", rows)


def seed_work_orders(c, users, wells, vendors):
    print("  -> work_orders")
    operators = [u for u in users if "FIELD_SUPERVISOR" in u.role_codes or "PROD_ENG" in u.role_codes or "OPS_MGR" in u.role_codes]
    rows = []
    for i in range(800):
        w = random.choice(wells) if random.random() < 0.6 else None
        wo_type = weighted_choice([("Preventive", 45), ("Corrective", 30), ("Emergency", 5), ("Inspection", 15), ("Project", 5)])
        prio = weighted_choice([("Low", 35), ("Medium", 40), ("High", 18), ("Critical", 7)])
        req_at = fake.date_time_between(start_date=START_DATE, end_date=END_DATE)
        status = weighted_choice([("Completed", 65), ("InProgress", 12), ("Open", 12), ("OnHold", 6), ("Cancelled", 5)])
        started = req_at + dt.timedelta(hours=random.randint(2, 96)) if status != "Open" else None
        completed = started + dt.timedelta(days=random.randint(1, 21)) if status == "Completed" else None
        est = random.uniform(500, 250000)
        actual = est * random.uniform(0.7, 1.4) if status == "Completed" else None
        req = random.choice(operators)
        assn = random.choice(operators)
        v = random.choice(vendors) if random.random() < 0.45 else None
        rows.append((f"WO-{i+1:06d}", None, w[0] if w else None, wo_type, prio,
                     fake.sentence(nb_words=10), req.user_id, assn.user_id,
                     v[0] if v else None, status, isod(req_at),
                     isod(started) if started else None,
                     isod(completed) if completed else None,
                     round(est, 2), round(actual, 2) if actual else None))
    c.executemany("""INSERT INTO work_orders(wo_number,equipment_id,well_id,wo_type,priority,description,
                      requested_by_user_id,assigned_to_user_id,vendor_id,status,requested_at,started_at,completed_at,
                      estimated_cost,actual_cost) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", rows)


def seed_inspections(c, users):
    print("  -> inspections")
    inspectors = [u for u in users if "FIELD_SUPERVISOR" in u.role_codes or "HSE_OFFICER" in u.role_codes or "OPS_MGR" in u.role_codes]
    eq_count = c.execute("SELECT COUNT(*) FROM equipment").fetchone()[0]
    seg_count = c.execute("SELECT COUNT(*) FROM pipeline_segments").fetchone()[0]
    rows = []
    for _ in range(1200):
        if random.random() < 0.65:
            eq_id = random.randint(1, eq_count)
            seg_id = None
        else:
            eq_id = None
            seg_id = random.randint(1, seg_count)
        idate = fake.date_between(start_date=START_DATE, end_date=END_DATE)
        sev = weighted_choice([("None", 50), ("Low", 28), ("Medium", 15), ("High", 5), ("Critical", 2)])
        rows.append((eq_id, seg_id, isod(idate),
                     random.choice(["Visual","Ultrasonic","Magnetic Particle","Radiographic","Routine PM","API 510","API 570"]),
                     random.choice(inspectors).user_id,
                     fake.sentence(nb_words=12), sev,
                     isod(idate + dt.timedelta(days=random.choice([90, 180, 365]))), None))
    c.executemany("""INSERT INTO inspections(equipment_id,pipeline_segment_id,inspection_date,inspection_type,
                      inspector_user_id,finding_summary,finding_severity,next_inspection_date,report_external_link_id)
                     VALUES(?,?,?,?,?,?,?,?,?)""", rows)


def seed_incidents(c, users, wells):
    print("  -> incidents")
    hse_off = [u for u in users if "HSE_OFFICER" in u.role_codes]
    hse_mgr = [u for u in users if "HSE_MGR" in u.role_codes]
    field_sup = [u for u in users if "FIELD_SUPERVISOR" in u.role_codes]
    rows = []
    for i in range(180):
        occurred = fake.date_time_between(start_date=START_DATE, end_date=END_DATE)
        w = random.choice(wells) if random.random() < 0.65 else None
        itype = random.choices(INCIDENT_TYPES, weights=INCIDENT_WEIGHTS, k=1)[0]
        sev = weighted_choice([("SIF1", 55), ("SIF2", 22), ("SIF3", 13), ("SIF4", 7), ("SIF5", 3)])
        reporter = random.choice(field_sup + hse_off)
        invest = random.choice(hse_mgr) if hse_mgr else random.choice(hse_off)
        closed = occurred + dt.timedelta(days=random.randint(7, 180)) if random.random() < 0.78 else None
        rows.append((f"INC-{2023+random.randint(0,3)}-{i+1:05d}", isod(occurred),
                     fake.address().split("\n")[0], w[0] if w else None, None,
                     itype, sev, fake.paragraph(nb_sentences=2),
                     reporter.user_id, invest.user_id,
                     fake.sentence(nb_words=10), fake.sentence(nb_words=12),
                     isod(closed) if closed else None,
                     round(random.uniform(0, 2_500_000), 2)))
    c.executemany("""INSERT INTO incidents(incident_number,occurred_at,location,well_id,refinery_id,incident_type,
                      severity,description,reported_by_user_id,investigated_by_user_id,root_cause,corrective_actions,
                      closed_at,cost_estimate)
                     VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", rows)


def seed_environmental_readings(c, users, wells):
    print("  -> environmental_readings")
    hse = [u for u in users if "HSE_OFFICER" in u.role_codes or "HSE_MGR" in u.role_codes]
    rows = []
    # Sample weekly per well per parameter
    for wid, *_ in wells[:15]:   # cap to first 15 wells to keep volume reasonable
        d = START_DATE
        while d <= END_DATE:
            for param, unit, baseline, threshold in ENV_PARAMS:
                val = baseline * random.uniform(0.6, 1.4)
                if random.random() < 0.03:
                    val = threshold * random.uniform(1.05, 1.6)
                rows.append((fake.address().split("\n")[0], wid, isod(d), param,
                             round(val, 3), unit, threshold,
                             1 if val > threshold else 0,
                             fake.bothify(text="SENS-####"),
                             random.choice(hse).user_id))
            d += dt.timedelta(days=7)
    print(f"     environmental_readings rows: {len(rows):,}")
    chunk = 5000
    for i in range(0, len(rows), chunk):
        c.executemany("""INSERT INTO environmental_readings(location,well_id,reading_date,parameter,value,unit,
                          threshold,is_exceedance,sensor_tag,recorded_by_user_id)
                         VALUES(?,?,?,?,?,?,?,?,?,?)""", rows[i:i+chunk])


def seed_finance(c, users, customers, vendors, contracts, products, wf_id, dept_id):
    print("  -> cost_centers + exchange_rates")
    cc_ids = []
    for dcode, did in dept_id.items():
        cur = c.execute("""INSERT INTO cost_centers(cc_code,cc_name,department_id,is_active)
                           VALUES(?,?,?,?)""", (f"CC-{dcode}", f"Cost Center {dcode}", did, 1))
        cc_ids.append(cur.lastrowid)
    # exchange rates daily for major pairs
    pairs = [("USD","EUR"),("USD","GBP"),("USD","CAD"),("USD","JPY"),("USD","NOK"),("USD","AED"),("USD","SGD")]
    rate_baselines = {"EUR":0.93,"GBP":0.79,"CAD":1.36,"JPY":150.0,"NOK":10.5,"AED":3.67,"SGD":1.34}
    rate_rows = []
    d = START_DATE
    while d <= END_DATE:
        for fr, to in pairs:
            base = rate_baselines[to]
            rate_rows.append((fr, to, isod(d), round(base * random.uniform(0.93, 1.07), 5), "ECB"))
        d += dt.timedelta(days=1)
    print(f"     exchange_rates rows: {len(rate_rows):,}")
    chunk = 5000
    for i in range(0, len(rate_rows), chunk):
        c.executemany("""INSERT INTO exchange_rates(from_currency,to_currency,rate_date,rate,source)
                         VALUES(?,?,?,?,?)""", rate_rows[i:i+chunk])

    print("  -> invoices + invoice_items + payments + approval_requests + approval_actions")
    creators = [u for u in users if "FINANCE_ANALYST" in u.role_codes]
    validators = [u for u in users if "VALIDATOR" in u.role_codes]
    fin_mgrs = [u for u in users if "FINANCE_MGR" in u.role_codes]
    cfos = [u for u in users if "CFO" in u.role_codes]
    ceos = [u for u in users if "CEO" in u.role_codes]

    inv_rows = 600
    for i in range(inv_rows):
        inv_type = random.choice(["AR","AP"])
        cust_id, vend_id = (None, None)
        contract_id = None
        if inv_type == "AR":
            cust_id = random.choice(customers)[0]
        else:
            vend_id = random.choice(vendors)[0]
        if contracts and random.random() < 0.6:
            contract_id = random.choice(contracts)
        cc_id = random.choice(cc_ids)
        invoice_date = fake.date_between(start_date=START_DATE, end_date=END_DATE)
        due_date = invoice_date + dt.timedelta(days=random.choice([15, 30, 45, 60]))
        n_items = random.randint(1, 5)
        subtotal = 0.0
        items = []
        for ln in range(1, n_items+1):
            qty = random.uniform(50, 50000)
            price = random.uniform(20, 250)
            line = qty * price
            subtotal += line
            prod_id, _ = random.choice(products) if random.random() < 0.6 else (None, None)
            items.append((ln, fake.bs().capitalize(), prod_id, round(qty, 2), round(price, 2), round(line, 2), None))
        tax = subtotal * random.choice([0, 0, 0, 0.05, 0.0825, 0.20])
        total = subtotal + tax
        # workflow selection
        if total < 50000:
            wf_code = "WF-INV-LOW"
            chain_status = weighted_choice([("Approved", 70), ("Submitted", 12), ("InReview", 8), ("Rejected", 5), ("Cancelled", 5)])
        elif total < 250000:
            wf_code = "WF-INV-MED"
            chain_status = weighted_choice([("Approved", 65), ("InReview", 15), ("Submitted", 10), ("Rejected", 7), ("Cancelled", 3)])
        else:
            wf_code = "WF-INV-HIGH"
            chain_status = weighted_choice([("Approved", 55), ("InReview", 22), ("Submitted", 12), ("Rejected", 8), ("Cancelled", 3)])
        creator = random.choice(creators)
        validator = random.choice(validators) if validators else None
        approver = random.choice(fin_mgrs)
        # Create approval_request
        submitted = invoice_date + dt.timedelta(days=random.randint(0, 5))
        completed = submitted + dt.timedelta(days=random.randint(1, 14)) if chain_status in ("Approved","Rejected","Cancelled") else None
        cur = c.execute("""INSERT INTO approval_requests(workflow_id,entity_type,entity_id,title,description,amount,
                            currency_code,creator_id,validator_id,final_approver_id,current_step,status,
                            submitted_at,completed_at,due_at,created_at,updated_at)
                           VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                        (wf_id[wf_code], "invoice", i+1,
                         f"Invoice approval - {inv_type} {round(total,0)}", "Auto-generated",
                         round(total, 2), "USD",
                         creator.user_id, validator.user_id if validator else None,
                         (random.choice(cfos).user_id if total > 250000 else approver.user_id),
                         random.randint(1, 4), chain_status,
                         isod(submitted), isod(completed) if completed else None,
                         isod(submitted + dt.timedelta(days=14)),
                         isod(submitted), isod(completed if completed else submitted)))
        ar_id = cur.lastrowid

        # invoice
        inv_status = {
            "Approved": weighted_choice([("Paid", 60), ("PartiallyPaid", 15), ("Overdue", 10), ("Approved", 15)]),
            "Submitted": "Submitted",
            "InReview": "Submitted",
            "Rejected": "Cancelled",
            "Cancelled": "Cancelled",
        }[chain_status]
        cur = c.execute("""INSERT INTO invoices(invoice_number,invoice_type,customer_id,vendor_id,contract_id,cost_center_id,
                            invoice_date,due_date,subtotal,tax_amount,total_amount,currency_code,status,
                            created_by_user_id,approved_by_user_id,approval_request_id,notes,created_at)
                           VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                        (f"INV-{2023+random.randint(0,3)}-{i+1:06d}", inv_type, cust_id, vend_id, contract_id, cc_id,
                         isod(invoice_date), isod(due_date), round(subtotal, 2), round(tax, 2), round(total, 2),
                         "USD", inv_status, creator.user_id,
                         approver.user_id if chain_status == "Approved" else None,
                         ar_id, fake.sentence(nb_words=8), isod(invoice_date)))
        invoice_id = cur.lastrowid
        for ln, desc, pid, qty, price, line, _ in items:
            c.execute("""INSERT INTO invoice_items(invoice_id,line_number,description,product_id,quantity,unit_price,line_total,well_id)
                         VALUES(?,?,?,?,?,?,?,?)""", (invoice_id, ln, desc, pid, qty, price, line, None))

        # approval actions chain
        c.execute("""INSERT INTO approval_actions(request_id,actor_id,action,comment,occurred_at)
                     VALUES(?,?,?,?,?)""",
                  (ar_id, creator.user_id, "Submit", "Submitted for approval", isod(submitted)))
        if validator and chain_status not in ("Cancelled",):
            c.execute("""INSERT INTO approval_actions(request_id,actor_id,action,comment,occurred_at)
                         VALUES(?,?,?,?,?)""",
                      (ar_id, validator.user_id, "Validate", "Data verified",
                       isod(submitted + dt.timedelta(days=1))))
        if chain_status == "Approved":
            c.execute("""INSERT INTO approval_actions(request_id,actor_id,action,comment,occurred_at)
                         VALUES(?,?,?,?,?)""",
                      (ar_id, approver.user_id, "Approve", "Approved by Finance",
                       isod(submitted + dt.timedelta(days=2))))
            if total > 250000 and cfos:
                c.execute("""INSERT INTO approval_actions(request_id,actor_id,action,comment,occurred_at)
                             VALUES(?,?,?,?,?)""",
                          (ar_id, cfos[0].user_id, "Approve", "CFO sign-off",
                           isod(submitted + dt.timedelta(days=3))))
            if total > 1_000_000 and ceos:
                c.execute("""INSERT INTO approval_actions(request_id,actor_id,action,comment,occurred_at)
                             VALUES(?,?,?,?,?)""",
                          (ar_id, ceos[0].user_id, "Approve", "CEO sign-off",
                           isod(submitted + dt.timedelta(days=4))))
        elif chain_status == "Rejected":
            c.execute("""INSERT INTO approval_actions(request_id,actor_id,action,comment,occurred_at)
                         VALUES(?,?,?,?,?)""",
                      (ar_id, approver.user_id, "Reject", "Rejected - missing info",
                       isod(submitted + dt.timedelta(days=2))))

        # payments for paid invoices
        if inv_status in ("Paid","PartiallyPaid"):
            paid_amount = total if inv_status == "Paid" else total * random.uniform(0.3, 0.8)
            pay_date = due_date + dt.timedelta(days=random.choice([-10, -3, 0, 5, 12, 25]))
            if pay_date <= END_DATE:
                c.execute("""INSERT INTO payments(invoice_id,payment_date,amount,currency_code,payment_method,reference,received_by_user_id)
                             VALUES(?,?,?,?,?,?,?)""",
                          (invoice_id, isod(pay_date), round(paid_amount, 2), "USD",
                           random.choice(["Wire","ACH","Check","Card"]), fake.bothify(text="REF-#########"),
                           random.choice(creators).user_id))


def seed_purchase_orders(c, users, vendors, products, wf_id, dept_id):
    print("  -> purchase_orders + po_items")
    creators = [u for u in users if "FINANCE_ANALYST" in u.role_codes or "PROCUREMENT_MGR" in u.role_codes]
    proc_mgrs = [u for u in users if "PROCUREMENT_MGR" in u.role_codes]
    cfos = [u for u in users if "CFO" in u.role_codes]
    ceos = [u for u in users if "CEO" in u.role_codes]
    cc_count = c.execute("SELECT COUNT(*) FROM cost_centers").fetchone()[0]

    for k in range(450):
        vid = random.choice(vendors)[0]
        cc_id = random.randint(1, cc_count)
        creator = random.choice(creators)
        pm = random.choice(proc_mgrs)
        issue_date = fake.date_between(start_date=START_DATE, end_date=END_DATE)
        expected = issue_date + dt.timedelta(days=random.randint(14, 90))
        n_items = random.randint(1, 6)
        total = 0.0
        items = []
        for ln in range(1, n_items+1):
            qty = random.uniform(10, 5000)
            price = random.uniform(15, 1500)
            line = qty * price
            total += line
            prod_id = random.choice(products)[0] if random.random() < 0.5 else None
            items.append((ln, fake.bs().capitalize(), prod_id, round(qty, 2), round(price, 2), round(line, 2)))
        if total < 100000:
            wf_code = "WF-PO-LOW"
            status = weighted_choice([("Closed", 55), ("PartiallyReceived", 15), ("Approved", 15), ("PendingApproval", 8), ("Rejected", 5), ("Cancelled", 2)])
        else:
            wf_code = "WF-PO-HIGH"
            status = weighted_choice([("Closed", 45), ("PartiallyReceived", 18), ("Approved", 17), ("PendingApproval", 12), ("Rejected", 6), ("Cancelled", 2)])

        approver = pm if total < 100000 else (random.choice(cfos) if cfos else pm)
        submitted = issue_date
        ar_status = {"Closed":"Approved","PartiallyReceived":"Approved","Approved":"Approved","PendingApproval":"InReview","Rejected":"Rejected","Cancelled":"Cancelled","Draft":"Draft"}.get(status, "Approved")
        completed = submitted + dt.timedelta(days=random.randint(1, 10)) if ar_status in ("Approved","Rejected","Cancelled") else None
        cur = c.execute("""INSERT INTO approval_requests(workflow_id,entity_type,entity_id,title,description,amount,currency_code,
                            creator_id,final_approver_id,current_step,status,submitted_at,completed_at,due_at,created_at,updated_at)
                           VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                        (wf_id[wf_code], "purchase_order", k+1, f"PO Approval {round(total,0)}", "PO routing",
                         round(total, 2), "USD", creator.user_id,
                         approver.user_id, random.randint(1,3), ar_status,
                         isod(submitted), isod(completed) if completed else None,
                         isod(submitted + dt.timedelta(days=10)),
                         isod(submitted), isod(completed if completed else submitted)))
        ar_id = cur.lastrowid
        cur = c.execute("""INSERT INTO purchase_orders(po_number,vendor_id,cost_center_id,requested_by_user_id,approved_by_user_id,
                            approval_request_id,issue_date,expected_date,total_amount,currency_code,status,notes)
                           VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
                        (f"PO-{2023+random.randint(0,3)}-{k+1:06d}", vid, cc_id, creator.user_id,
                         approver.user_id if status not in ("PendingApproval","Rejected","Cancelled","Draft") else None,
                         ar_id, isod(issue_date), isod(expected), round(total, 2), "USD", status,
                         fake.sentence(nb_words=10)))
        po_id = cur.lastrowid
        for ln, desc, pid, qty, price, line in items:
            received = qty if status == "Closed" else (qty * random.uniform(0.3, 0.85) if status == "PartiallyReceived" else 0)
            c.execute("""INSERT INTO po_items(po_id,line_number,description,product_id,quantity,unit_price,line_total,received_qty)
                         VALUES(?,?,?,?,?,?,?,?)""", (po_id, ln, desc, pid, qty, price, line, round(received, 2)))


def seed_permits(c, users, fields):
    print("  -> permits")
    holders = [u for u in users if "HSE_MGR" in u.role_codes or "LEGAL_COUNSEL" in u.role_codes or "OPS_MGR" in u.role_codes]
    well_count = c.execute("SELECT COUNT(*) FROM wells").fetchone()[0]
    rows = []
    for i in range(120):
        ptype = random.choice(["Drilling","Environmental","Pipeline","Construction","Operating"])
        issued = fake.date_between(start_date=dt.date(2018,1,1), end_date=END_DATE)
        expiry = issued + dt.timedelta(days=random.choice([180, 365, 730, 1825]))
        status = "Active" if expiry > END_DATE else random.choice(["Expired","Active","Revoked"])
        wid = random.randint(1, well_count) if random.random() < 0.7 else None
        fid = random.choice(fields)[0]
        rows.append((f"PMT-{2023+random.randint(0,3)}-{i+1:05d}", ptype,
                     random.choice(["EPA","TCEQ","BLM","BSEE","Alberta AER","UK NSTA","NORSOK","ADNOC"]),
                     wid, fid, isod(issued), isod(expiry), status,
                     random.choice(holders).user_id,
                     round(random.uniform(5_000, 250_000), 2),
                     fake.sentence(nb_words=10)))
    c.executemany("""INSERT INTO permits(permit_number,permit_type,issuing_authority,well_id,field_id,issued_date,
                      expiry_date,status,holder_user_id,fee_paid,notes)
                     VALUES(?,?,?,?,?,?,?,?,?,?,?)""", rows)


def seed_external_links(c):
    print("  -> external_links + document_references")
    well_count = c.execute("SELECT COUNT(*) FROM wells").fetchone()[0]
    inv_count = c.execute("SELECT COUNT(*) FROM invoices").fetchone()[0]
    contract_count = c.execute("SELECT COUNT(*) FROM contracts").fetchone()[0]
    incident_count = c.execute("SELECT COUNT(*) FROM incidents").fetchone()[0]
    inspection_count = c.execute("SELECT COUNT(*) FROM inspections").fetchone()[0]

    rows = []
    # SCADA links for wells
    for wid in range(1, well_count+1):
        for sys_code, sys_name, base in EXTERNAL_SYSTEMS[:3]:
            if random.random() < 0.7:
                rows.append(("well", wid, sys_code, sys_name, f"{base}well/{wid}",
                             f"EXT-{sys_code}-{wid:06d}",
                             isod(fake.date_time_between(start_date=END_DATE - dt.timedelta(days=2), end_date=END_DATE)), 1))
    # ERP links for invoices
    for iid in range(1, min(inv_count+1, 600)):
        rows.append(("invoice", iid, "ERP", "SAP S/4HANA", f"https://sap.northstar-petro.com/object/INV/{iid}",
                     f"SAP-{iid:08d}", isod(fake.date_time_between(start_date=END_DATE - dt.timedelta(days=7), end_date=END_DATE)), 1))
    # SharePoint for contracts
    for cid in range(1, contract_count+1):
        rows.append(("contract", cid, "SharePoint", "MS SharePoint",
                     f"https://northstar.sharepoint.com/sites/legal/Contracts/Contract_{cid}.pdf",
                     f"SP-{cid:08d}", isod(fake.date_time_between(start_date=END_DATE - dt.timedelta(days=14), end_date=END_DATE)), 1))
    # CMMS for incidents
    for iid in range(1, incident_count+1):
        if random.random() < 0.65:
            rows.append(("incident", iid, "CMMS", "IBM Maximo", f"https://maximo.northstar-petro.com/incident/{iid}",
                         f"MAX-{iid:08d}", isod(fake.date_time_between(start_date=END_DATE - dt.timedelta(days=30), end_date=END_DATE)), 1))

    print(f"     external_links rows: {len(rows):,}")
    chunk = 5000
    for i in range(0, len(rows), chunk):
        c.executemany("""INSERT INTO external_links(entity_type,entity_id,link_type,system_name,url,external_id,last_synced_at,is_active)
                         VALUES(?,?,?,?,?,?,?,?)""", rows[i:i+chunk])

    # document_references
    drows = []
    for cid in range(1, contract_count+1):
        drows.append(("contract", cid, f"Contract_{cid}.pdf", "Contract",
                      f"s3://northstar-docs/contracts/{cid}.pdf",
                      random.randint(50_000, 5_000_000), "application/pdf",
                      random.randint(2, 30), isod(fake.date_time_between(start_date=START_DATE, end_date=END_DATE)),
                      1 if random.random() < 0.6 else 0))
    for insp in range(1, min(inspection_count+1, 500)):
        drows.append(("inspection", insp, f"Inspection_{insp}_Report.pdf", "InspectionReport",
                      f"s3://northstar-docs/inspections/{insp}.pdf",
                      random.randint(20_000, 2_000_000), "application/pdf",
                      random.randint(2, 30), isod(fake.date_time_between(start_date=START_DATE, end_date=END_DATE)), 0))
    print(f"     document_references rows: {len(drows):,}")
    chunk = 5000
    for i in range(0, len(drows), chunk):
        c.executemany("""INSERT INTO document_references(entity_type,entity_id,document_name,document_type,storage_uri,
                          file_size_bytes,mime_type,uploaded_by_user_id,uploaded_at,is_confidential)
                         VALUES(?,?,?,?,?,?,?,?,?,?)""", drows[i:i+chunk])


def seed_audit_log(c, users):
    print("  -> audit_log")
    rows = []
    actions = ["INSERT","UPDATE","DELETE","APPROVE","REJECT"]
    entities = ["invoices","purchase_orders","wells","contracts","incidents","permits","approval_requests","work_orders"]
    for _ in range(8000):
        u = random.choice(users)
        rows.append((u.user_id, random.choice(entities), random.randint(1, 600),
                     random.choice(actions), None, None,
                     fake.ipv4(),
                     isod(fake.date_time_between(start_date=START_DATE, end_date=END_DATE))))
    chunk = 5000
    for i in range(0, len(rows), chunk):
        c.executemany("""INSERT INTO audit_log(actor_user_id,entity_type,entity_id,action,old_value,new_value,ip_address,occurred_at)
                         VALUES(?,?,?,?,?,?,?,?)""", rows[i:i+chunk])


def seed_notifications(c, users):
    print("  -> notifications")
    rows = []
    for _ in range(2500):
        u = random.choice(users)
        sent = fake.date_time_between(start_date=START_DATE, end_date=END_DATE)
        is_read = random.random() < 0.78
        rows.append((u.user_id, random.choice(["Email","Push","InApp","SMS"]),
                     random.choice(["Approval pending","PO approved","Incident closed","Production validated","Contract expiring"]),
                     fake.sentence(nb_words=12),
                     random.choice(["invoice","purchase_order","incident","contract"]),
                     random.randint(1, 600),
                     1 if is_read else 0, isod(sent),
                     isod(sent + dt.timedelta(hours=random.randint(1, 72))) if is_read else None))
    chunk = 5000
    for i in range(0, len(rows), chunk):
        c.executemany("""INSERT INTO notifications(recipient_user_id,channel,subject,body,
                          related_entity_type,related_entity_id,is_read,sent_at,read_at)
                         VALUES(?,?,?,?,?,?,?,?,?)""", rows[i:i+chunk])


def seed_delegations(c, users):
    print("  -> delegations")
    for _ in range(40):
        delegator = random.choice(users)
        delegate = random.choice([u for u in users if u.user_id != delegator.user_id])
        starts = fake.date_between(start_date=START_DATE, end_date=END_DATE - dt.timedelta(days=14))
        ends = starts + dt.timedelta(days=random.randint(7, 30))
        c.execute("""INSERT INTO delegations(delegator_id,delegate_id,scope,reason,starts_at,ends_at,is_active)
                     VALUES(?,?,?,?,?,?,?)""",
                  (delegator.user_id, delegate.user_id,
                   random.choice(["all","approvals","signing"]),
                   random.choice(["Vacation","Conference","Medical leave","Training"]),
                   isod(starts), isod(ends), 1 if ends > END_DATE else 0))


# =====================================================================
# Main
# =====================================================================

def main():
    t0 = dt.datetime.now()
    print(f"Seeding NorthStar Petroleum DB at {DB_PATH}")
    print(f"Date window: {START_DATE} -> {END_DATE} (3 years)\n")

    conn = init_db()
    c = conn.cursor()

    role_id, perm_id = seed_roles_perms(c)
    dept_id = seed_departments(c)
    users = seed_users(c, role_id, dept_id)
    seed_employees(c, users, dept_id)
    seed_login_audit(c, users)
    seed_user_sessions(c, users)
    seed_delegations(c, users)
    wf_id = seed_approval_workflows(c, role_id)

    customers, vendors, contracts = seed_customers_vendors_contracts(c, users)
    fields, wells = seed_upstream(c, users)
    seed_drilling(c, users, wells, vendors)
    seed_well_completions(c, wells, vendors)
    seed_well_tests(c, wells, users)
    seed_daily_production(c, wells, users)
    products = seed_midstream_downstream(c, vendors, fields)
    seed_shipments(c, users, customers, contracts, products)
    seed_equipment(c, wells)
    seed_work_orders(c, users, wells, vendors)
    seed_inspections(c, users)
    seed_incidents(c, users, wells)
    seed_environmental_readings(c, users, wells)
    seed_finance(c, users, customers, vendors, contracts, products, wf_id, dept_id)
    seed_purchase_orders(c, users, vendors, products, wf_id, dept_id)
    seed_permits(c, users, fields)
    seed_external_links(c)
    seed_audit_log(c, users)
    seed_notifications(c, users)

    conn.commit()

    # Print summary
    print("\n" + "=" * 60)
    print("SEED COMPLETE - Row counts")
    print("=" * 60)
    tables = [r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name").fetchall()]
    grand = 0
    for t in tables:
        n = c.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
        grand += n
        print(f"  {t:35s} {n:>10,}")
    print("-" * 60)
    print(f"  {'TOTAL':35s} {grand:>10,}")
    print(f"  Tables: {len(tables)}")
    print(f"  Elapsed: {(dt.datetime.now()-t0).total_seconds():.1f}s")
    print(f"  DB size: {DB_PATH.stat().st_size/1024/1024:.1f} MB")
    conn.close()


if __name__ == "__main__":
    main()
