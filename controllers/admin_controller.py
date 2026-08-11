import os
from datetime import date, datetime, timedelta, timezone

import httpx

USERS_PAGE_SIZE = 20
BAN_DURATION = "876000h"
AUTH_PROVIDERS = {"email", "google", "apple", "facebook"}


def _supabase_headers() -> dict:
    supabase_url = os.getenv("SUPABASE_URL")
    service_role_key = os.getenv("SUPABASE_SERVICE_ROLE_KEY")

    if not supabase_url or not service_role_key:
        raise RuntimeError("SUPABASE_URL/SUPABASE_SERVICE_ROLE_KEY not configured")

    return {
        "apikey": service_role_key,
        "Authorization": f"Bearer {service_role_key}",
    }


def _auth_provider(auth_user: dict) -> str:
    provider = (auth_user.get("app_metadata") or {}).get("provider")
    return provider if provider in AUTH_PROVIDERS else "email"


def _parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _to_summary(auth_user: dict, profile: dict | None, platform: str | None) -> dict:
    return {
        "id": auth_user["id"],
        "name": (profile or {}).get("full_name") or auth_user.get("email") or "ללא שם",
        "email": auth_user.get("email"),
        "platform": platform,
        "status": "suspended" if auth_user.get("banned_until") else "active",
        "authProvider": _auth_provider(auth_user),
        "joinedAt": auth_user.get("created_at"),
        "lastActiveAt": auth_user.get("last_sign_in_at"),
    }


async def _fetch_all_auth_users(client: httpx.AsyncClient, supabase_url: str, headers: dict) -> list[dict]:
    response = await client.get(
        f"{supabase_url}/auth/v1/admin/users",
        params={"page": "1", "per_page": "1000"},
        headers=headers,
    )
    response.raise_for_status()
    return response.json().get("users", [])


async def _fetch_profiles_by_user_id(client: httpx.AsyncClient, supabase_url: str, headers: dict) -> dict:
    response = await client.get(
        f"{supabase_url}/rest/v1/profiles",
        params={"select": "user_id,full_name,is_admin"},
        headers=headers,
    )
    response.raise_for_status()
    return {row["user_id"]: row for row in response.json()}


async def _fetch_latest_platform_by_user_id(client: httpx.AsyncClient, supabase_url: str, headers: dict) -> dict:
    response = await client.get(
        f"{supabase_url}/rest/v1/user_push_tokens",
        params={"select": "user_id,platform,updated_at", "order": "updated_at.desc"},
        headers=headers,
    )
    response.raise_for_status()
    platform_by_user_id: dict = {}
    for row in response.json():
        platform_by_user_id.setdefault(row["user_id"], row["platform"])
    return platform_by_user_id


async def list_users(
    search: str,
    page: int,
    *,
    status: str | None = None,
    platform: str | None = None,
    auth_provider: str | None = None,
    inactive_days: int | None = None,
    joined_from: date | None = None,
    joined_to: date | None = None,
) -> dict:
    supabase_url = os.getenv("SUPABASE_URL")
    headers = _supabase_headers()

    async with httpx.AsyncClient(timeout=10.0) as client:
        auth_users = await _fetch_all_auth_users(client, supabase_url, headers)
        profiles_by_user_id = await _fetch_profiles_by_user_id(client, supabase_url, headers)
        platform_by_user_id = await _fetch_latest_platform_by_user_id(client, supabase_url, headers)

    summaries = [
        _to_summary(auth_user, profiles_by_user_id.get(auth_user["id"]), platform_by_user_id.get(auth_user["id"]))
        for auth_user in auth_users
    ]
    summaries.sort(key=lambda user: user["joinedAt"] or "", reverse=True)

    query = search.strip().lower()
    if query:
        summaries = [
            user
            for user in summaries
            if query in (user["name"] or "").lower() or query in (user["email"] or "").lower()
        ]

    if status:
        summaries = [user for user in summaries if user["status"] == status]
    if platform:
        summaries = [user for user in summaries if user["platform"] == platform]
    if auth_provider:
        summaries = [user for user in summaries if user["authProvider"] == auth_provider]
    if inactive_days is not None:
        cutoff = datetime.now(timezone.utc) - timedelta(days=inactive_days)
        summaries = [
            user
            for user in summaries
            if (last_active := _parse_iso(user["lastActiveAt"])) is None or last_active <= cutoff
        ]
    if joined_from is not None:
        summaries = [
            user
            for user in summaries
            if (joined := _parse_iso(user["joinedAt"])) and joined.date() >= joined_from
        ]
    if joined_to is not None:
        summaries = [
            user
            for user in summaries
            if (joined := _parse_iso(user["joinedAt"])) and joined.date() <= joined_to
        ]

    total = len(summaries)
    start = (page - 1) * USERS_PAGE_SIZE
    items = summaries[start : start + USERS_PAGE_SIZE]

    return {"items": items, "page": page, "pageSize": USERS_PAGE_SIZE, "total": total}


