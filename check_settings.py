import sqlite3
import os

db_path = 'users.db'
if not os.path.exists(db_path):
    print(f"Database {db_path} not found.")
    exit(1)

try:
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    c.execute("SELECT key, value FROM bot_settings WHERE key IN ('telegram_bot_token', 'telegram_bot_username', 'admin_telegram_id')")
    rows = c.fetchall()
    print("Settings found:")
    for row in rows:
        print(f"{row[0]}: {row[1]}")
    conn.close()
except Exception as e:
    print(f"Error: {e}")
