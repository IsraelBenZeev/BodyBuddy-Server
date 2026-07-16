import hashlib
import os
import time

import httpx

CUSTOM_EXERCISE_FOLDER = "custom-exercises"


async def upload_custom_exercise_images(files: list[tuple[bytes, str]]) -> list[str]:
    cloud_name = os.getenv("CLOUDINARY_CLOUD_NAME")
    api_key = os.getenv("CLOUDINARY_API_KEY")
    api_secret = os.getenv("CLOUDINARY_API_SECRET")

    if not cloud_name or not api_key or not api_secret:
        raise RuntimeError("CLOUDINARY_CLOUD_NAME/CLOUDINARY_API_KEY/CLOUDINARY_API_SECRET not configured")

    upload_url = f"https://api.cloudinary.com/v1_1/{cloud_name}/image/upload"
    urls: list[str] = []

    async with httpx.AsyncClient(timeout=30.0) as client:
        for data, content_type in files:
            timestamp = int(time.time())
            string_to_sign = f"folder={CUSTOM_EXERCISE_FOLDER}&timestamp={timestamp}{api_secret}"
            signature = hashlib.sha1(string_to_sign.encode("utf-8")).hexdigest()

            response = await client.post(
                upload_url,
                data={
                    "api_key": api_key,
                    "timestamp": timestamp,
                    "signature": signature,
                    "folder": CUSTOM_EXERCISE_FOLDER,
                },
                files={"file": ("image", data, content_type)},
            )
            response.raise_for_status()
            urls.append(response.json()["secure_url"])

    return urls
