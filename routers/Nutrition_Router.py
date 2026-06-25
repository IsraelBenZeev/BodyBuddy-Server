from fastapi import APIRouter, HTTPException, Request, Depends
from pydantic import BaseModel
from controllers.nutrition_controller import analyze_food_image
from dependencies import verify_supabase_token
from limiter import limiter

routerNutrition = APIRouter()

MAX_IMAGE_B64_SIZE = 5 * 1024 * 1024  # 5MB base64 ≈ ~3.7MB actual image


class FoodImageRequest(BaseModel):
    image: str


@routerNutrition.post("/analyze-food")
@limiter.limit("10/minute")
async def analyze_food(
    request: Request,
    body: FoodImageRequest,
    user_id: str = Depends(verify_supabase_token),
):
    if len(body.image) > MAX_IMAGE_B64_SIZE:
        raise HTTPException(status_code=413, detail="Image too large")

    try:
        return await analyze_food_image(body.image)
    except HTTPException:
        raise
    except Exception as e:
        print("nutrition error:", e)
        raise HTTPException(status_code=500, detail="Failed to analyze image")
