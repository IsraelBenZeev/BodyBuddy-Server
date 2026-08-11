import os
from datetime import datetime, timedelta, timezone

import httpx

from controllers.admin_controller import _supabase_headers, log_admin_action
from controllers.scheduler_controller import (
    AUTOMATION_TRIGGER_DEFAULTS,
    AUTOMATION_TYPES,
    MESSAGES,
    WEEKLY_SUMMARY_DEFAULTS,
)

EXPO_PUSH_URL = "https://exp.host/--/api/v2/push/send"
EXPO_CHUNK_SIZE = 100

ACTIVITY_SEGMENTS = {"any", "active_7d", "active_30d", "inactive_30d"}
PLATFORM_SEGMENTS = {"any", "ios", "android"}
TARGET_MODES = {"segment", "specific_users"}

AUTOMATION_UPDATABLE_COLUMNS = {
    "enabled": "enabled",
    "title": "title",
    "body": "body",
    "titleSuccess": "title_success",
    "bodySuccess": "body_success",
    "titleFail": "title_fail",
    "bodyFail": "body_fail",
    "screen": "screen",
    "hour": "hour",
    "dayOfWeek": "day_of_week",
    "thresholdPercent": "threshold_percent",
    "firstReminderDelayHours": "first_reminder_delay_hours",
    "reminderIntervalHours": "reminder_interval_hours",
}

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


async def preview_specific_users_audience(user_ids: list[str]) -> dict:
    if not user_ids:
        return {"audienceSize": 0, "users": []}

    supabase_url = os.getenv("SUPABASE_URL")
    headers = _supabase_headers()

    async with httpx.AsyncClient(timeout=15.0) as client:
        response = await client.get(
            f"{supabase_url}/rest/v1/user_push_tokens",
            params={"select": "user_id,platform", "user_id": f"in.({','.join(user_ids)})"},
            headers=headers,
        )
        response.raise_for_status()
        rows = response.json()

    platforms_by_user: dict[str, list[str]] = {}
    for row in rows:
        platforms_by_user.setdefault(row["user_id"], []).append(row["platform"])

    users = [
        {
            "userId": user_id,
            "deviceCount": len(platforms_by_user.get(user_id, [])),
            "platforms": sorted(set(platforms_by_user.get(user_id, []))),
        }
        for user_id in user_ids
    ]
    return {"audienceSize": len(rows), "users": users}


async def send_notification(
    title: str,
    body: str,
    screen: str | None,
    activity: str,
    platform: str,
    admin_id: str,
    target_mode: str = "segment",
    user_ids: list[str] | None = None,
) -> dict:
    supabase_url = os.getenv("SUPABASE_URL")
    headers = _supabase_headers()
    navigation = {"screen": screen} if screen else None

    async with httpx.AsyncClient(timeout=20.0) as client:
        if target_mode == "specific_users":
            target_user_ids = set(user_ids or [])
        else:
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
                "target_type": target_mode,
                "recipient_user_ids": list(target_user_ids) if target_mode == "specific_users" else None,
            },
        )
        broadcast_response.raise_for_status()
        broadcast = broadcast_response.json()[0]

    await log_admin_action(
        admin_id,
        "send_notification",
        screen or "no-navigation",
        {
            "title": title,
            "body": body,
            "audienceSize": len(tokens),
            "targetMode": target_mode,
            "activity": activity if target_mode == "segment" else None,
            "platform": platform if target_mode == "segment" else None,
            "recipientCount": len(target_user_ids) if target_mode == "specific_users" else None,
        },
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
        recipient_ids: set[str] = set()
        for row in broadcasts:
            recipient_ids.update(row.get("recipient_user_ids") or [])

        profiles_by_id: dict[str, dict] = {}
        lookup_ids = admin_ids | recipient_ids
        if lookup_ids:
            profiles_response = await client.get(
                f"{supabase_url}/rest/v1/profiles",
                params={"select": "user_id,full_name", "user_id": f"in.({','.join(lookup_ids)})"},
                headers=headers,
            )
            profiles_response.raise_for_status()
            profiles_by_id = {row["user_id"]: row for row in profiles_response.json()}

        emails_by_id: dict[str, str] = {}
        if recipient_ids:
            auth_users = await _list_all_auth_users(client, supabase_url, headers)
            emails_by_id = {user["id"]: user.get("email") for user in auth_users if user["id"] in recipient_ids}

    def _recipient(user_id: str) -> dict:
        name = (profiles_by_id.get(user_id) or {}).get("full_name")
        email = emails_by_id.get(user_id)
        return {"id": user_id, "name": name or email or "משתמש לא ידוע", "email": email}

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
            "sentByName": (profiles_by_id.get(row.get("admin_id")) or {}).get("full_name"),
            "sentVia": row.get("sent_via") or "admin_panel",
            "targetType": row.get("target_type") or "segment",
            "recipients": [_recipient(user_id) for user_id in (row.get("recipient_user_ids") or [])],
            "notificationType": row.get("notification_type"),
            "dedupKey": row.get("dedup_key"),
        }
        for row in broadcasts
    ]


