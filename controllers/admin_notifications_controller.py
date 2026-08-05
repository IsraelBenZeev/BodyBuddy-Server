import os
from datetime import datetime, timedelta, timezone

import httpx

from controllers.admin_controller import _supabase_headers, log_admin_action

EXPO_PUSH_URL = "https://exp.host/--/api/v2/push/send"
EXPO_CHUNK_SIZE = 100

ACTIVITY_SEGMENTS = {"any", "active_7d", "active_30d", "inactive_30d"}
PLATFORM_SEGMENTS = {"any", "ios", "android"}

# תואם 1:1 ל-SCREEN_ROUTES ב-BodyBuddy-Client/src/hooks/useNotificationNavigation.ts.
# privacy-policy ו-workout_plan לא נתמכים בכוונה - ראה הערה שם.
VALID_SCREENS = {"home", "workouts", "nutrition", "profile"}


def _chunk(items: list, size: int):
    for i in range(0, len(items), size):
        yield items[i : i + size]


async def _list_all_auth_users(client: httpx.AsyncClient, supabase_url: str, headers: dict) -> list[dict]:
    users: list[dict] = []
    page = 1
    per_page = 1000
    while True:
        response = await client.get(
            f"{supabase_url}/auth/v1/admin/users",
            params={"page": page, "per_page": per_page},
            headers=headers,
        )
        response.raise_for_status()
        batch = response.json().get("users", [])
        users.extend(batch)
        if len(batch) < per_page:
            break
        page += 1
    return users


def _matches_activity(auth_user: dict, activity: str, now: datetime) -> bool:
    if activity == "any":
        return True

    last_sign_in = auth_user.get("last_sign_in_at")
    last_active = datetime.fromisoformat(last_sign_in.replace("Z", "+00:00")) if last_sign_in else None

    if activity == "active_7d":
        return last_active is not None and now - last_active <= timedelta(days=7)
    if activity == "active_30d":
        return last_active is not None and now - last_active <= timedelta(days=30)
    if activity == "inactive_30d":
        return last_active is None or now - last_active > timedelta(days=30)
    return True


async def _resolve_target_user_ids(
    client: httpx.AsyncClient, supabase_url: str, headers: dict, activity: str, platform: str
) -> set[str]:
    auth_users = await _list_all_auth_users(client, supabase_url, headers)
    now = datetime.now(timezone.utc)
    matching = {user["id"] for user in auth_users if _matches_activity(user, activity, now)}

    if platform == "any":
        return matching

    tokens_response = await client.get(
        f"{supabase_url}/rest/v1/user_push_tokens",
        params={"select": "user_id,platform"},
        headers=headers,
    )
    tokens_response.raise_for_status()
    platform_user_ids = {row["user_id"] for row in tokens_response.json() if row["platform"] == platform}
    return matching & platform_user_ids


async def _tokens_for_user_ids(client: httpx.AsyncClient, supabase_url: str, headers: dict, user_ids: set[str]) -> list[str]:
    if not user_ids:
        return []
    response = await client.get(
        f"{supabase_url}/rest/v1/user_push_tokens",
        params={"select": "expo_push_token", "user_id": f"in.({','.join(user_ids)})"},
        headers=headers,
    )
    response.raise_for_status()
    return [row["expo_push_token"] for row in response.json()]


async def preview_audience(activity: str, platform: str) -> dict:
    supabase_url = os.getenv("SUPABASE_URL")
    headers = _supabase_headers()

    async with httpx.AsyncClient(timeout=15.0) as client:
        target_user_ids = await _resolve_target_user_ids(client, supabase_url, headers, activity, platform)
        tokens = await _tokens_for_user_ids(client, supabase_url, headers, target_user_ids)

    return {"audienceSize": len(tokens)}


async def send_notification(
    title: str, body: str, screen: str | None, activity: str, platform: str, admin_id: str
) -> dict:
    supabase_url = os.getenv("SUPABASE_URL")
    headers = _supabase_headers()
    navigation = {"screen": screen} if screen else None

    async with httpx.AsyncClient(timeout=20.0) as client:
        target_user_ids = await _resolve_target_user_ids(client, supabase_url, headers, activity, platform)
        tokens = await _tokens_for_user_ids(client, supabase_url, headers, target_user_ids)

        status = "sent"
        try:
            for chunk in _chunk(tokens, EXPO_CHUNK_SIZE):
                messages = [{"to": token, "title": title, "body": body, "data": navigation or {}} for token in chunk]
                response = await client.post(
                    EXPO_PUSH_URL,
                    headers={"Content-Type": "application/json", "Accept": "application/json"},
                    json=messages,
                )
                response.raise_for_status()
        except Exception as e:
            print("admin send notification expo error:", e)
            status = "failed"

        broadcast_response = await client.post(
            f"{supabase_url}/rest/v1/notification_broadcasts",
            headers={**headers, "Content-Type": "application/json", "Prefer": "return=representation"},
            json={
                "title": title,
                "body": body,
                "navigation": navigation,
                "sent_via": "admin_panel",
                "admin_id": admin_id,
                "activity_segment": activity,
                "platform_segment": platform,
                "audience_size": len(tokens),
                "status": status,
            },
        )
        broadcast_response.raise_for_status()
        broadcast = broadcast_response.json()[0]

    await log_admin_action(
        admin_id,
        "send_notification",
        screen or "no-navigation",
        {"title": title, "body": body, "audienceSize": len(tokens), "activity": activity, "platform": platform},
    )

    return {
        "id": broadcast["id"],
        "sentAt": broadcast["sent_at"],
        "title": title,
        "body": body,
        "screen": screen,
        "audienceSize": len(tokens),
        "status": status,
    }


async def get_notification_history() -> list[dict]:
    supabase_url = os.getenv("SUPABASE_URL")
    headers = _supabase_headers()

    async with httpx.AsyncClient(timeout=15.0) as client:
        broadcasts_response = await client.get(
            f"{supabase_url}/rest/v1/notification_broadcasts",
            params={"select": "*", "order": "sent_at.desc", "limit": "100"},
            headers=headers,
        )
        broadcasts_response.raise_for_status()
        broadcasts = broadcasts_response.json()

        admin_ids = {row["admin_id"] for row in broadcasts if row.get("admin_id")}
        admins_by_id: dict[str, dict] = {}
        if admin_ids:
            profiles_response = await client.get(
                f"{supabase_url}/rest/v1/profiles",
                params={"select": "user_id,full_name", "user_id": f"in.({','.join(admin_ids)})"},
                headers=headers,
            )
            profiles_response.raise_for_status()
            admins_by_id = {row["user_id"]: row for row in profiles_response.json()}

    return [
        {
            "id": row["id"],
            "sentAt": row["sent_at"],
            "title": row["title"],
            "body": row["body"],
            "screen": (row.get("navigation") or {}).get("screen"),
            "criteria": {
                "activity": row.get("activity_segment") or "any",
                "platform": row.get("platform_segment") or "any",
            },
            "audienceSize": row.get("audience_size") or 0,
            "status": row.get("status") or "sent",
            "sentByName": (admins_by_id.get(row.get("admin_id")) or {}).get("full_name"),
            "sentVia": row.get("sent_via") or "admin_panel",
        }
        for row in broadcasts
    ]
