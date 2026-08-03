from fastapi import APIRouter, HTTPException, Request, Depends

from controllers.admin_controller import delete_user, get_user_detail, list_users, toggle_user_suspension
from dependencies import _fetch_is_admin, require_admin, verify_supabase_token
from limiter import limiter

routerAdmin = APIRouter()

NOT_ADMIN_MESSAGE = "החשבון שהתחברת איתו אינו מוגדר כמנהל מערכת. אנא התחברו עם חשבון מנהל כדי להמשיך."


@routerAdmin.get("/me")
@limiter.limit("60/minute")
async def get_me_route(request: Request, user_id: str = Depends(verify_supabase_token)):
    try:
        is_admin = await _fetch_is_admin(user_id)
    except RuntimeError as e:
        print("admin me config error:", e)
        raise HTTPException(status_code=500, detail="Failed to verify admin status")

    if not is_admin:
        return {"isAdmin": False, "message": NOT_ADMIN_MESSAGE}

    return {"isAdmin": True}


@routerAdmin.get("/users")
@limiter.limit("60/minute")
async def list_users_route(
    request: Request,
    search: str = "",
    page: int = 1,
    user_id: str = Depends(require_admin),
):
    try:
        return await list_users(search, page)
    except RuntimeError as e:
        print("admin list users config error:", e)
        raise HTTPException(status_code=500, detail="Failed to load users")
    except Exception as e:
        print("admin list users error:", e)
        raise HTTPException(status_code=500, detail="Failed to load users")


@routerAdmin.get("/users/{target_user_id}")
@limiter.limit("60/minute")
async def get_user_detail_route(request: Request, target_user_id: str, user_id: str = Depends(require_admin)):
    try:
        return await get_user_detail(target_user_id)
    except LookupError:
        raise HTTPException(status_code=404, detail="User not found")
    except RuntimeError as e:
        print("admin get user config error:", e)
        raise HTTPException(status_code=500, detail="Failed to load user")
    except Exception as e:
        print("admin get user error:", e)
        raise HTTPException(status_code=500, detail="Failed to load user")


@routerAdmin.post("/users/{target_user_id}/suspend")
@limiter.limit("20/minute")
async def suspend_user_route(request: Request, target_user_id: str, user_id: str = Depends(require_admin)):
    try:
        return await toggle_user_suspension(target_user_id, user_id)
    except LookupError:
        raise HTTPException(status_code=404, detail="User not found")
    except RuntimeError as e:
        print("admin suspend user config error:", e)
        raise HTTPException(status_code=500, detail="Failed to update user")
    except Exception as e:
        print("admin suspend user error:", e)
        raise HTTPException(status_code=500, detail="Failed to update user")


@routerAdmin.delete("/users/{target_user_id}")
@limiter.limit("20/minute")
async def delete_user_route(request: Request, target_user_id: str, user_id: str = Depends(require_admin)):
    try:
        await delete_user(target_user_id, user_id)
        return {"status": "deleted"}
    except LookupError:
        raise HTTPException(status_code=404, detail="User not found")
    except RuntimeError as e:
        print("admin delete user config error:", e)
        raise HTTPException(status_code=500, detail="Failed to delete user")
    except Exception as e:
        print("admin delete user error:", e)
        raise HTTPException(status_code=500, detail="Failed to delete user")
