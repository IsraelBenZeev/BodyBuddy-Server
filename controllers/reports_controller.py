import html
import os
import re
import smtplib
from datetime import datetime
from email.mime.image import MIMEImage
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from urllib.parse import urlparse

import httpx

CONTROL_CHARS = re.compile(r"[\r\n]")

LOGO_PATH = Path(__file__).resolve().parent.parent / "assets" / "logo.png"

COLOR_LIME = "#96C828"
COLOR_LIME_LIGHT = "#EFF7E1"
COLOR_GRAY_900 = "#27272A"
COLOR_GRAY_500 = "#71717A"
COLOR_GRAY_200 = "#E4E4E7"
COLOR_GRAY_50 = "#FAFAFA"


def _sanitize(value: str | None, max_length: int = 200) -> str:
    if not value:
        return "-"
    return CONTROL_CHARS.sub(" ", value).strip()[:max_length]


def _escape(value: str | None, max_length: int = 200) -> str:
    return html.escape(_sanitize(value, max_length))


def _safe_url(value: str | None) -> str | None:
    if not value:
        return None
    candidate = value.strip()
    if urlparse(candidate).scheme not in ("http", "https"):
        return None
    return html.escape(candidate, quote=True)


def _format_created_at(created_at: str | None) -> str:
    if not created_at:
        return "-"
    try:
        dt = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
        return dt.strftime("%d/%m/%Y %H:%M")
    except ValueError:
        return _escape(created_at)


async def _fetch_user_details(user_id: str | None) -> tuple[str, str]:
    supabase_url = os.getenv("SUPABASE_URL")
    service_role_key = os.getenv("SUPABASE_SERVICE_ROLE_KEY")

    if not user_id or not supabase_url or not service_role_key:
        return "-", "-"

    headers = {
        "apikey": service_role_key,
        "Authorization": f"Bearer {service_role_key}",
    }

    full_name = "-"
    email_address = "-"

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            profile_response = await client.get(
                f"{supabase_url}/rest/v1/profiles",
                params={"user_id": f"eq.{user_id}", "select": "full_name"},
                headers=headers,
            )
            profile_response.raise_for_status()
            profiles = profile_response.json()
            if profiles and profiles[0].get("full_name"):
                full_name = profiles[0]["full_name"]

            auth_response = await client.get(
                f"{supabase_url}/auth/v1/admin/users/{user_id}",
                headers=headers,
            )
            if auth_response.status_code == 200:
                email_address = auth_response.json().get("email") or "-"
    except Exception as e:
        print("exercise report webhook user lookup error:", e)

    return full_name, email_address


def _build_email_html(
    safe_query: str,
    safe_suggested_name: str,
    safe_note: str,
    created_at_display: str,
    report_id_display: str,
    full_name_display: str,
    email_display: str,
    example_url_safe: str | None,
) -> str:
    example_url_row = ""
    if example_url_safe:
        example_url_row = f"""\
                <tr>
                  <td style="padding:10px 0;border-bottom:1px solid {COLOR_GRAY_200};color:{COLOR_GRAY_500};font-size:13px;text-align:right;">קישור לדוגמה</td>
                  <td style="padding:10px 0;border-bottom:1px solid {COLOR_GRAY_200};font-size:14px;text-align:right;">
                    <a href="{example_url_safe}" style="color:{COLOR_LIME};text-decoration:none;font-weight:bold;">צפייה בדוגמה &#8592;</a>
                  </td>
                </tr>
"""
    return f"""\
<!DOCTYPE html>
<html dir="rtl" lang="he">
<body style="margin:0;padding:24px;background:{COLOR_GRAY_50};font-family:Arial,Helvetica,sans-serif;">
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0">
    <tr>
      <td align="center">
        <table role="presentation" width="560" cellpadding="0" cellspacing="0"
               style="max-width:560px;width:100%;background:#ffffff;border:1px solid {COLOR_GRAY_200};border-radius:12px;overflow:hidden;">
          <tr>
            <td align="center" style="background:{COLOR_GRAY_900};padding:28px 24px;">
              <img src="cid:logo" alt="BodyBuddy" width="72" style="display:block;height:auto;" />
            </td>
          </tr>
          <tr>
            <td style="padding:28px 24px 8px 24px;" dir="rtl">
              <span style="display:inline-block;background:{COLOR_LIME_LIGHT};color:{COLOR_GRAY_900};font-size:12px;font-weight:bold;padding:4px 10px;border-radius:999px;">
                דיווח חדש
              </span>
              <h1 style="margin:12px 0 0 0;font-size:20px;color:{COLOR_GRAY_900};text-align:right;">
                דיווח על תרגיל חסר
              </h1>
            </td>
          </tr>
          <tr>
            <td style="padding:8px 24px 24px 24px;" dir="rtl">
              <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse;">
                <tr>
                  <td style="padding:10px 0;border-bottom:1px solid {COLOR_GRAY_200};color:{COLOR_GRAY_500};font-size:13px;text-align:right;width:120px;">שאילתת חיפוש</td>
                  <td style="padding:10px 0;border-bottom:1px solid {COLOR_GRAY_200};color:{COLOR_GRAY_900};font-size:14px;text-align:right;">{safe_query}</td>
                </tr>
                <tr>
                  <td style="padding:10px 0;border-bottom:1px solid {COLOR_GRAY_200};color:{COLOR_GRAY_500};font-size:13px;text-align:right;">שם מוצע</td>
                  <td style="padding:10px 0;border-bottom:1px solid {COLOR_GRAY_200};color:{COLOR_GRAY_900};font-size:14px;text-align:right;">{safe_suggested_name}</td>
                </tr>
                <tr>
                  <td style="padding:10px 0;border-bottom:1px solid {COLOR_GRAY_200};color:{COLOR_GRAY_500};font-size:13px;text-align:right;">הערה</td>
                  <td style="padding:10px 0;border-bottom:1px solid {COLOR_GRAY_200};color:{COLOR_GRAY_900};font-size:14px;text-align:right;">{safe_note}</td>
                </tr>
{example_url_row}\
                <tr>
                  <td style="padding:10px 0;border-bottom:1px solid {COLOR_GRAY_200};color:{COLOR_GRAY_500};font-size:13px;text-align:right;">תאריך</td>
                  <td style="padding:10px 0;border-bottom:1px solid {COLOR_GRAY_200};color:{COLOR_GRAY_900};font-size:14px;text-align:right;">{created_at_display}</td>
                </tr>
                <tr>
                  <td style="padding:10px 0;color:{COLOR_GRAY_500};font-size:13px;text-align:right;">מזהה דיווח</td>
                  <td style="padding:10px 0;color:{COLOR_GRAY_500};font-size:12px;font-family:monospace;text-align:right;">{report_id_display}</td>
                </tr>
              </table>
            </td>
          </tr>
          <tr>
            <td style="padding:0 24px 24px 24px;" dir="rtl">
              <table role="presentation" width="100%" cellpadding="0" cellspacing="0"
                     style="background:{COLOR_GRAY_50};border:1px solid {COLOR_GRAY_200};border-radius:8px;">
                <tr>
                  <td style="padding:14px 16px;">
                    <div style="color:{COLOR_GRAY_500};font-size:12px;margin-bottom:4px;">הוגש על ידי</div>
                    <div style="color:{COLOR_GRAY_900};font-size:14px;font-weight:bold;">{full_name_display}</div>
                    <div style="color:{COLOR_GRAY_500};font-size:13px;">{email_display}</div>
                  </td>
                </tr>
              </table>
            </td>
          </tr>
          <tr>
            <td align="center" style="padding:16px 24px;background:{COLOR_GRAY_50};border-top:1px solid {COLOR_GRAY_200};">
              <span style="color:{COLOR_GRAY_500};font-size:12px;">נשלח אוטומטית ממערכת BodyBuddy</span>
            </td>
          </tr>
        </table>
      </td>
    </tr>
  </table>
</body>
</html>
"""


