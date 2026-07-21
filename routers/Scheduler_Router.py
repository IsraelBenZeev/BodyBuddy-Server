import hmac
import os

from fastapi import APIRouter, Header, HTTPException

from controllers.scheduler_controller import run_scheduler_cycle

routerScheduler = APIRouter()


def _verify_scheduler_secret(x_scheduler_secret: str | None) -> None:
    expected = os.getenv("SCHEDULER_SECRET")
    if not expected or not x_scheduler_secret or not hmac.compare_digest(x_scheduler_secret, expected):
        raise HTTPException(status_code=401, detail="Unauthorized")


@routerScheduler.post("/run")
async def run_scheduler(
    x_scheduler_secret: str | None = Header(default=None, alias="x-scheduler-secret"),
):
    _verify_scheduler_secret(x_scheduler_secret)

    try:
        result = await run_scheduler_cycle()
    except Exception as e:
        print("scheduler run error:", e)
        raise HTTPException(status_code=500, detail="Scheduler run failed")

    return {"status": "ok", **result}
