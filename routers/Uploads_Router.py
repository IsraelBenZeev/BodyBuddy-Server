from fastapi import APIRouter, HTTPException, Request, Depends, File, UploadFile
from controllers.uploads_controller import upload_custom_exercise_images
from dependencies import verify_supabase_token
from limiter import limiter

routerUploads = APIRouter()

MAX_FILES = 3
MAX_FILE_SIZE = 10 * 1024 * 1024  # 10MB
ALLOWED_CONTENT_TYPES = {"image/jpeg", "image/png", "image/webp", "image/heic", "image/heif"}


@routerUploads.post("/custom-exercise-images")
@limiter.limit("10/minute")
async def upload_custom_exercise_images_route(
    request: Request,
    images: list[UploadFile] = File(...),
    user_id: str = Depends(verify_supabase_token),
):
    if not images or len(images) > MAX_FILES:
        raise HTTPException(status_code=400, detail="Must upload between 1 and 3 images")

    files: list[tuple[bytes, str]] = []
    for image in images:
        if image.content_type not in ALLOWED_CONTENT_TYPES:
            raise HTTPException(status_code=400, detail="Invalid file type")
        data = await image.read()
        if len(data) > MAX_FILE_SIZE:
            raise HTTPException(status_code=400, detail="Image too large")
        files.append((data, image.content_type))

    try:
        urls = await upload_custom_exercise_images(files)
        return {"urls": urls}
    except RuntimeError as e:
        print("custom exercise image upload config error:", e)
        raise HTTPException(status_code=500, detail="Failed to upload images")
    except Exception as e:
        print("custom exercise image upload error:", e)
        raise HTTPException(status_code=500, detail="Failed to upload images")
