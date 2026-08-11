import os
import smtplib
from datetime import date, datetime, timedelta
from email.mime.text import MIMEText
from zoneinfo import ZoneInfo

import httpx

IL_TZ = ZoneInfo("Asia/Jerusalem")
UTC_TZ = ZoneInfo("UTC")

EXPO_PUSH_URL = "https://exp.host/--/api/v2/push/send"
EXPO_CHUNK_SIZE = 100
MAX_ATTEMPTS = 5

SCHEDULER_TEST_EMAIL_RECIPIENT = "i0548542122@gmail.com"

DAY_LETTERS = ["א", "ב", "ג", "ד", "ה", "ו", "ש"]  # JS Date.getDay() order: 0=Sunday..6=Saturday

ACTIVITY_MULTIPLIERS = {
    "sedentary": 1.2,
    "lightly_active": 1.375,
    "moderately_active": 1.55,
    "very_active": 1.725,
    "extra_active": 1.9,
}

GOAL_DIRECTION = {"cut": -1, "bulk": 1, "maintain": 0}

MESSAGES = {
    "workout_reminder": {
        "title": "זמן להתאמן! 💪",
        "body": "עדיין לא התאמנת היום - האימון שלך מחכה לך",
        "data": {"screen": "workouts"},
    },
    "profile_incomplete": {
        "title": "כמעט שם!",
        "body": "השלימו את הפרופיל שלכם כדי לקבל תוכנית מותאמת אישית",
        "data": None,
    },
    "nutrition_reminder": {
        "title": "עוד לא תיעדתם היום 🍽️",
        "body": "לא הוכנסו ארוחות ליומן שלכם היום - כל תיעוד מקרב אתכם ליעד",
        "data": {"screen": "nutrition"},
    },
    "weekly_summary": {
        "title": "שבוע מושלם! 🏆",
        "body": "עמדתם בכל היעדים השבוע - כל הכבוד!",
        "data": {"screen": "home"},
    },
}

WEEKLY_SUMMARY_DEFAULTS = {
    "titleSuccess": "שבוע מושלם! 🏆",
    "bodySuccess": "עמדתם בכל היעדים השבוע - כל הכבוד!",
    "titleFail": "סיכום השבוע 💪",
    "bodyFail": "השלמת {actual} מתוך {required} אימונים השבוע - כל התחלה היא הישג, תמשיך ככה!",
    "screen": "home",
}

AUTOMATION_TYPES = {"workout_reminder", "profile_incomplete", "nutrition_reminder", "weekly_summary"}

AUTOMATION_TRIGGER_DEFAULTS = {
    "workout_reminder": {"hour": 20},
    "profile_incomplete": {"firstReminderDelayHours": 24, "reminderIntervalHours": 24},
    "nutrition_reminder": {"hour": 20, "thresholdPercent": 50},
    "weekly_summary": {"dayOfWeek": 5, "hour": 12},
}


def _supabase_config() -> tuple[str, str]:
    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
    if not url or not key:
        raise RuntimeError("SUPABASE_URL/SUPABASE_SERVICE_ROLE_KEY not configured")
    return url, key


