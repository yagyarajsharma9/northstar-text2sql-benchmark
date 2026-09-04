import sqlite3
c = sqlite3.connect("C:/Users/Administrator/Desktop/Aiwrapper/database/oilgas.db")
n_total = c.execute("SELECT COUNT(*) FROM drilling_operations").fetchone()[0]
n_start_2025 = c.execute(
    "SELECT COUNT(*) FROM drilling_operations WHERE start_date BETWEEN '2025-01-01' AND '2025-12-31'"
).fetchone()[0]
n_end_2025 = c.execute(
    "SELECT COUNT(*) FROM drilling_operations WHERE end_date BETWEEN '2025-01-01' AND '2025-12-31'"
).fetchone()[0]
n_overlap_2025 = c.execute(
    "SELECT COUNT(*) FROM drilling_operations "
    "WHERE start_date <= '2025-12-31' AND end_date >= '2025-01-01'"
).fetchone()[0]
print(f"drilling_operations total: {n_total}")
print(f"  start_date in 2025: {n_start_2025}")
print(f"  end_date in 2025:   {n_end_2025}")
print(f"  overlap with 2025:  {n_overlap_2025}")
