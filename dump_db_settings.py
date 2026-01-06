import sqlite3
import sys
from pathlib import Path

# Setup path
PROJECT_ROOT = Path(__file__).resolve().parent
DB_FILE = PROJECT_ROOT / "users.db"

def dump_settings():
    print(f"Checking database at: {DB_FILE}")
    try:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        
        # Check settings
        print("\n--- SETTINGS TABLE ---")
        try:
            cursor.execute("SELECT key, value FROM settings")
            rows = cursor.fetchall()
            for key, value in rows:
                print(f"{key}: {value}")
        except Exception as e:
            print(f"Error reading settings: {e}")

        # Check button_configs if exists
        print("\n--- BUTTON_CONFIGS TABLE ---")
        try:
            cursor.execute("SELECT menu_type, button_id, text, callback_data, url FROM button_configs")
            rows = cursor.fetchall()
            for row in rows:
                print(row)
        except Exception as e:
            print(f"Error reading button_configs: {e}")
            
        conn.close()
    except Exception as e:
        print(f"Database error: {e}")

if __name__ == "__main__":
    dump_settings()
