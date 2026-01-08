import hashlib

def calculate_hash(notification_type, operation_id, amount, currency, event_datetime, sender, codepro, secret, label):
    # notification_type&operation_id&amount&currency&datetime&sender&codepro&notification_secret&label
    validation_string = f"{notification_type}&{operation_id}&{amount}&{currency}&{event_datetime}&{sender}&{codepro}&{secret}&{label}"
    print(f"Validation String: {validation_string}")
    return hashlib.sha1(validation_string.encode('utf-8')).hexdigest()

secret = "9dm+vyGtCMEKh9RLIeADIl6J"
notification_type = "p2p-incoming"
operation_id = "1234567"
amount = "100.00"
currency = "643"
event_datetime = "2024-01-01T00:00:00Z"
sender = "410010000000000"
codepro = "false"
label = "test_payment"

calculated_hash = calculate_hash(notification_type, operation_id, amount, currency, event_datetime, sender, codepro, secret, label)
print(f"Calculated Hash: {calculated_hash}")