def _headers(key: str, prefer: str | None = None) -> dict:
    headers = {"apikey": key, "Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    if prefer:
        headers["Prefer"] = prefer
    return headers


async def _rest_get(client: httpx.AsyncClient, table: str, params) -> list[dict]:
    url, key = _supabase_config()
    response = await client.get(f"{url}/rest/v1/{table}", params=params, headers=_headers(key))
    response.raise_for_status()
    return response.json()


async def _rest_patch(client: httpx.AsyncClient, table: str, params: dict, json_body: dict) -> None:
    url, key = _supabase_config()
    response = await client.patch(
        f"{url}/rest/v1/{table}",
        params=params,
        headers=_headers(key, prefer="return=minimal"),
        json=json_body,
    )
    response.raise_for_status()


async def _rest_delete(client: httpx.AsyncClient, table: str, params: dict) -> None:
    url, key = _supabase_config()
    response = await client.delete(
        f"{url}/rest/v1/{table}", params=params, headers=_headers(key, prefer="return=minimal")
    )
    response.raise_for_status()


async def _rest_insert_ignore_conflicts(
    client: httpx.AsyncClient, table: str, rows: list[dict], on_conflict: str
) -> None:
    if not rows:
        return
    url, key = _supabase_config()
    response = await client.post(
        f"{url}/rest/v1/{table}",
        params={"on_conflict": on_conflict},
        headers=_headers(key, prefer="resolution=ignore-duplicates,return=minimal"),
        json=rows,
    )
    response.raise_for_status()


def _israel_now() -> datetime:
    return datetime.now(IL_TZ)


def _day_letter(d: date) -> str:
    js_day = (d.weekday() + 1) % 7
    return DAY_LETTERS[js_day]


def _day_bounds_utc(d: date) -> tuple[str, str]:
    start = datetime.combine(d, datetime.min.time(), tzinfo=IL_TZ)
    end = start + timedelta(days=1)
    return start.astimezone(UTC_TZ).isoformat(), end.astimezone(UTC_TZ).isoformat()


def _age_from_profile(profile: dict, today: date) -> int | None:
    dob = profile.get("date_of_birth")
    if dob:
        d = date.fromisoformat(dob)
        return today.year - d.year - ((today.month, today.day) < (d.month, d.day))
    return profile.get("age")


def calculate_daily_calories(profile: dict, today: date) -> float | None:
    weight = profile.get("weight")
    height = profile.get("height")
    gender = profile.get("gender")
    activity_level = profile.get("activity_level")
    goal = profile.get("goal")
    age = _age_from_profile(profile, today)

    multiplier = ACTIVITY_MULTIPLIERS.get(activity_level)
    if None in (weight, height, gender, goal, age) or multiplier is None:
        return None

    bmr = 10 * weight + 6.25 * height - 5 * age + (5 if gender == "male" else -161)
    tdee = round(bmr * multiplier)
    offset = profile.get("calorie_offset") or 0
    return tdee + GOAL_DIRECTION.get(goal, 0) * offset


async def _fetch_automations(client: httpx.AsyncClient) -> dict[str, dict]:
    rows = await _rest_get(client, "notification_automations", {"select": "*"})
    return {row["type"]: row for row in rows}


def _param(automation: dict, key: str, default):
    value = automation.get(key)
    return default if value is None else value


def _resolved_message(automation: dict, notification_type: str) -> dict:
    default = MESSAGES[notification_type]
    screen = automation.get("screen")
    return {
        "title": automation.get("title") or default["title"],
        "body": automation.get("body") or default["body"],
        "data": {"screen": screen} if screen else default["data"],
    }


async def _get_tokens_for_users(client: httpx.AsyncClient, user_ids: set[str]) -> dict[str, list[str]]:
    if not user_ids:
        return {}
    rows = await _rest_get(
        client,
        "user_push_tokens",
        {"user_id": f"in.({','.join(user_ids)})", "select": "user_id,expo_push_token"},
    )
    result: dict[str, list[str]] = {}
    for row in rows:
        result.setdefault(row["user_id"], []).append(row["expo_push_token"])
    return result


async def _enqueue_for_users(
    client, user_ids: set[str], notification_type: str, dedup_key_fn, message_fn=None
) -> None:
    if not user_ids:
        return
    tokens_by_user = await _get_tokens_for_users(client, user_ids)
    if not tokens_by_user:
        return

    default_message = MESSAGES.get(notification_type)
    rows = []
    for user_id, tokens in tokens_by_user.items():
        dedup_key = dedup_key_fn(user_id)
        message = message_fn(user_id) if message_fn else default_message
        for token in tokens:
            rows.append(
                {
                    "user_id": user_id,
                    "expo_push_token": token,
                    "notification_type": notification_type,
                    "dedup_key": dedup_key,
                    "title": message["title"],
                    "body": message["body"],
                    "data": message["data"],
                }
            )
    await _rest_insert_ignore_conflicts(client, "push_queue", rows, on_conflict="expo_push_token,dedup_key")


async def _check_workout_reminder(client: httpx.AsyncClient, now_il: datetime, automation: dict) -> None:
    if not automation.get("enabled", True):
        return
    if now_il.hour != _param(automation, "hour", 20):
        return

    today = now_il.date()
    letter = _day_letter(today)

    plans = await _rest_get(
        client, "workouts_plans", {"days_per_week": f"cs.{{{letter}}}", "select": "id,user_id"}
    )
    if not plans:
        return

    plan_ids = [p["id"] for p in plans]
    start_utc, end_utc = _day_bounds_utc(today)
    sessions = await _rest_get(
        client,
        "sessions",
        [
            ("workout_plan_id", f"in.({','.join(plan_ids)})"),
            ("started_at", f"gte.{start_utc}"),
            ("started_at", f"lt.{end_utc}"),
            ("select", "workout_plan_id"),
        ],
    )
    plans_with_session_today = {s["workout_plan_id"] for s in sessions}
    eligible_user_ids = {p["user_id"] for p in plans if p["id"] not in plans_with_session_today}

    dedup_key = f"workout_reminder:{today.isoformat()}"
    message = _resolved_message(automation, "workout_reminder")
    await _enqueue_for_users(
        client, eligible_user_ids, "workout_reminder", lambda _uid: dedup_key, message_fn=lambda _uid: message
    )


async def _list_all_users(client: httpx.AsyncClient) -> list[dict]:
    url, key = _supabase_config()
    users: list[dict] = []
    page = 1
    per_page = 1000
    while True:
        response = await client.get(
            f"{url}/auth/v1/admin/users",
            params={"page": page, "per_page": per_page},
            headers=_headers(key),
        )
        response.raise_for_status()
        batch = response.json().get("users", [])
        users.extend(batch)
        if len(batch) < per_page:
            break
        page += 1
    return users


async def _check_profile_incomplete(client: httpx.AsyncClient, now_il: datetime, automation: dict) -> None:
    if not automation.get("enabled", True):
        return
    first_delay_hours = _param(automation, "first_reminder_delay_hours", 24)
    interval_hours = _param(automation, "reminder_interval_hours", 24)

    cutoff = now_il.astimezone(UTC_TZ) - timedelta(hours=first_delay_hours)
    all_users = await _list_all_users(client)
    candidates = [
        u
        for u in all_users
        if u.get("created_at") and datetime.fromisoformat(u["created_at"].replace("Z", "+00:00")) < cutoff
    ]
    if not candidates:
        return

    candidate_ids = [u["id"] for u in candidates]
    profiles = await _rest_get(
        client, "profiles", {"user_id": f"in.({','.join(candidate_ids)})", "select": "user_id"}
    )
    has_profile = {p["user_id"] for p in profiles}
    missing_ids = [u["id"] for u in candidates if u["id"] not in has_profile]
    if not missing_ids:
        return

    history = await _rest_get(
        client,
        "push_queue",
        {
            "user_id": f"in.({','.join(missing_ids)})",
            "notification_type": "eq.profile_incomplete",
            "select": "user_id,created_at",
            "order": "created_at.asc",
        },
    )
    history_by_user: dict[str, list[datetime]] = {}
    for row in history:
        history_by_user.setdefault(row["user_id"], []).append(
            datetime.fromisoformat(row["created_at"].replace("Z", "+00:00"))
        )

    now_utc = now_il.astimezone(UTC_TZ)
    eligible_dedup: dict[str, str] = {}
    for user_id in missing_ids:
        sent_times = history_by_user.get(user_id, [])
        if len(sent_times) == 0:
            eligible_dedup[user_id] = "profile_incomplete:1"
        elif len(sent_times) == 1 and (now_utc - sent_times[0]) > timedelta(hours=interval_hours):
            eligible_dedup[user_id] = "profile_incomplete:2"

    if not eligible_dedup:
        return

    message = _resolved_message(automation, "profile_incomplete")
    await _enqueue_for_users(
        client,
        set(eligible_dedup.keys()),
        "profile_incomplete",
        lambda uid: eligible_dedup[uid],
        message_fn=lambda _uid: message,
    )


async def _check_nutrition_reminder(client: httpx.AsyncClient, now_il: datetime, automation: dict) -> None:
    if not automation.get("enabled", True):
        return
    if now_il.hour != _param(automation, "hour", 20):
        return
    threshold_percent = _param(automation, "threshold_percent", 50)

    today = now_il.date()
    profiles = await _rest_get(
        client,
        "profiles",
        {"select": "user_id,weight,height,gender,activity_level,goal,calorie_offset,date_of_birth,age"},
    )
    entries = await _rest_get(
        client, "nutrition_entries", {"date": f"eq.{today.isoformat()}", "select": "user_id,calories"}
    )
    consumed: dict[str, int] = {}
    for e in entries:
        consumed[e["user_id"]] = consumed.get(e["user_id"], 0) + (e.get("calories") or 0)

    eligible_user_ids = set()
    for profile in profiles:
        user_id = profile.get("user_id")
        if not user_id:
            continue
        daily_calories = calculate_daily_calories(profile, today)
        if daily_calories is None:
            continue
        if consumed.get(user_id, 0) < daily_calories * (threshold_percent / 100):
            eligible_user_ids.add(user_id)

    dedup_key = f"nutrition_reminder:{today.isoformat()}"
    message = _resolved_message(automation, "nutrition_reminder")
    await _enqueue_for_users(
        client, eligible_user_ids, "nutrition_reminder", lambda _uid: dedup_key, message_fn=lambda _uid: message
    )


async def _check_weekly_summary(client: httpx.AsyncClient, now_il: datetime, automation: dict) -> None:
    if not automation.get("enabled", True):
        return
    today = now_il.date()
    js_day_today = (today.weekday() + 1) % 7
    if js_day_today != _param(automation, "day_of_week", 5) or now_il.hour != _param(automation, "hour", 12):
        return
    screen = automation.get("screen") or WEEKLY_SUMMARY_DEFAULTS["screen"]

    week_start = today - timedelta(days=6)
    week_start_utc, _ = _day_bounds_utc(week_start)
    _, week_end_utc = _day_bounds_utc(today)

    plans = await _rest_get(client, "workouts_plans", {"select": "user_id,days_per_week"})
    required_days: dict[str, int] = {}
    for plan in plans:
        user_id = plan["user_id"]
        required_days[user_id] = required_days.get(user_id, 0) + len(plan.get("days_per_week") or [])
    required_days = {user_id: required for user_id, required in required_days.items() if required > 0}
    if not required_days:
        return

    sessions = await _rest_get(
        client,
        "sessions",
        [
            ("started_at", f"gte.{week_start_utc}"),
            ("started_at", f"lt.{week_end_utc}"),
            ("select", "user_id,started_at"),
        ],
    )
    workout_days: dict[str, set[str]] = {}
    for s in sessions:
        started_il = datetime.fromisoformat(s["started_at"].replace("Z", "+00:00")).astimezone(IL_TZ).date()
        workout_days.setdefault(s["user_id"], set()).add(started_il.isoformat())

    title_success = automation.get("title_success") or WEEKLY_SUMMARY_DEFAULTS["titleSuccess"]
    body_success = automation.get("body_success") or WEEKLY_SUMMARY_DEFAULTS["bodySuccess"]
    title_fail = automation.get("title_fail") or WEEKLY_SUMMARY_DEFAULTS["titleFail"]
    body_fail_template = automation.get("body_fail") or WEEKLY_SUMMARY_DEFAULTS["bodyFail"]

    messages_by_user: dict[str, dict] = {}
    for user_id, required in required_days.items():
        actual = len(workout_days.get(user_id, set()))
        if actual >= required:
            messages_by_user[user_id] = {
                "title": title_success,
                "body": body_success,
                "data": {"screen": screen},
            }
        else:
            messages_by_user[user_id] = {
                "title": title_fail,
                "body": body_fail_template.format(actual=actual, required=required),
                "data": {"screen": screen},
            }

    year, week, _ = today.isocalendar()
    dedup_key = f"weekly_summary:{year}-W{week:02d}"
    await _enqueue_for_users(
        client,
        set(messages_by_user.keys()),
        "weekly_summary",
        lambda _uid: dedup_key,
        message_fn=lambda uid: messages_by_user[uid],
    )


# def _send_scheduler_test_email() -> None:
#     gmail_address = os.getenv("GMAIL_ADDRESS")
#     gmail_app_password = os.getenv("GMAIL_APP_PASSWORD")
#     if not gmail_address or not gmail_app_password:
#         print("scheduler test email skipped: GMAIL_ADDRESS/GMAIL_APP_PASSWORD not configured")
#         return

#     sent_at = _israel_now().strftime("%d/%m/%Y %H:%M:%S")
#     message = MIMEText(f"מייל בדיקה - ה-scheduler רץ בשעה {sent_at} (שעון ישראל)", "plain", "utf-8")
#     message["Subject"] = "מייל בדיקה - Scheduler"
#     message["From"] = gmail_address
#     message["To"] = SCHEDULER_TEST_EMAIL_RECIPIENT

#     try:
#         with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
#             server.login(gmail_address, gmail_app_password)
#             server.send_message(message)
#     except Exception as e:
#         print("scheduler test email error:", e)


async def enqueue_eligible_notifications() -> None:
    now_il = _israel_now()
    async with httpx.AsyncClient(timeout=20.0) as client:
        automations = await _fetch_automations(client)
        await _check_workout_reminder(client, now_il, automations.get("workout_reminder", {}))
        await _check_profile_incomplete(client, now_il, automations.get("profile_incomplete", {}))
        await _check_nutrition_reminder(client, now_il, automations.get("nutrition_reminder", {}))
        await _check_weekly_summary(client, now_il, automations.get("weekly_summary", {}))


async def _fetch_pending_queue(client: httpx.AsyncClient) -> list[dict]:
    return await _rest_get(
        client,
        "push_queue",
        [
            ("or", f"(status.eq.pending,and(status.eq.failed_retryable,attempts.lt.{MAX_ATTEMPTS}))"),
            ("select", "id,expo_push_token,title,body,data,attempts,notification_type,dedup_key"),
            ("order", "created_at.asc"),
            ("limit", "1000"),
        ],
    )


def _chunk(items: list, size: int):
    for i in range(0, len(items), size):
        yield items[i : i + size]


async def _send_expo_chunk(client: httpx.AsyncClient, rows: list[dict]) -> list[dict]:
    messages = [
        {"to": r["expo_push_token"], "title": r["title"], "body": r["body"], "data": r.get("data") or {}}
        for r in rows
    ]
    response = await client.post(
        EXPO_PUSH_URL,
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        json=messages,
    )
    response.raise_for_status()
    return response.json().get("data", [])


async def _sync_scheduled_broadcasts(client: httpx.AsyncClient, touched_keys: set[tuple[str, str]]) -> None:
    for notification_type, dedup_key in touched_keys:
        rows = await _rest_get(
            client, "push_queue", {"dedup_key": f"eq.{dedup_key}", "select": "status,title,body,data"}
        )
        sent_rows = [r for r in rows if r["status"] == "sent"]
        if not sent_rows:
            continue

        if notification_type == "weekly_summary":
            variant_counts: dict[str, int] = {}
            for r in sent_rows:
                variant_counts[r["title"]] = variant_counts.get(r["title"], 0) + 1
            title = "סיכום שבועי אוטומטי"
            body = " | ".join(f"{variant_title}: {count}" for variant_title, count in variant_counts.items())
        else:
            title = sent_rows[0]["title"]
            body = sent_rows[0]["body"]

        url, key = _supabase_config()
        response = await client.post(
            f"{url}/rest/v1/notification_broadcasts",
            params={"on_conflict": "dedup_key"},
            headers=_headers(key, prefer="resolution=merge-duplicates,return=minimal"),
            json={
                "title": title,
                "body": body,
                "navigation": sent_rows[0].get("data"),
                "sent_via": "scheduler",
                "notification_type": notification_type,
                "dedup_key": dedup_key,
                "activity_segment": "any",
                "platform_segment": "any",
                "audience_size": len(sent_rows),
                "status": "sent",
                "target_type": "segment",
            },
        )
        response.raise_for_status()


async def process_push_queue() -> dict:
    async with httpx.AsyncClient(timeout=20.0) as client:
        rows = await _fetch_pending_queue(client)
        if not rows:
            return {"processed": 0, "sent": 0, "failed_permanent": 0, "failed_retryable": 0}

        sent_ids: list[str] = []
        touched_keys: set[tuple[str, str]] = set()
        device_not_registered_ids: list[str] = []
        dead_tokens: set[str] = set()
        retryable_rows: list[dict] = []

        for chunk in _chunk(rows, EXPO_CHUNK_SIZE):
            try:
                tickets = await _send_expo_chunk(client, chunk)
            except Exception as e:
                print("expo push send error:", e)
                retryable_rows.extend(chunk)
                continue

            for row, ticket in zip(chunk, tickets):
                if ticket.get("status") == "ok":
                    sent_ids.append(row["id"])
                    touched_keys.add((row["notification_type"], row["dedup_key"]))
                elif (ticket.get("details") or {}).get("error") == "DeviceNotRegistered":
                    device_not_registered_ids.append(row["id"])
                    dead_tokens.add(row["expo_push_token"])
                else:
                    retryable_rows.append({**row, "_error": ticket.get("message") or "unknown error"})

        if sent_ids:
            await _rest_patch(client, "push_queue", {"id": f"in.({','.join(sent_ids)})"}, {"status": "sent"})
            await _sync_scheduled_broadcasts(client, touched_keys)

        if device_not_registered_ids:
            await _rest_patch(
                client,
                "push_queue",
                {"id": f"in.({','.join(device_not_registered_ids)})"},
                {"status": "failed_permanent", "last_error": "DeviceNotRegistered"},
            )
        if dead_tokens:
            await _rest_delete(client, "user_push_tokens", {"expo_push_token": f"in.({','.join(dead_tokens)})"})

        failed_retryable_count = 0
        failed_permanent_count = len(device_not_registered_ids)
        for row in retryable_rows:
            new_attempts = row["attempts"] + 1
            is_permanent = new_attempts >= MAX_ATTEMPTS
            new_status = "failed_permanent" if is_permanent else "failed_retryable"
            failed_permanent_count += 1 if is_permanent else 0
            failed_retryable_count += 0 if is_permanent else 1
            await _rest_patch(
                client,
                "push_queue",
                {"id": f"eq.{row['id']}"},
                {"status": new_status, "attempts": new_attempts, "last_error": row.get("_error", "send failed")},
            )

        return {
            "processed": len(rows),
            "sent": len(sent_ids),
            "failed_permanent": failed_permanent_count,
            "failed_retryable": failed_retryable_count,
        }


async def run_scheduler_cycle() -> dict:
    await enqueue_eligible_notifications()
    return await process_push_queue()
