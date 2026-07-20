import hmac
import os

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel

from controllers.reports_controller import send_exercise_report_email, update_exercise_report_status

routerWebhooks = APIRouter()


class ExerciseReportRecord(BaseModel):
    id: str
    user_id: str | None = None
    search_query: str
    suggested_name: str | None = None
    note: str | None = None


class SupabaseWebhookPayload(BaseModel):
    type: str
    table: str
    record: ExerciseReportRecord


def _verify_webhook_secret(x_webhook_secret: str | None) -> None:
    expected = os.getenv("SUPABASE_WEBHOOK_SECRET")
    if not expected or not x_webhook_secret or not hmac.compare_digest(x_webhook_secret, expected):
        raise HTTPException(status_code=401, detail="Unauthorized")


@routerWebhooks.post("/exercise-report")
async def exercise_report_webhook(
    payload: SupabaseWebhookPayload,
    x_webhook_secret: str | None = Header(default=None, alias="x-webhook-secret"),
):
    _verify_webhook_secret(x_webhook_secret)

    if payload.table != "exercise_reports" or payload.type != "INSERT":
        return {"status": "ignored"}

    record = payload.record

    try:
        await send_exercise_report_email(
            record.search_query, record.suggested_name, record.note, record.user_id or "-"
        )
    except Exception as e:
        print("exercise report webhook email error:", e)
        raise HTTPException(status_code=500, detail="Failed to send report email")

    try:
        await update_exercise_report_status(record.id, "reviewed")
    except Exception as e:
        print("exercise report webhook status update error:", e)

    return {"status": "ok"}