async def get_new_user_counts() -> dict:
    supabase_url = os.getenv("SUPABASE_URL")
    headers = _supabase_headers()

    async with httpx.AsyncClient(timeout=10.0) as client:
        auth_users = await _fetch_all_auth_users(client, supabase_url, headers)

    week_ago = datetime.now(timezone.utc) - timedelta(days=7)
    new_this_week = sum(
        1 for user in auth_users if (joined := _parse_iso(user.get("created_at"))) and joined >= week_ago
    )

    return {"totalUsers": len(auth_users), "newThisWeek": new_this_week}


async def get_active_user_counts() -> dict:
    supabase_url = os.getenv("SUPABASE_URL")
    headers = {**_supabase_headers(), "Content-Type": "application/json"}

    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.post(
            f"{supabase_url}/rest/v1/rpc/get_active_session_counts", headers=headers, json={}
        )
        response.raise_for_status()
        rows = response.json()

    row = rows[0] if rows else {"active_today": 0, "active_7d": 0, "active_30d": 0}
    return {
        "activeToday": row["active_today"],
        "active7d": row["active_7d"],
        "active30d": row["active_30d"],
    }


async def _fetch_recent_timestamps(
    client: httpx.AsyncClient, supabase_url: str, headers: dict, table: str, timestamp_field: str, cutoff: datetime
) -> list[dict]:
    response = await client.get(
        f"{supabase_url}/rest/v1/{table}",
        params={
            "select": f"user_id,{timestamp_field}",
            timestamp_field: f"gte.{cutoff.isoformat()}",
        },
        headers=headers,
    )
    response.raise_for_status()
    return response.json()


async def get_engaged_user_counts() -> dict:
    supabase_url = os.getenv("SUPABASE_URL")
    headers = _supabase_headers()
    cutoff = datetime.now(timezone.utc) - timedelta(days=30)

    async with httpx.AsyncClient(timeout=10.0) as client:
        sessions = await _fetch_recent_timestamps(client, supabase_url, headers, "sessions", "completed_at", cutoff)
        workouts_plans = await _fetch_recent_timestamps(
            client, supabase_url, headers, "workouts_plans", "created_at", cutoff
        )
        nutrition_entries = await _fetch_recent_timestamps(
            client, supabase_url, headers, "nutrition_entries", "created_at", cutoff
        )

    last_engaged_at: dict[str, datetime] = {}
    for rows, timestamp_field in (
        (sessions, "completed_at"),
        (workouts_plans, "created_at"),
        (nutrition_entries, "created_at"),
    ):
        for row in rows:
            occurred_at = _parse_iso(row[timestamp_field])
            if occurred_at is None:
                continue
            user_id = row["user_id"]
            if user_id not in last_engaged_at or occurred_at > last_engaged_at[user_id]:
                last_engaged_at[user_id] = occurred_at

    now = datetime.now(timezone.utc)
    return {
        "activeToday": sum(1 for t in last_engaged_at.values() if now - t <= timedelta(days=1)),
        "active7d": sum(1 for t in last_engaged_at.values() if now - t <= timedelta(days=7)),
        "active30d": sum(1 for t in last_engaged_at.values() if now - t <= timedelta(days=30)),
    }


