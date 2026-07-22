import os

import httpx


async def get_privacy_policy() -> dict:
    supabase_url = os.getenv("SUPABASE_URL")
    service_role_key = os.getenv("SUPABASE_SERVICE_ROLE_KEY")

    if not supabase_url or not service_role_key:
        raise RuntimeError("SUPABASE_URL/SUPABASE_SERVICE_ROLE_KEY not configured")

    headers = {
        "apikey": service_role_key,
        "Authorization": f"Bearer {service_role_key}",
    }

    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.get(
            f"{supabase_url}/rest/v1/privacy_policies",
            params={
                "select": "version,content_he,content_en,created_at",
                "order": "created_at.desc",
                "limit": "1",
            },
            headers=headers,
        )
        response.raise_for_status()
        rows = response.json()

    if not rows:
        raise RuntimeError("No privacy policy found")

    return rows[0]
