import hashlib
import os
import time
import uuid

import httpx

CUSTOM_EXERCISE_FOLDER = "custom-exercises"
EXERCISES_V2_IMAGE_FOLDER = "exercises-v2/images"
EXERCISES_V2_VIDEO_FOLDER = "exercises-v2/video"


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


async def _upload_exercise_asset(data: bytes, content_type: str, resource_type: str, folder: str, public_id: str) -> str:
    cloud_name = os.getenv("CLOUDINARY_CLOUD_NAME")
    api_key = os.getenv("CLOUDINARY_API_KEY")
    api_secret = os.getenv("CLOUDINARY_API_SECRET")

    if not cloud_name or not api_key or not api_secret:
        raise RuntimeError("CLOUDINARY_CLOUD_NAME/CLOUDINARY_API_KEY/CLOUDINARY_API_SECRET not configured")

    upload_url = f"https://api.cloudinary.com/v1_1/{cloud_name}/{resource_type}/upload"
    timestamp = int(time.time())
    string_to_sign = f"folder={folder}&overwrite=true&public_id={public_id}&timestamp={timestamp}{api_secret}"
    signature = hashlib.sha1(string_to_sign.encode("utf-8")).hexdigest()

    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(
            upload_url,
            data={
                "api_key": api_key,
                "timestamp": timestamp,
                "signature": signature,
                "folder": folder,
                "public_id": public_id,
                "overwrite": "true",
            },
            files={"file": ("asset", data, content_type)},
        )
        response.raise_for_status()
        return response.json()["secure_url"]


async def upload_exercise_images(files: list[tuple[bytes, str]], exercise_id: str) -> list[str]:
    cloud_name = os.getenv("CLOUDINARY_CLOUD_NAME")
    api_key = os.getenv("CLOUDINARY_API_KEY")
    api_secret = os.getenv("CLOUDINARY_API_SECRET")

    if not cloud_name or not api_key or not api_secret:
        raise RuntimeError("CLOUDINARY_CLOUD_NAME/CLOUDINARY_API_KEY/CLOUDINARY_API_SECRET not configured")

    folder = f"{EXERCISES_V2_IMAGE_FOLDER}/{exercise_id}"
    upload_url = f"https://api.cloudinary.com/v1_1/{cloud_name}/image/upload"
    urls: list[str] = []

    async with httpx.AsyncClient(timeout=30.0) as client:
        for data, content_type in files:
            timestamp = int(time.time())
            public_id = uuid.uuid4().hex
            string_to_sign = f"folder={folder}&public_id={public_id}&timestamp={timestamp}{api_secret}"
            signature = hashlib.sha1(string_to_sign.encode("utf-8")).hexdigest()

            response = await client.post(
                upload_url,
                data={
                    "api_key": api_key,
                    "timestamp": timestamp,
                    "signature": signature,
                    "folder": folder,
                    "public_id": public_id,
                },
                files={"file": ("image", data, content_type)},
            )
            response.raise_for_status()
            urls.append(response.json()["secure_url"])

    return urls


async def upload_exercise_video(data: bytes, content_type: str, exercise_id: str) -> str:
    return await _upload_exercise_asset(data, content_type, "video", EXERCISES_V2_VIDEO_FOLDER, exercise_id)
