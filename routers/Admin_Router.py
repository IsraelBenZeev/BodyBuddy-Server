from datetime import date

from fastapi import APIRouter, HTTPException, Request, Depends, Body, Form, File, UploadFile

from controllers.admin_controller import (
    delete_user,
    get_active_user_counts,
    get_new_user_counts,
    get_user_detail,
    list_users,
    toggle_user_suspension,
)
from controllers.admin_exercises_controller import (
    VALID_BODY_PARTS,
    create_exercise,
    delete_exercise,
    get_exercise,
    list_exercises,
    toggle_exercise_freeze,
    update_exercise,
)
from controllers.admin_notifications_controller import (
    ACTIVITY_SEGMENTS,
    PLATFORM_SEGMENTS,
    VALID_SCREENS,
    get_notification_history,
    preview_audience,
    send_notification,
)
from dependencies import _fetch_is_admin, require_admin, verify_supabase_token
from limiter import limiter

routerAdmin = APIRouter()

NOT_ADMIN_MESSAGE = "החשבון שהתחברת איתו אינו מוגדר כמנהל מערכת. אנא התחברו עם חשבון מנהל כדי להמשיך."

VALID_STATUSES = {"active", "suspended"}
VALID_PLATFORMS = {"ios", "android"}
VALID_AUTH_PROVIDERS = {"email", "google", "apple", "facebook"}

MAX_EXERCISE_IMAGE_SIZE = 10 * 1024 * 1024  # 10MB
MAX_EXERCISE_VIDEO_SIZE = 100 * 1024 * 1024  # 100MB
ALLOWED_EXERCISE_IMAGE_CONTENT_TYPES = {"image/jpeg", "image/png", "image/webp", "image/heic", "image/heif"}
ALLOWED_EXERCISE_VIDEO_CONTENT_TYPES = {"video/mp4", "video/quicktime", "video/webm"}


EXERCISE_STATUSES = {"active", "frozen"}
EXERCISE_SORT_FIELDS = {"createdAt", "name"}
EXERCISE_SORT_ORDERS = {"asc", "desc"}


def _validate_exercise_fields(name: str, name_he: str, body_parts: list[str]) -> None:
    if not name.strip():
        raise HTTPException(status_code=400, detail="name is required")
    if not name_he.strip():
        raise HTTPException(status_code=400, detail="nameHe is required")
    if not body_parts:
        raise HTTPException(status_code=400, detail="bodyParts must contain at least one value")
    if any(part not in VALID_BODY_PARTS for part in body_parts):
        raise HTTPException(status_code=400, detail="Invalid bodyParts value")


async def _read_validated_image(image: UploadFile) -> tuple[bytes, str]:
    if image.content_type not in ALLOWED_EXERCISE_IMAGE_CONTENT_TYPES:
        raise HTTPException(status_code=400, detail="Invalid image type")
    data = await image.read()
    if len(data) > MAX_EXERCISE_IMAGE_SIZE:
        raise HTTPException(status_code=400, detail="Image too large")
    return data, image.content_type


async def _read_validated_images(images: list[UploadFile]) -> list[tuple[bytes, str]]:
    return [await _read_validated_image(image) for image in images]


async def _read_validated_video(video: UploadFile) -> tuple[bytes, str]:
    if video.content_type not in ALLOWED_EXERCISE_VIDEO_CONTENT_TYPES:
        raise HTTPException(status_code=400, detail="Invalid video type")
    data = await video.read()
    if len(data) > MAX_EXERCISE_VIDEO_SIZE:
        raise HTTPException(status_code=400, detail="Video too large")
    return data, video.content_type


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


@routerAdmin.get("/exercises")
@limiter.limit("60/minute")
async def list_exercises_route(
    request: Request,
    page: int,
    search: str = "",
    bodyPart: str | None = None,
    status: str | None = None,
    sortBy: str = "createdAt",
    sortOrder: str = "desc",
    user_id: str = Depends(require_admin),
):
    if bodyPart is not None and bodyPart not in VALID_BODY_PARTS:
        raise HTTPException(status_code=400, detail="Invalid bodyPart")
    if status is not None and status not in EXERCISE_STATUSES:
        raise HTTPException(status_code=400, detail="Invalid status")
    if sortBy not in EXERCISE_SORT_FIELDS:
        raise HTTPException(status_code=400, detail="Invalid sortBy")
    if sortOrder not in EXERCISE_SORT_ORDERS:
        raise HTTPException(status_code=400, detail="Invalid sortOrder")

    try:
        return await list_exercises(search, page, body_part=bodyPart, status=status, sort_by=sortBy, sort_order=sortOrder)
    except RuntimeError as e:
        print("admin list exercises config error:", e)
        raise HTTPException(status_code=500, detail="Failed to load exercises")
    except Exception as e:
        print("admin list exercises error:", e)
        raise HTTPException(status_code=500, detail="Failed to load exercises")


