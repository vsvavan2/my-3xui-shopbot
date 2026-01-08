import sqlite3
import json
import os

DB_FILE = 'users.db'

def setup():
    print(f"Connecting to {DB_FILE}...")
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()

    # 1. Set YooMoney Secret
    secret = "9dm+vyGtCMEKh9RLIeADIl6J"
    cursor.execute("INSERT OR REPLACE INTO bot_settings (key, value) VALUES (?, ?)", ('yoomoney_secret', secret))
    print(f"Set yoomoney_secret to {secret}")

    # 2. Create Pending Transaction
    payment_id = "test_payment_local"
    user_id = 12345
    amount = 100.0
    metadata = {"user_id": user_id, "plan_id": 1, "months": 1}
    
    # Check if exists
    cursor.execute("SELECT transaction_id FROM transactions WHERE payment_id = ?", (payment_id,))
    row = cursor.fetchone()
    
    if row:
        cursor.execute("UPDATE transactions SET status='pending' WHERE payment_id = ?", (payment_id,))
        print(f"Reset transaction {payment_id} to pending")
    else:
        cursor.execute(
            "INSERT INTO transactions (payment_id, user_id, status, amount_rub, metadata) VALUES (?, ?, ?, ?, ?)",
            (payment_id, user_id, 'pending', amount, json.dumps(metadata))
        )
        print(f"Created new pending transaction {payment_id}")

    conn.commit()
    conn.close()

if __name__ == "__main__":
    setup()
