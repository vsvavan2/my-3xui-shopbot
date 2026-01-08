import sqlite3
import os
import sys
from pathlib import Path

# Add src to path
project_root = Path(__file__).parent
src_path = project_root / "src"
sys.path.append(str(src_path))

from shop_bot.data_manager import database

DB_PATH = database.DB_FILE

def search_db():
    if len(sys.argv) > 1:
        DB_PATH = Path(sys.argv[1])
    else:
        DB_PATH = database.DB_FILE

    print(f"Checking database at {DB_PATH}")
    
    if not DB_PATH.exists():
        print("Database not found. Initializing...")
        database.initialize_db()
        print("Database initialized.")

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # Get all tables
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
    tables = cursor.fetchall()
    
    found = False
    for table in tables:
        table_name = table[0]
        print(f"Checking table: {table_name}")
        try:
            cursor.execute(f"SELECT * FROM {table_name}")
            rows = cursor.fetchall()
            for row in rows:
                for cell in row:
                    if isinstance(cell, str) and "Функция в разработке" in cell:
                        print(f"FOUND in table '{table_name}': {cell}")
                        found = True
        except Exception as e:
            print(f"Error checking table {table_name}: {e}")
            
    if not found:
        print("String not found in database.")
    
    conn.close()

if __name__ == "__main__":
    search_db()
