import base64
import json
import os
import time

import httpx
import jwt
from jwt.algorithms import ECAlgorithm
from fastapi import Depends, HTTPException, Header


def _load_public_key():
    jwks_str = os.getenv("SUPABASE_JWKS", "")
    if not jwks_str:
        return None
    try:
        jwks = json.loads(jwks_str)
        key_data = jwks.get("keys", [jwks])[0]
        return ECAlgorithm.from_jwk(json.dumps(key_data))
    except Exception as e:
        print("JWKS load error:", e)
        return None


_PUBLIC_KEY = _load_public_key()


async def verify_supabase_token(authorization: str = Header(default=None)) -> str:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Unauthorized")

    token = authorization.removeprefix("Bearer ").strip()

    if _PUBLIC_KEY is not None:
        try:
            payload = jwt.decode(
                token,
                _PUBLIC_KEY,
                algorithms=["ES256"],
                options={"verify_aud": False},
            )
            user_id = payload.get("sub")
            if not user_id:
                raise HTTPException(status_code=401, detail="Unauthorized")
            return user_id
        except jwt.ExpiredSignatureError:
            raise HTTPException(status_code=401, detail="Unauthorized")
        except jwt.InvalidTokenError as e:
            print("JWT invalid:", type(e).__name__)
            raise HTTPException(status_code=401, detail="Unauthorized")

    try:
        parts = token.split('.')
        if len(parts) != 3:
            raise ValueError("not a JWT")
        payload_b64 = parts[1] + '=' * (4 - len(parts[1]) % 4)
        payload = json.loads(base64.urlsafe_b64decode(payload_b64))
        user_id = payload.get("sub")
        if not user_id:
            raise HTTPException(status_code=401, detail="Unauthorized")
        if time.time() > payload.get("exp", 0):
            raise HTTPException(status_code=401, detail="Unauthorized")
        return user_id
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=401, detail="Unauthorized")


async def _fetch_is_admin(user_id: str) -> bool:
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
            f"{supabase_url}/rest/v1/profiles",
            params={"select": "is_admin", "user_id": f"eq.{user_id}"},
            headers=headers,
        )
        response.raise_for_status()
        rows = response.json()

    return bool(rows and rows[0].get("is_admin"))


async def require_admin(user_id: str = Depends(verify_supabase_token)) -> str:
    if not await _fetch_is_admin(user_id):
        raise HTTPException(status_code=403, detail="Forbidden")

    return user_id
