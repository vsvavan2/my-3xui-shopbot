import sqlite3
import sys
from pathlib import Path

# Use the same path resolution as the main app
PROJECT_ROOT = Path(__file__).resolve().parent
DB_FILE = PROJECT_ROOT / "users.db"

def dump_buttons():
    if not DB_FILE.exists():
        print(f"DB file not found: {DB_FILE}")
        return

    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    try:
        cursor.execute("SELECT * FROM button_configs WHERE menu_type='main_menu'")
        columns = [description[0] for description in cursor.description]
        print(f"Columns: {columns}")
        
        rows = cursor.fetchall()
        for row in rows:
            print(dict(zip(columns, row)))

        print("\n--- Settings ---")
        cursor.execute("SELECT key, value FROM settings WHERE key LIKE 'btn_%'")
        settings = cursor.fetchall()
        for k, v in settings:
            print(f"{k}: {v}")
            
    except Exception as e:
        print(f"Error: {e}")
    finally:
        conn.close()

if __name__ == "__main__":
    print("STARTING DUMP", flush=True)
    dump_buttons()
