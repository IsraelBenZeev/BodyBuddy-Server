from fastapi import APIRouter, HTTPException, Request, Depends
from pydantic import BaseModel
from controllers.reports_controller import send_exercise_report_email
from dependencies import verify_supabase_token
from limiter import limiter

routerReports = APIRouter()


class ExerciseReportRequest(BaseModel):
    search_query: str
    suggested_name: str | None = None
    note: str | None = None


@routerReports.post("/exercise-missing")
@limiter.limit("5/minute")
async def report_exercise_missing(
    request: Request,
    body: ExerciseReportRequest,
    user_id: str = Depends(verify_supabase_token),
):
    try:
        await send_exercise_report_email(body.search_query, body.suggested_name, body.note, user_id)
        return {"status": "sent"}
    except Exception as e:
        print("report email error:", e)
        raise HTTPException(status_code=500, detail="Failed to send report email")
