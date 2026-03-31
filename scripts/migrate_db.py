import sqlite3
import os

def migrate():
    # Database path relative to this script
    current_dir = os.path.dirname(os.path.abspath(__file__))
    backend_dir = os.path.dirname(current_dir)
    db_path = os.path.abspath(os.path.join(backend_dir, "data", "autoauth.db"))

    if not os.path.exists(db_path):
        print(f"Error: Database not found at {db_path}")
        return

    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        print(f"Checking database schema for: {db_path}")
        
        # Add confidence_score column
        try:
            cursor.execute("ALTER TABLE cases ADD COLUMN confidence_score FLOAT")
            print("✅ Added column: confidence_score")
        except sqlite3.OperationalError as e:
            if "duplicate column name" in str(e).lower():
                pass # Already exists
            else:
                print(f"⚠️ Column error: {e}")

        # Add auto_submit_reason column
        try:
            cursor.execute("ALTER TABLE cases ADD COLUMN auto_submit_reason VARCHAR(255)")
            print("✅ Added column: auto_submit_reason")
        except sqlite3.OperationalError as e:
            if "duplicate column name" in str(e).lower():
                pass # Already exists
            else:
                print(f"⚠️ Column error: {e}")
                
        conn.commit()
        conn.close()
        print("🚀 Database schema check complete!")
        
    except Exception as e:
        print(f"❌ Error updating database: {e}")

if __name__ == "__main__":
    migrate()
