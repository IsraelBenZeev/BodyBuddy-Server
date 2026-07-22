from fastapi import APIRouter, HTTPException, Request

from controllers.privacy_policy_controller import get_privacy_policy
from limiter import limiter

routerPrivacyPolicy = APIRouter()


@routerPrivacyPolicy.get("")
@limiter.limit("30/minute")
async def privacy_policy_route(request: Request):
    try:
        return await get_privacy_policy()
    except RuntimeError as e:
        print("privacy policy config error:", e)
        raise HTTPException(status_code=500, detail="Failed to load privacy policy")
    except Exception as e:
        print("privacy policy error:", e)
        raise HTTPException(status_code=500, detail="Failed to load privacy policy")