async def _fetch_activity(client: httpx.AsyncClient, supabase_url: str, headers: dict, user_id: str) -> list[dict]:
    sessions_response = await client.get(
        f"{supabase_url}/rest/v1/sessions",
        params={
            "select": "id,completed_at",
            "user_id": f"eq.{user_id}",
            "completed_at": "not.is.null",
            "order": "completed_at.desc",
            "limit": "10",
        },
        headers=headers,
    )
    sessions_response.raise_for_status()

    nutrition_response = await client.get(
        f"{supabase_url}/rest/v1/nutrition_entries",
        params={
            "select": "id,created_at",
            "user_id": f"eq.{user_id}",
            "order": "created_at.desc",
            "limit": "10",
        },
        headers=headers,
    )
    nutrition_response.raise_for_status()

    activity = [
        {"id": f"session_{row['id']}", "label": "השלים אימון", "occurredAt": row["completed_at"]}
        for row in sessions_response.json()
    ] + [
        {"id": f"nutrition_{row['id']}", "label": "תיעד ארוחה", "occurredAt": row["created_at"]}
        for row in nutrition_response.json()
    ]
    activity.sort(key=lambda entry: entry["occurredAt"], reverse=True)
    return activity[:15]


async def get_user_detail(user_id: str) -> dict:
    supabase_url = os.getenv("SUPABASE_URL")
    headers = _supabase_headers()

    async with httpx.AsyncClient(timeout=10.0) as client:
        auth_response = await client.get(f"{supabase_url}/auth/v1/admin/users/{user_id}", headers=headers)
        if auth_response.status_code == 404:
            raise LookupError(f"User {user_id} not found")
        auth_response.raise_for_status()
        auth_user = auth_response.json()

        profile_response = await client.get(
            f"{supabase_url}/rest/v1/profiles",
            params={"select": "user_id,full_name,is_admin", "user_id": f"eq.{user_id}"},
            headers=headers,
        )
        profile_response.raise_for_status()
        profile_rows = profile_response.json()

        platform_response = await client.get(
            f"{supabase_url}/rest/v1/user_push_tokens",
            params={"select": "platform", "user_id": f"eq.{user_id}", "order": "updated_at.desc", "limit": "1"},
            headers=headers,
        )
        platform_response.raise_for_status()
        platform_rows = platform_response.json()

        activity = await _fetch_activity(client, supabase_url, headers, user_id)

    summary = _to_summary(
        auth_user,
        profile_rows[0] if profile_rows else None,
        platform_rows[0]["platform"] if platform_rows else None,
    )
    return {**summary, "activity": activity}


async def toggle_user_suspension(user_id: str, admin_id: str) -> dict:
    supabase_url = os.getenv("SUPABASE_URL")
    headers = {**_supabase_headers(), "Content-Type": "application/json"}

    async with httpx.AsyncClient(timeout=10.0) as client:
        current_response = await client.get(f"{supabase_url}/auth/v1/admin/users/{user_id}", headers=headers)
        if current_response.status_code == 404:
            raise LookupError(f"User {user_id} not found")
        current_response.raise_for_status()
        is_currently_suspended = bool(current_response.json().get("banned_until"))
        suspend = not is_currently_suspended

        response = await client.put(
            f"{supabase_url}/auth/v1/admin/users/{user_id}",
            headers=headers,
            json={"ban_duration": BAN_DURATION if suspend else "none"},
        )
        response.raise_for_status()

    await log_admin_action(admin_id, "suspend_user" if suspend else "unsuspend_user", user_id)
    return await get_user_detail(user_id)


async def delete_user(user_id: str, admin_id: str) -> None:
    supabase_url = os.getenv("SUPABASE_URL")
    headers = _supabase_headers()

    async with httpx.AsyncClient(timeout=10.0) as client:
        # body_stats has no cascade delete rule on user_id, unlike every other user-owned table
        cleanup_response = await client.delete(
            f"{supabase_url}/rest/v1/body_stats",
            params={"user_id": f"eq.{user_id}"},
            headers=headers,
        )
        cleanup_response.raise_for_status()

        response = await client.delete(f"{supabase_url}/auth/v1/admin/users/{user_id}", headers=headers)
        if response.status_code == 404:
            raise LookupError(f"User {user_id} not found")
        response.raise_for_status()

    await log_admin_action(admin_id, "delete_user", user_id)


async def log_admin_action(admin_id: str, action: str, target: str, details: dict | None = None) -> None:
    supabase_url = os.getenv("SUPABASE_URL")
    headers = {**_supabase_headers(), "Content-Type": "application/json", "Prefer": "return=minimal"}

    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.post(
            f"{supabase_url}/rest/v1/admin_actions",
            headers=headers,
            json={"admin_id": admin_id, "action": action, "target": target, "details": details},
        )
        response.raise_for_status()
