import sqlite3
from pathlib import Path

# Fix path to match where the bot runs
DB_PATH = Path("users.db").resolve()

print(f"Checking database at: {DB_PATH}")

try:
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    print("\n--- bot_settings ---")
    try:
        cursor.execute("SELECT key, value FROM bot_settings")
        rows = cursor.fetchall()
        for key, value in rows:
            print(f"{key}: {value}")
            if "Функция в разработке" in str(value):
                print(f"!!! FOUND 'Функция в разработке' in key: {key} !!!")
    except Exception as e:
        print(f"Error reading bot_settings: {e}")

    conn.close()

except Exception as e:
    print(f"Connection error: {e}")
