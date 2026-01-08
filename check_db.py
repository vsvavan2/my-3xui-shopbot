import sqlite3

def check():
    try:
        conn = sqlite3.connect('users.db')
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute("SELECT * FROM transactions WHERE payment_id='test_payment_local'")
        row = c.fetchone()
        if row:
            print(dict(row))
        else:
            print("Transaction not found")
        conn.close()
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    check()
