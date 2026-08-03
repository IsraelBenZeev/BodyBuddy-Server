from datetime import date

from fastapi import APIRouter, HTTPException, Request, Depends

from controllers.admin_controller import (
    delete_user,
    get_active_user_counts,
    get_new_user_counts,
    get_user_detail,
    list_users,
    toggle_user_suspension,
)
from dependencies import _fetch_is_admin, require_admin, verify_supabase_token
from limiter import limiter

routerAdmin = APIRouter()

NOT_ADMIN_MESSAGE = "החשבון שהתחברת איתו אינו מוגדר כמנהל מערכת. אנא התחברו עם חשבון מנהל כדי להמשיך."

VALID_STATUSES = {"active", "suspended"}
VALID_PLATFORMS = {"ios", "android"}
VALID_AUTH_PROVIDERS = {"email", "google", "apple", "facebook"}


def _parse_query_date(value: str | None, field: str) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid {field}")


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
    status: str | None = None,
    platform: str | None = None,
    authProvider: str | None = None,
    inactiveDays: int | None = None,
    joinedFrom: str | None = None,
    joinedTo: str | None = None,
    user_id: str = Depends(require_admin),
):
    if status is not None and status not in VALID_STATUSES:
        raise HTTPException(status_code=400, detail="Invalid status")
    if platform is not None and platform not in VALID_PLATFORMS:
        raise HTTPException(status_code=400, detail="Invalid platform")
    if authProvider is not None and authProvider not in VALID_AUTH_PROVIDERS:
        raise HTTPException(status_code=400, detail="Invalid authProvider")
    if inactiveDays is not None and inactiveDays <= 0:
        raise HTTPException(status_code=400, detail="Invalid inactiveDays")

    joined_from_date = _parse_query_date(joinedFrom, "joinedFrom")
    joined_to_date = _parse_query_date(joinedTo, "joinedTo")
    if joined_from_date and joined_to_date and joined_from_date > joined_to_date:
        raise HTTPException(status_code=400, detail="joinedFrom must be before joinedTo")

    try:
        return await list_users(
            search,
            page,
            status=status,
            platform=platform,
            auth_provider=authProvider,
            inactive_days=inactiveDays,
            joined_from=joined_from_date,
            joined_to=joined_to_date,
        )
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


@routerAdmin.get("/dashboard/user-counts")
@limiter.limit("60/minute")
async def get_user_counts_route(request: Request, user_id: str = Depends(require_admin)):
    try:
        return await get_new_user_counts()
    except RuntimeError as e:
        print("admin user counts config error:", e)
        raise HTTPException(status_code=500, detail="Failed to load user counts")
    except Exception as e:
        print("admin user counts error:", e)
        raise HTTPException(status_code=500, detail="Failed to load user counts")


@routerAdmin.get("/dashboard/active-user-counts")
@limiter.limit("60/minute")
async def get_active_user_counts_route(request: Request, user_id: str = Depends(require_admin)):
    try:
        return await get_active_user_counts()
    except RuntimeError as e:
        print("admin active user counts config error:", e)
        raise HTTPException(status_code=500, detail="Failed to load active user counts")
    except Exception as e:
        print("admin active user counts error:", e)
        raise HTTPException(status_code=500, detail="Failed to load active user counts")


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
