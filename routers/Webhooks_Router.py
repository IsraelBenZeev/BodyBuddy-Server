import hmac
import os

from fastapi import APIRouter, Header, HTTPException, Request

from controllers.reports_controller import send_exercise_report_email

routerWebhooks = APIRouter()


@routerWebhooks.post("/exercise-report")
async def exercise_report_webhook(
    request: Request,
    x_webhook_secret: str = Header(default=""),
):
    expected_secret = os.getenv("EXERCISE_REPORT_WEBHOOK_SECRET", "")
    if not expected_secret or not hmac.compare_digest(x_webhook_secret, expected_secret):
        raise HTTPException(status_code=401, detail="Unauthorized")

    payload = await request.json()
    record = payload.get("record", {})

    try:
        await send_exercise_report_email(
            record.get("search_query", ""),
            record.get("suggested_name"),
            record.get("note"),
            record.get("user_id", "unknown"),
        )
    except Exception as e:
        print("exercise report webhook email error:", e)
        raise HTTPException(status_code=500, detail="Failed to process webhook")

    return {"status": "ok"}
