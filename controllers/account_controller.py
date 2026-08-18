import os

import httpx


def _supabase_headers() -> dict:
    supabase_url = os.getenv("SUPABASE_URL")
    service_role_key = os.getenv("SUPABASE_SERVICE_ROLE_KEY")

    if not supabase_url or not service_role_key:
        raise RuntimeError("SUPABASE_URL/SUPABASE_SERVICE_ROLE_KEY not configured")

    return {
        "apikey": service_role_key,
        "Authorization": f"Bearer {service_role_key}",
    }


async def delete_own_account(user_id: str) -> None:
    supabase_url = os.getenv("SUPABASE_URL")

    async with httpx.AsyncClient(timeout=10.0) as client:
        # recipient_user_ids on notification_broadcasts is an array column with no FK
        # enforcement, so a deleted user's id would otherwise linger forever in old
        # broadcast history rows
        cleanup_broadcasts_response = await client.post(
            f"{supabase_url}/rest/v1/rpc/cleanup_user_broadcast_refs",
            headers={**_supabase_headers(), "Content-Type": "application/json"},
            json={"target_user_id": user_id},
        )
        cleanup_broadcasts_response.raise_for_status()

        # body_stats has no cascade delete rule on user_id, unlike every other user-owned table
        cleanup_body_stats_response = await client.delete(
            f"{supabase_url}/rest/v1/body_stats",
            params={"user_id": f"eq.{user_id}"},
            headers=_supabase_headers(),
        )
        cleanup_body_stats_response.raise_for_status()

        response = await client.delete(
            f"{supabase_url}/auth/v1/admin/users/{user_id}",
            headers=_supabase_headers(),
        )
        response.raise_for_status()
