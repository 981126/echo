"""通用上传：编辑器插入的图片等附件（存 data/uploads/，/uploads 静态可访问）。"""

from __future__ import annotations

import shutil
import uuid
from pathlib import Path

from fastapi import APIRouter, File, HTTPException, UploadFile

from ..config import get_settings

router = APIRouter()

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".webp"}


@router.post("/image", response_model=dict)
def upload_image(file: UploadFile = File(...)):
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in IMAGE_EXTS:
        raise HTTPException(status_code=400, detail="仅支持 png/jpg/gif/webp 图片")
    settings = get_settings()
    settings.uploads_dir.mkdir(parents=True, exist_ok=True)
    name = f"{uuid.uuid4().hex[:12]}{suffix}"
    dest = settings.uploads_dir / name
    with dest.open("wb") as out:
        shutil.copyfileobj(file.file, out)
    return {"url": f"/uploads/{name}"}
