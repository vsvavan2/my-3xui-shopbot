import requests
import hashlib

def trigger():
    url = "http://127.0.0.1:1489/yoomoney-webhook"
    
    # Parameters
    notification_type = "p2p-incoming"
    operation_id = "1234567890"
    amount = "100.00" # String format important for hash? Usually it is just the value
    currency = "643"
    datetime_val = "2024-01-01T00:00:00Z"
    sender = "410010000000000"
    codepro = "false"
    notification_secret = "9dm+vyGtCMEKh9RLIeADIl6J"
    label = "test_payment_local"
    
    # Calculate SHA1
    # formula: notification_type & operation_id & amount & currency & datetime & sender & codepro & notification_secret & label
    s = f"{notification_type}&{operation_id}&{amount}&{currency}&{datetime_val}&{sender}&{codepro}&{notification_secret}&{label}"
    sha1_hash = hashlib.sha1(s.encode('utf-8')).hexdigest()
    
    data = {
        "notification_type": notification_type,
        "operation_id": operation_id,
        "amount": amount,
        "currency": currency,
        "datetime": datetime_val,
        "sender": sender,
        "codepro": codepro,
        "label": label,
        "sha1_hash": sha1_hash,
        "test_notification": "true", # Optional, maybe helpful
        "unaccepted": "false"
    }
    
    print(f"Sending webhook to {url} with data: {data}")
    try:
        response = requests.post(url, data=data, proxies={"http": None, "https": None})
        print(f"Response status: {response.status_code}")
        print(f"Response text: {response.text}")
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    trigger()
