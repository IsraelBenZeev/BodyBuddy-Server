import os
import re
import smtplib
from email.mime.text import MIMEText

CONTROL_CHARS = re.compile(r"[\r\n]")


def _sanitize(value: str | None, max_length: int = 200) -> str:
    if not value:
        return "-"
    return CONTROL_CHARS.sub(" ", value).strip()[:max_length]


async def send_exercise_report_email(
    search_query: str,
    suggested_name: str | None,
    note: str | None,
    user_id: str,
) -> None:
    gmail_address = os.getenv("GMAIL_ADDRESS")
    gmail_app_password = os.getenv("GMAIL_APP_PASSWORD")
    recipient = os.getenv("REPORT_RECIPIENT_EMAIL", "bodybuddysupport@gmail.com")

    if not gmail_address or not gmail_app_password:
        raise RuntimeError("GMAIL_ADDRESS/GMAIL_APP_PASSWORD not configured")

    safe_query = _sanitize(search_query)
    safe_suggested_name = _sanitize(suggested_name)
    safe_note = _sanitize(note, max_length=2000)

    body = (
        f"שאילתת חיפוש: {safe_query}\n"
        f"שם מוצע: {safe_suggested_name}\n"
        f"הערה: {safe_note}\n"
        f"משתמש: {user_id}"
    )

    message = MIMEText(body, "plain", "utf-8")
    message["Subject"] = f'דיווח על תרגיל חסר: "{safe_query}"'
    message["From"] = gmail_address
    message["To"] = recipient

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(gmail_address, gmail_app_password)
        server.send_message(message)
