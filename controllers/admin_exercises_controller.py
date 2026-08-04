import os
import uuid

import httpx

from controllers.admin_controller import _supabase_headers, log_admin_action
from controllers.reports_controller import send_exercise_added_email
from controllers.uploads_controller import upload_exercise_images, upload_exercise_video

EXERCISES_TABLE = "exercises_v2"
EXERCISES_PAGE_SIZE = 20
VALID_BODY_PARTS = {"chest", "back", "shoulders", "upper arms", "upper legs", "waist"}
VALID_STATUSES = {"active", "frozen"}

BODY_PART_HE = {
    "chest": "חזה",
    "back": "גב",
    "shoulders": "כתפיים",
    "upper arms": "ידיים עליונות",
    "upper legs": "רגליים עליונות",
    "waist": "מותניים",
}

EXERCISE_SELECT = "*"


def _to_exercise(row: dict) -> dict:
    return {
        "id": row["exerciseId"],
        "name": row["name"],
        "nameHe": row.get("name_he") or "",
        "bodyParts": row.get("bodyParts") or [],
        "bodyPartsHe": row.get("bodyParts_he") or [],
        "subBodyParts": row.get("subBodyParts") or [],
        "subBodyPartsHe": row.get("subBodyParts_he") or [],
        "targetMuscles": row.get("targetMuscles") or [],
        "targetMusclesHe": row.get("targetMuscles_he") or [],
        "secondaryMuscles": row.get("secondaryMuscles") or [],
        "secondaryMusclesHe": row.get("secondaryMuscles_he") or [],
        "equipments": row.get("equipments") or [],
        "equipmentsHe": row.get("equipments_he") or [],
        "instructions": row.get("instructions") or [],
        "instructionsHe": row.get("instructions_he") or [],
        "homeFriendly": bool(row.get("homeFriendly")),
        "status": row.get("status") or "active",
        "imageUrls": row.get("imageUrls") or [],
        "videoUrl": row.get("videoUrl"),
    }


def _parse_total(content_range: str | None) -> int:
    if not content_range or "/" not in content_range:
        return 0
    total = content_range.rsplit("/", 1)[1]
    return int(total) if total.isdigit() else 0


async def list_exercises(
    search: str, page: int, *, body_part: str | None = None, status: str | None = None
) -> dict:
    supabase_url = os.getenv("SUPABASE_URL")
    headers = {**_supabase_headers(), "Prefer": "count=exact"}

    params = {
        "select": EXERCISE_SELECT,
        "order": "name.asc",
        "limit": str(EXERCISES_PAGE_SIZE),
        "offset": str((page - 1) * EXERCISES_PAGE_SIZE),
    }
    query = search.strip()
    if query:
        params["name"] = f"ilike.*{query}*"
    if body_part:
        params["bodyParts"] = f"cs.{{{body_part}}}"
    if status:
        params["status"] = f"eq.{status}"

    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.get(f"{supabase_url}/rest/v1/{EXERCISES_TABLE}", params=params, headers=headers)
        response.raise_for_status()
        rows = response.json()
        total = _parse_total(response.headers.get("content-range"))

    return {
        "items": [_to_exercise(row) for row in rows],
        "page": page,
        "pageSize": EXERCISES_PAGE_SIZE,
        "total": total,
    }


async def get_exercise(exercise_id: str) -> dict:
    supabase_url = os.getenv("SUPABASE_URL")
    headers = _supabase_headers()

    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.get(
            f"{supabase_url}/rest/v1/{EXERCISES_TABLE}",
            params={"select": EXERCISE_SELECT, "exerciseId": f"eq.{exercise_id}"},
            headers=headers,
        )
        response.raise_for_status()
        rows = response.json()

    if not rows:
        raise LookupError(f"Exercise {exercise_id} not found")
    return _to_exercise(rows[0])


async def create_exercise(
    *,
    name: str,
    name_he: str,
    body_parts: list[str],
    sub_body_parts: list[str],
    sub_body_parts_he: list[str],
    target_muscles: list[str],
    target_muscles_he: list[str],
    secondary_muscles: list[str],
    secondary_muscles_he: list[str],
    equipments: list[str],
    equipments_he: list[str],
    instructions: list[str],
    instructions_he: list[str],
    home_friendly: bool,
    images: list[tuple[bytes, str]],
    video_data: bytes | None,
    video_content_type: str | None,
    admin_id: str,
) -> dict:
    exercise_id = f"admin_{uuid.uuid4().hex}"
    image_urls = await upload_exercise_images(images, exercise_id)
    video_url = None
    if video_data is not None:
        video_url = await upload_exercise_video(video_data, video_content_type, exercise_id)

    supabase_url = os.getenv("SUPABASE_URL")
    headers = {**_supabase_headers(), "Content-Type": "application/json", "Prefer": "return=representation"}

    payload = {
        "exerciseId": exercise_id,
        "name": name,
        "name_he": name_he,
        "bodyParts": body_parts,
        "bodyParts_he": [BODY_PART_HE[part] for part in body_parts],
        "subBodyParts": sub_body_parts,
        "subBodyParts_he": sub_body_parts_he,
        "targetMuscles": target_muscles,
        "targetMuscles_he": target_muscles_he,
        "secondaryMuscles": secondary_muscles,
        "secondaryMuscles_he": secondary_muscles_he,
        "equipments": equipments,
        "equipments_he": equipments_he,
        "instructions": instructions,
        "instructions_he": instructions_he,
        "homeFriendly": home_friendly,
        "imageUrls": image_urls,
        "videoUrl": video_url,
        "status": "active",
    }

    async with httpx.AsyncClient(timeout=10.0) as client:
        next_sort_order_response = await client.get(
            f"{supabase_url}/rest/v1/{EXERCISES_TABLE}",
            params={"select": "sort_order", "order": "sort_order.desc", "limit": "1"},
            headers=_supabase_headers(),
        )
        next_sort_order_response.raise_for_status()
        rows = next_sort_order_response.json()
        payload["sort_order"] = (rows[0]["sort_order"] + 1) if rows else 1

        response = await client.post(f"{supabase_url}/rest/v1/{EXERCISES_TABLE}", headers=headers, json=payload)
        response.raise_for_status()
        row = response.json()[0]

    exercise = _to_exercise(row)
    await log_admin_action(admin_id, "create_exercise", exercise["id"])

    try:
        await send_exercise_added_email(exercise, admin_id)
    except Exception as e:
        print("exercise added email error:", e)

    return exercise


