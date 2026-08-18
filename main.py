from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
import os
from dotenv import load_dotenv

load_dotenv(override=True)

from routers.PrivacyPolicy_Router import routerPrivacyPolicy
from routers.Nutrition_Router import routerNutrition
from routers.Reports_Router import routerReports
from routers.Scheduler_Router import routerScheduler
from routers.Uploads_Router import routerUploads
from routers.Webhooks_Router import routerWebhooks
from routers.Admin_Router import routerAdmin
from routers.Account_Router import routerAccount
from limiter import limiter

app = FastAPI(title="BodyBuddy Server")
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

origins = [
    os.getenv("CLIENT_URL"),
    "http://localhost:5173",
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
async def root():
    return {"message": "Welcome to BodyBuddy Server!", "version": "1.0"}


app.include_router(routerPrivacyPolicy, prefix="/privacy-policy", tags=["privacy-policy"])
app.include_router(routerNutrition, prefix="/nutrition", tags=["nutrition"])
app.include_router(routerReports, prefix="/reports", tags=["reports"])
app.include_router(routerScheduler, prefix="/scheduler", tags=["scheduler"])
app.include_router(routerUploads, prefix="/uploads", tags=["uploads"])
app.include_router(routerWebhooks, prefix="/webhooks", tags=["webhooks"])
app.include_router(routerAdmin, prefix="/admin", tags=["admin"])
app.include_router(routerAccount, prefix="/account", tags=["account"])

if __name__ == "__main__":
    if os.getenv("ENVIRONMENT") == "development":
        import uvicorn

        port = int(os.getenv("PORT", "8000"))
        print(f"Server running on port {port}")
        uvicorn.run(app, host="0.0.0.0", port=port, reload=True)