async def get_automations() -> list[dict]:
    supabase_url = os.getenv("SUPABASE_URL")
    headers = _supabase_headers()

    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.get(
            f"{supabase_url}/rest/v1/notification_automations",
            params={"select": "*"},
            headers=headers,
        )
        response.raise_for_status()
        rows_by_type = {row["type"]: row for row in response.json()}

    order = ["workout_reminder", "nutrition_reminder", "profile_incomplete", "weekly_summary"]
    result = []
    for automation_type in order:
        row = rows_by_type.get(automation_type, {})
        trigger_defaults = AUTOMATION_TRIGGER_DEFAULTS[automation_type]
        entry: dict = {
            "type": automation_type,
            "enabled": row.get("enabled", True),
            "screen": row.get("screen"),
            "hour": row.get("hour"),
            "dayOfWeek": row.get("day_of_week"),
            "thresholdPercent": row.get("threshold_percent"),
            "firstReminderDelayHours": row.get("first_reminder_delay_hours"),
            "reminderIntervalHours": row.get("reminder_interval_hours"),
            "updatedAt": row.get("updated_at"),
        }
        if automation_type == "weekly_summary":
            entry["titleSuccess"] = row.get("title_success")
            entry["bodySuccess"] = row.get("body_success")
            entry["titleFail"] = row.get("title_fail")
            entry["bodyFail"] = row.get("body_fail")
            entry["defaults"] = {**trigger_defaults, **WEEKLY_SUMMARY_DEFAULTS}
        else:
            default_message = MESSAGES[automation_type]
            entry["title"] = row.get("title")
            entry["body"] = row.get("body")
            entry["defaults"] = {
                **trigger_defaults,
                "title": default_message["title"],
                "body": default_message["body"],
                "screen": (default_message.get("data") or {}).get("screen"),
            }
        result.append(entry)

    return result


async def update_automation(automation_type: str, updates: dict, admin_id: str) -> dict:
    supabase_url = os.getenv("SUPABASE_URL")
    headers = {**_supabase_headers(), "Content-Type": "application/json", "Prefer": "return=representation"}

    patch_body = {
        AUTOMATION_UPDATABLE_COLUMNS[key]: value for key, value in updates.items() if key in AUTOMATION_UPDATABLE_COLUMNS
    }
    patch_body["updated_at"] = datetime.now(timezone.utc).isoformat()
    patch_body["updated_by"] = admin_id

    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.patch(
            f"{supabase_url}/rest/v1/notification_automations",
            params={"type": f"eq.{automation_type}"},
            headers=headers,
            json=patch_body,
        )
        response.raise_for_status()
        rows = response.json()

    await log_admin_action(admin_id, "update_notification_automation", automation_type, updates)

    return rows[0] if rows else {}


async def get_broadcast_recipients(dedup_key: str) -> list[dict]:
    supabase_url = os.getenv("SUPABASE_URL")
    headers = _supabase_headers()

    async with httpx.AsyncClient(timeout=15.0) as client:
        response = await client.get(
            f"{supabase_url}/rest/v1/push_queue",
            params={
                "dedup_key": f"eq.{dedup_key}",
                "select": "user_id,status,attempts,last_error,updated_at",
                "order": "updated_at.desc",
            },
            headers=headers,
        )
        response.raise_for_status()
        rows = response.json()

        user_ids = {row["user_id"] for row in rows}
        profiles_by_id: dict[str, dict] = {}
        emails_by_id: dict[str, str] = {}
        if user_ids:
            profiles_response = await client.get(
                f"{supabase_url}/rest/v1/profiles",
                params={"select": "user_id,full_name", "user_id": f"in.({','.join(user_ids)})"},
                headers=headers,
            )
            profiles_response.raise_for_status()
            profiles_by_id = {row["user_id"]: row for row in profiles_response.json()}

            auth_users = await _list_all_auth_users(client, supabase_url, headers)
            emails_by_id = {user["id"]: user.get("email") for user in auth_users if user["id"] in user_ids}

    def _label(user_id: str) -> str:
        name = (profiles_by_id.get(user_id) or {}).get("full_name")
        return name or emails_by_id.get(user_id) or "משתמש לא ידוע"

    return [
        {
            "userId": row["user_id"],
            "userName": _label(row["user_id"]),
            "status": row["status"],
            "attempts": row["attempts"],
            "lastError": row.get("last_error"),
            "updatedAt": row["updated_at"],
        }
        for row in rows
    ]