async def update_exercise(
    exercise_id: str,
    *,
    name: str,
    name_he: str,
    body_parts: list[str],
    sub_body_parts: list[str],
    sub_body_parts_he: list[str],
    target_muscles: list[str],
    target_muscles_he: list[str],
    secondary_muscles: list[str],
    secondary_muscles_he: list[str],
    equipments: list[str],
    equipments_he: list[str],
    instructions: list[str],
    instructions_he: list[str],
    home_friendly: bool,
    keep_image_urls: list[str] | None,
    new_images: list[tuple[bytes, str]],
    video_data: bytes | None,
    video_content_type: str | None,
    remove_video: bool,
    admin_id: str,
) -> dict:
    supabase_url = os.getenv("SUPABASE_URL")
    headers = {**_supabase_headers(), "Content-Type": "application/json", "Prefer": "return=representation"}

    payload: dict = {
        "name": name,
        "name_he": name_he,
        "bodyParts": body_parts,
        "bodyParts_he": [BODY_PART_HE[part] for part in body_parts],
        "subBodyParts": sub_body_parts,
        "subBodyParts_he": sub_body_parts_he,
        "targetMuscles": target_muscles,
        "targetMuscles_he": target_muscles_he,
        "secondaryMuscles": secondary_muscles,
        "secondaryMuscles_he": secondary_muscles_he,
        "equipments": equipments,
        "equipments_he": equipments_he,
        "instructions": instructions,
        "instructions_he": instructions_he,
        "homeFriendly": home_friendly,
    }

    if keep_image_urls is not None or new_images:
        uploaded = await upload_exercise_images(new_images, exercise_id) if new_images else []
        payload["imageUrls"] = (keep_image_urls or []) + uploaded

    if video_data is not None:
        payload["videoUrl"] = await upload_exercise_video(video_data, video_content_type, exercise_id)
    elif remove_video:
        payload["videoUrl"] = None

    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.patch(
            f"{supabase_url}/rest/v1/{EXERCISES_TABLE}",
            params={"exerciseId": f"eq.{exercise_id}"},
            headers=headers,
            json=payload,
        )
        response.raise_for_status()
        rows = response.json()

    if not rows:
        raise LookupError(f"Exercise {exercise_id} not found")

    exercise = _to_exercise(rows[0])
    await log_admin_action(admin_id, "update_exercise", exercise_id)
    return exercise


async def toggle_exercise_freeze(exercise_id: str, admin_id: str) -> dict:
    current = await get_exercise(exercise_id)
    new_status = "frozen" if current["status"] == "active" else "active"

    supabase_url = os.getenv("SUPABASE_URL")
    headers = {**_supabase_headers(), "Content-Type": "application/json", "Prefer": "return=representation"}

    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.patch(
            f"{supabase_url}/rest/v1/{EXERCISES_TABLE}",
            params={"exerciseId": f"eq.{exercise_id}"},
            headers=headers,
            json={"status": new_status},
        )
        response.raise_for_status()
        rows = response.json()

    if not rows:
        raise LookupError(f"Exercise {exercise_id} not found")

    exercise = _to_exercise(rows[0])
    action = "freeze_exercise" if new_status == "frozen" else "unfreeze_exercise"
    await log_admin_action(admin_id, action, exercise_id)
    return exercise


async def delete_exercise(exercise_id: str, admin_id: str) -> None:
    supabase_url = os.getenv("SUPABASE_URL")
    headers = {**_supabase_headers(), "Prefer": "return=representation"}

    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.delete(
            f"{supabase_url}/rest/v1/{EXERCISES_TABLE}",
            params={"exerciseId": f"eq.{exercise_id}"},
            headers=headers,
        )
        response.raise_for_status()
        rows = response.json()

    if not rows:
        raise LookupError(f"Exercise {exercise_id} not found")

    await log_admin_action(admin_id, "delete_exercise", exercise_id)
