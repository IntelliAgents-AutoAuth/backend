import sqlite3
from pathlib import Path

backend_root = Path(__file__).resolve().parents[2]
db_path = backend_root / "data" / "autoauth.db"
conn = sqlite3.connect(db_path)
cursor = conn.cursor()

print("--- ALL TABLES ---")
cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
tables = [t[0] for t in cursor.fetchall()]
print(tables)

for table in tables:
    print(f"\n--- {table} (first row) ---")
    cursor.execute(f"PRAGMA table_info({table})")
    cols = [c[1] for c in cursor.fetchall()]
    print(f"Columns: {cols}")
    cursor.execute(f"SELECT * FROM {table} LIMIT 1")
    print(cursor.fetchone())

conn.close()
