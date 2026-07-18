from __future__ import annotations

import hashlib
from io import BytesIO
from pathlib import Path
from uuid import uuid4

from fastapi import HTTPException, UploadFile
from PIL import Image, UnidentifiedImageError

from backend.app.config import Settings
from backend.app.models import Asset


ALLOWED_MIME = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp"}


async def store_upload(upload: UploadFile, settings: Settings) -> Asset:
    if upload.content_type not in ALLOWED_MIME:
        raise HTTPException(status_code=422, detail="仅支持 JPG、PNG、WebP 商品图")
    content = await upload.read(settings.max_upload_bytes + 1)
    if not content:
        raise HTTPException(status_code=422, detail="上传文件为空")
    if len(content) > settings.max_upload_bytes:
        raise HTTPException(status_code=422, detail="单张图片不能超过 15MB")
    try:
        with Image.open(BytesIO(content)) as image:
            image.verify()
        with Image.open(BytesIO(content)) as image:
            width, height = image.size
    except (UnidentifiedImageError, OSError) as exc:
        raise HTTPException(status_code=422, detail="图片文件损坏或格式不合法") from exc
    if width < 128 or height < 128:
        raise HTTPException(status_code=422, detail="图片尺寸至少为 128×128")

    asset_id = str(uuid4())
    suffix = ALLOWED_MIME[upload.content_type]
    destination = settings.uploads_dir / f"{asset_id}{suffix}"
    destination.write_bytes(content)
    return Asset(
        id=asset_id,
        original_name=Path(upload.filename or f"product{suffix}").name,
        mime_type=upload.content_type,
        file_path=str(destination),
        url=f"/files/uploads/{destination.name}",
        width=width,
        height=height,
        byte_size=len(content),
        sha256=hashlib.sha256(content).hexdigest(),
    )

