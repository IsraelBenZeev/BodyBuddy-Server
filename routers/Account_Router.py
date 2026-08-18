from fastapi import APIRouter, HTTPException, Request, Depends

from controllers.account_controller import delete_own_account
from dependencies import verify_supabase_token
from limiter import limiter

routerAccount = APIRouter()


@routerAccount.delete("/me")
@limiter.limit("5/minute")
async def delete_own_account_route(request: Request, user_id: str = Depends(verify_supabase_token)):
    try:
        await delete_own_account(user_id)
        return {"status": "deleted"}
    except RuntimeError as e:
        print("delete own account config error:", e)
        raise HTTPException(status_code=500, detail="Failed to delete account")
    except Exception as e:
        print("delete own account error:", e)
        raise HTTPException(status_code=500, detail="Failed to delete account")
