import requests
from datetime import datetime

WEBHOOK_URL = "PASTE_YOUR_SLACK_WEBHOOK_HERE"

now = datetime.now().strftime("%I:%M %p")

message = f"""
🚨 UNDERSTAFFED ALERT
Location: Urban Grill
Time: {now}
Sales: +22% vs forecast
Labor: 68%
Ticket Time: Rising
→ Call in 1–2 staff immediately
"""

response = requests.post(
    WEBHOOK_URL,
    json={"text": message}
)
print(response.status_code)
