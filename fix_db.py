import sqlite3
import logging
import sys
from pathlib import Path

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Path to DB
PROJECT_ROOT = Path(__file__).resolve().parent
DB_FILE = PROJECT_ROOT / "users.db"

def fix_database():
    print(f"Checking database at {DB_FILE}...")
    
    if not DB_FILE.exists():
        print("Database file not found!")
        return

    try:
        with sqlite3.connect(DB_FILE) as conn:
            cursor = conn.cursor()
            
            # 1. Check vpn_keys schema
            print("Checking vpn_keys schema...")
            cursor.execute("PRAGMA table_info(vpn_keys)")
            columns = [info[1] for info in cursor.fetchall()]
            
            if 'email' in columns and 'key_email' not in columns:
                print("Migrating 'email' column to 'key_email'...")
                cursor.execute("ALTER TABLE vpn_keys RENAME COLUMN email TO key_email")
                conn.commit()
                print("Column renamed.")
            elif 'key_email' not in columns:
                print("WARNING: 'key_email' column missing and 'email' column not found.")
                # You might want to add it, but it's better to inspect manually if it's a very old DB
            
            if 'uuid' in columns and 'xui_client_uuid' not in columns:
                 print("Migrating 'uuid' column to 'xui_client_uuid'...")
                 cursor.execute("ALTER TABLE vpn_keys RENAME COLUMN uuid TO xui_client_uuid")
                 conn.commit()
                 print("Column renamed.")

            # 2. Reset button configs
            print("Resetting button configurations...")
            cursor.execute("DELETE FROM button_configs")
            conn.commit()
            print("Button configs cleared. They will be regenerated on next bot start.")
            
            # 3. Check for "Функция в разработке"
            print("Checking for legacy 'Function in development' strings...")
            # Check settings
            cursor.execute("SELECT key, value FROM bot_settings WHERE value LIKE '%Функция в разработке%'")
            bad_settings = cursor.fetchall()
            for key, val in bad_settings:
                print(f"Found bad setting: {key}={val}")
                cursor.execute("DELETE FROM bot_settings WHERE key = ?", (key,))
                print(f"Deleted setting {key}")
            conn.commit()

            print("\nDatabase fix completed successfully.")
            
    except sqlite3.Error as e:
        print(f"Database error: {e}")
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    fix_database()
