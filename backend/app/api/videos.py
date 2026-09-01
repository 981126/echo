"""素材库接口：上传/列表/详情/更新/确认标签。"""
import json
import shutil
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy.orm import Session

from ..config import get_settings
from ..core.topics import is_valid_platform, normalize_main_topic
from ..db import get_db
from ..models.video import Transcript, Video
from ..schemas.video import TagConfirmIn, VideoDetailOut, VideoListOut, VideoOut, VideoUpdate
from ..services.ingest import import_video_task
from ..tasks import start_task

router = APIRouter()

VIDEO_EXTS = {".mp4", ".mov", ".avi", ".mkv", ".flv", ".webm", ".m4v", ".ts"}


@router.post("/upload", response_model=VideoOut)
def upload_video(file: UploadFile = File(...), db: Session = Depends(get_db)):
    settings = get_settings()
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in VIDEO_EXTS:
        raise HTTPException(status_code=400, detail=f"不支持的视频格式: {suffix}")
    settings.videos_dir.mkdir(parents=True, exist_ok=True)
    new_name = f"{uuid.uuid4().hex[:8]}_{Path(file.filename or 'video').name}"
    dest = settings.videos_dir / new_name
    with dest.open("wb") as out:
        shutil.copyfileobj(file.file, out)
    video = Video(filename=new_name)
    db.add(video)
    db.commit()
    db.refresh(video)
    start_task("import_video", {"video_id": video.id}, import_video_task)
    return video


@router.get("", response_model=VideoListOut)
def list_videos(
    platform: str = "",
    status: str = "",
    main_topic: str = "",
    limit: int = 50,
    offset: int = 0,
    db: Session = Depends(get_db),
):
    q = db.query(Video)
    if platform:
        q = q.filter(Video.platform == platform)
    if status:
        q = q.filter(Video.status == status)
    if main_topic:
        q = q.filter(Video.main_topic == main_topic)
    total = q.count()
    items = q.order_by(Video.created_at.desc()).offset(offset).limit(limit).all()
    return {"total": total, "items": items}


@router.get("/{video_id}", response_model=VideoDetailOut)
def get_video(video_id: int, db: Session = Depends(get_db)):
    video = db.get(Video, video_id)
    if video is None:
        raise HTTPException(status_code=404, detail="视频不存在")
    return video


@router.patch("/{video_id}", response_model=VideoOut)
def update_video(video_id: int, payload: VideoUpdate, db: Session = Depends(get_db)):
    video = db.get(Video, video_id)
    if video is None:
        raise HTTPException(status_code=404, detail="视频不存在")
    data = payload.model_dump(exclude_unset=True)

    if "platform" in data and data["platform"]:
        if not is_valid_platform(data["platform"]):
            raise HTTPException(
                status_code=400, detail="platform 必须是 douyin/bilibili/xiaohongshu"
            )
        video.platform = data["platform"]
    if "main_topic" in data:
        video.main_topic = normalize_main_topic(data["main_topic"])
    if "tags" in data:
        video.tags = json.dumps([str(t) for t in data["tags"]], ensure_ascii=False)
    if "source_text" in data:
        if video.transcript is None:
            video.transcript = Transcript(video_id=video.id)
            db.add(video.transcript)
        video.transcript.source_text = data["source_text"] or ""
    for field in ("status", "planned_publish_at", "published_at", "is_ad"):
        if field in data:
            setattr(video, field, data[field])
    db.commit()
    db.refresh(video)
    return video


@router.post("/{video_id}/confirm-tags", response_model=VideoOut)
def confirm_tags(video_id: int, payload: TagConfirmIn, db: Session = Depends(get_db)):
    video = db.get(Video, video_id)
    if video is None:
        raise HTTPException(status_code=404, detail="视频不存在")
    video.tags_confirmed = payload.tags_confirmed
    db.commit()
    db.refresh(video)
    return video
