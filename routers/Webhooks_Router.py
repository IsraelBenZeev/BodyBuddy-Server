import hmac
import os

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel

from controllers.reports_controller import send_new_user_email

routerWebhooks = APIRouter()


class NewUserRecord(BaseModel):
    id: str
    email: str | None = None
    full_name: str | None = None
    created_at: str | None = None


class NewUserWebhookPayload(BaseModel):
    type: str
    table: str
    record: NewUserRecord


def _verify_webhook_secret(x_webhook_secret: str | None) -> None:
    expected = os.getenv("SUPABASE_WEBHOOK_SECRET")
    if not expected or not x_webhook_secret or not hmac.compare_digest(x_webhook_secret, expected):
        raise HTTPException(status_code=401, detail="Unauthorized")


@routerWebhooks.post("/new-user")
async def new_user_webhook(
    payload: NewUserWebhookPayload,
    x_webhook_secret: str | None = Header(default=None, alias="x-webhook-secret"),
):
    _verify_webhook_secret(x_webhook_secret)

    if payload.table != "users" or payload.type != "INSERT":
        return {"status": "ignored"}

    record = payload.record

    try:
        await send_new_user_email(
            user_id=record.id,
            email=record.email,
            full_name=record.full_name,
            created_at=record.created_at,
        )
    except Exception as e:
        print("new user webhook email error:", e)
        raise HTTPException(status_code=500, detail="Failed to send new user email")

    return {"status": "ok"}
