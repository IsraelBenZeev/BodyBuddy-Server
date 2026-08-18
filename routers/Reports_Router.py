from fastapi import APIRouter, HTTPException, Request, Depends
from pydantic import BaseModel
from controllers.reports_controller import (
    insert_exercise_report,
    send_exercise_report_email,
    update_exercise_report_status,
)
from dependencies import verify_supabase_token
from limiter import limiter

routerReports = APIRouter()


class ExerciseReportRequest(BaseModel):
    search_query: str
    suggested_name: str | None = None
    note: str | None = None
    example_url: str | None = None


@routerReports.post("/exercise-missing")
@limiter.limit("5/minute")
async def report_exercise_missing(
    request: Request,
    body: ExerciseReportRequest,
    user_id: str = Depends(verify_supabase_token),
):
    try:
        report = await insert_exercise_report(
            user_id, body.search_query, body.suggested_name, body.note, body.example_url
        )
    except Exception as e:
        print("report insert error:", e)
        raise HTTPException(status_code=500, detail="Failed to save report")

    try:
        await send_exercise_report_email(
            body.search_query,
            body.suggested_name,
            body.note,
            user_id,
            report_id=report.get("id"),
            created_at=report.get("created_at"),
            example_url=body.example_url,
        )
        await update_exercise_report_status(report["id"], "reviewed")
    except Exception as e:
        # The report is already saved — an email failure shouldn't surface as a
        # failed submission to the user; it just stays "pending" for manual review.
        print("report email error:", e)

    return {"status": "ok", "id": report.get("id")}
