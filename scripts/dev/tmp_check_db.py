import sqlite3, os
from pathlib import Path

def check_db(db_path):
    print(f"--- Checking {db_path} ---")
    if not os.path.exists(db_path):
        print(f"File {db_path} NOT FOUND")
        return
        
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # List tables
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = [t[0] for t in cursor.fetchall()]
    print(f"Tables: {tables}")
    
    for table in ["ehr_records", "extracted_data", "cases"]:
        if table in tables:
            print(f"\nTable: {table}")
            cursor.execute(f"SELECT * FROM {table} LIMIT 2")
            rows = cursor.fetchall()
            # Get column names
            cursor.execute(f"PRAGMA table_info({table})")
            cols = [c[1] for c in cursor.fetchall()]
            print(f"Columns: {cols}")
            for row in rows:
                print(row)
        else:
            print(f"Table {table} not found")
            
    conn.close()

if __name__ == "__main__":
    backend_root = Path(__file__).resolve().parents[2]
    check_db(str(backend_root / "data" / "autoauth.db"))
    check_db(str(backend_root / "app.db"))