@routerAdmin.get("/exercises/{exercise_id}")
@limiter.limit("60/minute")
async def get_exercise_route(request: Request, exercise_id: str, user_id: str = Depends(require_admin)):
    try:
        return await get_exercise(exercise_id)
    except LookupError:
        raise HTTPException(status_code=404, detail="Exercise not found")
    except RuntimeError as e:
        print("admin get exercise config error:", e)
        raise HTTPException(status_code=500, detail="Failed to load exercise")
    except Exception as e:
        print("admin get exercise error:", e)
        raise HTTPException(status_code=500, detail="Failed to load exercise")


@routerAdmin.post("/exercises")
@limiter.limit("20/minute")
async def create_exercise_route(
    request: Request,
    name: str = Form(...),
    nameHe: str = Form(...),
    bodyParts: list[str] = Form(...),
    subBodyParts: list[str] = Form([]),
    subBodyPartsHe: list[str] = Form([]),
    targetMuscles: list[str] = Form([]),
    targetMusclesHe: list[str] = Form([]),
    secondaryMuscles: list[str] = Form([]),
    secondaryMusclesHe: list[str] = Form([]),
    equipments: list[str] = Form([]),
    equipmentsHe: list[str] = Form([]),
    instructions: list[str] = Form([]),
    instructionsHe: list[str] = Form([]),
    homeFriendly: bool = Form(False),
    image: list[UploadFile] = File(...),
    video: UploadFile | None = File(None),
    user_id: str = Depends(require_admin),
):
    _validate_exercise_fields(name, nameHe, bodyParts)
    if not image:
        raise HTTPException(status_code=400, detail="At least one image is required")
    images = await _read_validated_images(image)
    video_data, video_content_type = (None, None)
    if video is not None:
        video_data, video_content_type = await _read_validated_video(video)

    try:
        return await create_exercise(
            name=name,
            name_he=nameHe,
            body_parts=bodyParts,
            sub_body_parts=subBodyParts,
            sub_body_parts_he=subBodyPartsHe,
            target_muscles=targetMuscles,
            target_muscles_he=targetMusclesHe,
            secondary_muscles=secondaryMuscles,
            secondary_muscles_he=secondaryMusclesHe,
            equipments=equipments,
            equipments_he=equipmentsHe,
            instructions=instructions,
            instructions_he=instructionsHe,
            home_friendly=homeFriendly,
            images=images,
            video_data=video_data,
            video_content_type=video_content_type,
            admin_id=user_id,
        )
    except RuntimeError as e:
        print("admin create exercise config error:", e)
        raise HTTPException(status_code=500, detail="Failed to create exercise")
    except Exception as e:
        print("admin create exercise error:", e)
        raise HTTPException(status_code=500, detail="Failed to create exercise")


@routerAdmin.put("/exercises/{exercise_id}")
@limiter.limit("20/minute")
async def update_exercise_route(
    request: Request,
    exercise_id: str,
    name: str = Form(...),
    nameHe: str = Form(...),
    bodyParts: list[str] = Form(...),
    subBodyParts: list[str] = Form([]),
    subBodyPartsHe: list[str] = Form([]),
    targetMuscles: list[str] = Form([]),
    targetMusclesHe: list[str] = Form([]),
    secondaryMuscles: list[str] = Form([]),
    secondaryMusclesHe: list[str] = Form([]),
    equipments: list[str] = Form([]),
    equipmentsHe: list[str] = Form([]),
    instructions: list[str] = Form([]),
    instructionsHe: list[str] = Form([]),
    homeFriendly: bool = Form(False),
    imageUrls: list[str] = Form([]),
    image: list[UploadFile] = File([]),
    video: UploadFile | None = File(None),
    removeVideo: bool = Form(False),
    user_id: str = Depends(require_admin),
):
    _validate_exercise_fields(name, nameHe, bodyParts)
    new_images = await _read_validated_images(image) if image else []
    if not imageUrls and not new_images:
        raise HTTPException(status_code=400, detail="At least one image is required")
    video_data, video_content_type = (None, None)
    if video is not None:
        video_data, video_content_type = await _read_validated_video(video)

    try:
        return await update_exercise(
            exercise_id,
            name=name,
            name_he=nameHe,
            body_parts=bodyParts,
            sub_body_parts=subBodyParts,
            sub_body_parts_he=subBodyPartsHe,
            target_muscles=targetMuscles,
            target_muscles_he=targetMusclesHe,
            secondary_muscles=secondaryMuscles,
            secondary_muscles_he=secondaryMusclesHe,
            equipments=equipments,
            equipments_he=equipmentsHe,
            instructions=instructions,
            instructions_he=instructionsHe,
            home_friendly=homeFriendly,
            keep_image_urls=imageUrls,
            new_images=new_images,
            video_data=video_data,
            video_content_type=video_content_type,
            remove_video=removeVideo,
            admin_id=user_id,
        )
    except LookupError:
        raise HTTPException(status_code=404, detail="Exercise not found")
    except RuntimeError as e:
        print("admin update exercise config error:", e)
        raise HTTPException(status_code=500, detail="Failed to update exercise")
    except Exception as e:
        print("admin update exercise error:", e)
        raise HTTPException(status_code=500, detail="Failed to update exercise")


