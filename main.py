from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
import os
from dotenv import load_dotenv

load_dotenv(override=True)

from routers.Nutrition_Router import routerNutrition
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


app.include_router(routerNutrition, prefix="/nutrition", tags=["nutrition"])

if __name__ == "__main__":
    if os.getenv("ENVIRONMENT") == "development":
        import uvicorn

        port = int(os.getenv("PORT", "8000"))
        print(f"Server running on port {port}")
        uvicorn.run(app, host="0.0.0.0", port=port, reload=True)
