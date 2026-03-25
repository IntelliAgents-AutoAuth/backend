import sqlite3
import os

# Calculate paths
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(BASE_DIR, 'data', 'autoauth.db')

def migrate():
    print(f"Connecting to database: {DB_PATH}")
    if not os.path.exists(DB_PATH):
        print("Database file not found. Creating a new one...")
        # main.py will handle creation via Base.metadata.create_all
        return

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # List of columns to add with their types
    columns_to_add = [
        ("patient_name", "VARCHAR(150)"),
        ("total_required", "INTEGER"),
        ("total_matched", "INTEGER"),
        ("total_missing", "INTEGER"),
        ("gap_percentage", "FLOAT"),
        ("eligibility_result", "JSON"),
        ("eligibility_verdict", "VARCHAR(30)")
    ]

    for col_name, col_type in columns_to_add:
        try:
            print(f"Adding column '{col_name}' to 'cases' table...")
            cursor.execute(f"ALTER TABLE cases ADD COLUMN {col_name} {col_type}")
            print(f"[OK] Added {col_name}")
        except sqlite3.OperationalError as e:
            if "duplicate column name" in str(e):
                print(f"[INFO] Column '{col_name}' already exists.")
            else:
                print(f"[ERROR] Failed to add {col_name}: {e}")

    conn.commit()
    conn.close()
    print("Migration complete!")

if __name__ == "__main__":
    migrate()