@routerAdmin.post("/exercises/{exercise_id}/freeze")
@limiter.limit("20/minute")
async def freeze_exercise_route(request: Request, exercise_id: str, user_id: str = Depends(require_admin)):
    try:
        return await toggle_exercise_freeze(exercise_id, user_id)
    except LookupError:
        raise HTTPException(status_code=404, detail="Exercise not found")
    except RuntimeError as e:
        print("admin freeze exercise config error:", e)
        raise HTTPException(status_code=500, detail="Failed to update exercise")
    except Exception as e:
        print("admin freeze exercise error:", e)
        raise HTTPException(status_code=500, detail="Failed to update exercise")


@routerAdmin.delete("/exercises/{exercise_id}")
@limiter.limit("20/minute")
async def delete_exercise_route(request: Request, exercise_id: str, user_id: str = Depends(require_admin)):
    try:
        await delete_exercise(exercise_id, user_id)
        return {"status": "deleted"}
    except LookupError:
        raise HTTPException(status_code=404, detail="Exercise not found")
    except RuntimeError as e:
        print("admin delete exercise config error:", e)
        raise HTTPException(status_code=500, detail="Failed to delete exercise")
    except Exception as e:
        print("admin delete exercise error:", e)
        raise HTTPException(status_code=500, detail="Failed to delete exercise")


@routerAdmin.get("/notifications/audience-preview")
@limiter.limit("60/minute")
async def notifications_audience_preview_route(
    request: Request,
    activity: str = "any",
    platform: str = "any",
    user_id: str = Depends(require_admin),
):
    if activity not in ACTIVITY_SEGMENTS:
        raise HTTPException(status_code=400, detail="Invalid activity")
    if platform not in PLATFORM_SEGMENTS:
        raise HTTPException(status_code=400, detail="Invalid platform")

    try:
        return await preview_audience(activity, platform)
    except RuntimeError as e:
        print("admin notifications audience preview config error:", e)
        raise HTTPException(status_code=500, detail="Failed to compute audience")
    except Exception as e:
        print("admin notifications audience preview error:", e)
        raise HTTPException(status_code=500, detail="Failed to compute audience")


@routerAdmin.post("/notifications/send")
@limiter.limit("10/minute")
async def notifications_send_route(
    request: Request,
    title: str = Body(...),
    body: str = Body(...),
    screen: str | None = Body(None),
    activity: str = Body("any"),
    platform: str = Body("any"),
    user_id: str = Depends(require_admin),
):
    if not title.strip():
        raise HTTPException(status_code=400, detail="title is required")
    if not body.strip():
        raise HTTPException(status_code=400, detail="body is required")
    if activity not in ACTIVITY_SEGMENTS:
        raise HTTPException(status_code=400, detail="Invalid activity")
    if platform not in PLATFORM_SEGMENTS:
        raise HTTPException(status_code=400, detail="Invalid platform")
    if screen and screen not in VALID_SCREENS:
        raise HTTPException(status_code=400, detail="Invalid screen")

    try:
        return await send_notification(
            title.strip(), body.strip(), screen.strip() if screen else None, activity, platform, user_id
        )
    except RuntimeError as e:
        print("admin notifications send config error:", e)
        raise HTTPException(status_code=500, detail="Failed to send notification")
    except Exception as e:
        print("admin notifications send error:", e)
        raise HTTPException(status_code=500, detail="Failed to send notification")


@routerAdmin.get("/notifications/history")
@limiter.limit("60/minute")
async def notifications_history_route(request: Request, user_id: str = Depends(require_admin)):
    try:
        return await get_notification_history()
    except RuntimeError as e:
        print("admin notifications history config error:", e)
        raise HTTPException(status_code=500, detail="Failed to load notification history")
    except Exception as e:
        print("admin notifications history error:", e)
        raise HTTPException(status_code=500, detail="Failed to load notification history")