async def send_exercise_report_email(
    search_query: str,
    suggested_name: str | None,
    note: str | None,
    user_id: str,
    report_id: str | None = None,
    created_at: str | None = None,
    example_url: str | None = None,
) -> None:
    gmail_address = os.getenv("GMAIL_ADDRESS")
    gmail_app_password = os.getenv("GMAIL_APP_PASSWORD")
    recipient = os.getenv("REPORT_RECIPIENT_EMAIL", "bodybuddysupport@gmail.com")

    if not gmail_address or not gmail_app_password:
        raise RuntimeError("GMAIL_ADDRESS/GMAIL_APP_PASSWORD not configured")

    safe_query = _escape(search_query)
    safe_suggested_name = _escape(suggested_name)
    safe_note = _escape(note, max_length=2000)
    created_at_display = _format_created_at(created_at)
    report_id_display = _escape(report_id, max_length=100)

    full_name, email_address = await _fetch_user_details(
        user_id if user_id != "-" else None
    )
    full_name_display = _escape(full_name)
    email_display = _escape(email_address)
    example_url_safe = _safe_url(example_url)

    message = MIMEMultipart("related")
    message["Subject"] = f'דיווח על תרגיל חסר: "{_sanitize(search_query)}"'
    message["From"] = gmail_address
    message["To"] = recipient

    html_body = _build_email_html(
        safe_query,
        safe_suggested_name,
        safe_note,
        created_at_display,
        report_id_display,
        full_name_display,
        email_display,
        example_url_safe,
    )
    message.attach(MIMEText(html_body, "html", "utf-8"))

    if LOGO_PATH.exists():
        with open(LOGO_PATH, "rb") as logo_file:
            logo_image = MIMEImage(logo_file.read())
            logo_image.add_header("Content-ID", "<logo>")
            logo_image.add_header("Content-Disposition", "inline", filename="logo.png")
            message.attach(logo_image)

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(gmail_address, gmail_app_password)
        server.send_message(message)


async def update_exercise_report_status(report_id: str, status: str) -> None:
    supabase_url = os.getenv("SUPABASE_URL")
    service_role_key = os.getenv("SUPABASE_SERVICE_ROLE_KEY")

    if not supabase_url or not service_role_key:
        raise RuntimeError("SUPABASE_URL/SUPABASE_SERVICE_ROLE_KEY not configured")

    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.patch(
            f"{supabase_url}/rest/v1/exercise_reports",
            params={"id": f"eq.{report_id}"},
            headers={
                "apikey": service_role_key,
                "Authorization": f"Bearer {service_role_key}",
                "Content-Type": "application/json",
                "Prefer": "return=minimal",
            },
            json={"status": status},
        )
        response.raise_for_status()
