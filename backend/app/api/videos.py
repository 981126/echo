"""素材库接口：上传/列表/详情/更新/确认标签/封面上传。"""

from __future__ import annotations

import json
import shutil
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy.orm import Session

from ..config import get_settings
from ..core.topics import normalize_platforms, normalize_topics
from ..db import get_db
from ..models.platform import PlatformPost
from ..models.video import Transcript, Video
from ..schemas.video import PlatformLinkOut, TagConfirmIn, VideoDetailOut, VideoListOut, VideoOut, VideoUpdate
from ..services.creator_service import current_creator_id
from ..services.ingest import import_video_task
from ..services.media_naming import media_stem, rename_to
from ..tasks import start_task

router = APIRouter()

VIDEO_EXTS = {".mp4", ".mov", ".avi", ".mkv", ".flv", ".webm", ".m4v", ".ts"}
COVER_EXTS = {".jpg", ".jpeg", ".png"}


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
    title = media_stem("", Path(file.filename or "video").stem, "视频")
    video = Video(filename=new_name, title=title, creator_id=current_creator_id(db))
    db.add(video)
    db.commit()
    try:  # R-058：落盘文件名改为「标题-视频」（重名自动 -2）
        video.filename = rename_to(dest, title)
        db.commit()
    except Exception:  # noqa: BLE001  改名失败不影响入库
        db.rollback()
    db.refresh(video)
    return video  # R-033：上传不自动转写，由编辑页「语音转文字」手动触发


@router.post("/{video_id}/transcribe", response_model=dict)
def transcribe_video(video_id: int, db: Session = Depends(get_db)):
    """R-033：手动触发语音转文字（后台任务，完成后右上角提醒并可跳转）。"""
    settings = get_settings()
    video = db.get(Video, video_id)
    if video is None:
        raise HTTPException(status_code=404, detail="视频不存在")
    if not video.filename:
        raise HTTPException(status_code=400, detail="该素材没有本地视频文件，请先在编辑页上传视频")
    if not (settings.videos_dir / video.filename).is_file():
        raise HTTPException(status_code=400, detail="本地视频文件缺失，请重新上传")
    if video.transcript and video.transcript.transcript_text and video.transcript.asr_status == "done":
        raise HTTPException(status_code=400, detail="该素材已转写完成，无需重复转写")
    task_id = start_task("import_video", {"video_id": video.id}, import_video_task)
    return {"ok": True, "task_id": task_id}


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
    cid = current_creator_id(db)
    if cid:
        q = q.filter(Video.creator_id == cid)
    if platform:
        q = q.filter(Video.platforms.like(f'%"{platform}"%'))
    if status:
        q = q.filter(Video.status == status)
    if main_topic:
        q = q.filter(Video.main_topics.like(f'%"{main_topic}"%'))
    total = q.count()
    items = q.order_by(Video.created_at.desc()).offset(offset).limit(limit).all()
    return {"total": total, "items": items}


@router.get("/{video_id}", response_model=VideoDetailOut)
def get_video(video_id: int, db: Session = Depends(get_db)):
    video = db.get(Video, video_id)
    if video is None:
        raise HTTPException(status_code=404, detail="视频不存在")
    out = VideoDetailOut.model_validate(video)
    out.platform_links = _platform_links(db, video)
    return out


def _platform_links(db: Session, video: Video) -> list[PlatformLinkOut]:
    """素材绑定的平台作品链接（按跨平台 work 聚合，展示三平台链接）。"""
    from ..core.platform_links import build_platform_page_url

    posts: list[PlatformPost] = []
    seen_ids: set[int] = set()
    for bound in db.query(PlatformPost).filter(PlatformPost.local_video_id == video.id).all():
        if bound.id not in seen_ids:
            posts.append(bound)
            seen_ids.add(bound.id)
    if video.work_id:
        for bound in db.query(PlatformPost).filter(PlatformPost.work_id == video.work_id).all():
            if bound.id not in seen_ids:
                posts.append(bound)
                seen_ids.add(bound.id)
    if video.platform_post_id and ":" in video.platform_post_id:
        platform, external_id = video.platform_post_id.split(":", 1)
        found = (
            db.query(PlatformPost)
            .filter(PlatformPost.platform == platform, PlatformPost.platform_post_id == external_id)
            .first()
        )
        if found is not None and found.id not in seen_ids:
            posts.append(found)
    seen: list[str] = []
    links: list[PlatformLinkOut] = []
    for post in posts:
        if post.platform in seen:
            continue
        seen.append(post.platform)
        url = build_platform_page_url(post.platform, post.platform_post_id, post.raw or "")
        links.append(
            PlatformLinkOut(
                platform=post.platform,
                platform_post_id=post.platform_post_id,
                post_id=post.id,
                url=url,
                publish_time=post.publish_time,
            )
        )
    return links


@router.patch("/{video_id}", response_model=VideoOut)
def update_video(video_id: int, payload: VideoUpdate, db: Session = Depends(get_db)):
    video = db.get(Video, video_id)
    if video is None:
        raise HTTPException(status_code=404, detail="视频不存在")
    data = payload.model_dump(exclude_unset=True)

    if "title" in data:
        video.title = (data["title"] or "").strip()[:200]
    if "platforms" in data:
        platforms = normalize_platforms(data["platforms"])
        if data["platforms"] and not platforms:
            raise HTTPException(status_code=400, detail="platforms 仅支持 douyin/bilibili/xiaohongshu")
        video.platforms = json.dumps(platforms, ensure_ascii=False)
    if "main_topics" in data:
        topics = normalize_topics(data["main_topics"])
        video.main_topics = json.dumps(topics, ensure_ascii=False)
    if "tags" in data:
        video.tags = json.dumps([str(t) for t in data["tags"]], ensure_ascii=False)
    if "source_text" in data or "corrected_text" in data:
        if video.transcript is None:
            video.transcript = Transcript(video_id=video.id)
            db.add(video.transcript)
        if "source_text" in data:
            video.transcript.source_text = data["source_text"] or ""
        if "corrected_text" in data:
            video.transcript.corrected_text = data["corrected_text"] or ""
    for field in ("status", "planned_publish_at", "published_at", "is_ad"):
        if field in data:
            setattr(video, field, data[field])
    if "ad_price" in data:
        video.ad_price = int(data["ad_price"]) if data["ad_price"] is not None else None
    db.commit()
    if "title" in data and (video.title or "").strip():
        _rename_by_title(db, video)
    db.refresh(video)
    return video


@router.post("/{video_id}/video", response_model=VideoOut)
def attach_video(video_id: int, file: UploadFile = File(...), db: Session = Depends(get_db)):
    """给已有素材上传/替换本地视频文件（不自动转写）。落盘名：标题-视频。"""
    video = db.get(Video, video_id)
    if video is None:
        raise HTTPException(status_code=404, detail="素材不存在")
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in VIDEO_EXTS:
        raise HTTPException(status_code=400, detail=f"不支持的视频格式: {suffix}")
    settings = get_settings()
    settings.videos_dir.mkdir(parents=True, exist_ok=True)
    if video.filename and not video.filename.startswith("__cloud__"):
        try:
            (settings.videos_dir / video.filename).unlink(missing_ok=True)
        except OSError:
            pass
    stem = media_stem(_first_platform(video), video.title or Path(file.filename or "video").stem, "视频")
    raw_name = f"{uuid.uuid4().hex[:8]}_{Path(file.filename or 'video').name}"
    dest = settings.videos_dir / raw_name
    with dest.open("wb") as out:
        shutil.copyfileobj(file.file, out)
    video.filename = rename_to(dest, stem)
    db.commit()
    db.refresh(video)
    return video


@router.delete("/{video_id}/video", response_model=VideoOut)
def remove_video_file(video_id: int, db: Session = Depends(get_db)):
    """删除素材的本地视频文件（素材记录保留，回到“未上传视频”）。"""
    video = db.get(Video, video_id)
    if video is None:
        raise HTTPException(status_code=404, detail="素材不存在")
    settings = get_settings()
    if video.filename and not video.filename.startswith("__cloud__"):
        try:
            (settings.videos_dir / video.filename).unlink(missing_ok=True)
        except OSError:
            pass
    video.filename = f"__cloud__{video.id}_{uuid.uuid4().hex[:6]}"  # 占位名唯一且前端识别为“未上传”
    db.commit()
    db.refresh(video)
    return video



@router.post("/{video_id}/cover", response_model=VideoOut)
def upload_cover(video_id: int, file: UploadFile = File(...), db: Session = Depends(get_db)):
    video = db.get(Video, video_id)
    if video is None:
        raise HTTPException(status_code=404, detail="视频不存在")
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in COVER_EXTS:
        raise HTTPException(status_code=400, detail="封面仅支持 jpg/png")
    settings = get_settings()
    settings.covers_dir.mkdir(parents=True, exist_ok=True)
    new_name = f"{uuid.uuid4().hex[:10]}{suffix}"
    dest = settings.covers_dir / new_name
    with dest.open("wb") as out:
        shutil.copyfileobj(file.file, out)
    if video.cover_path:
        try:
            (settings.covers_dir / video.cover_path).unlink(missing_ok=True)
        except OSError:
            pass
    stem = media_stem(_first_platform(video), video.title or Path(file.filename or "cover").stem, "封面")
    try:  # R-058：封面落盘名带平台前缀+主标题
        video.cover_path = rename_to(dest, stem)
    except Exception:  # noqa: BLE001
        video.cover_path = new_name
    db.commit()
    db.refresh(video)
    return video


@router.delete("/{video_id}/cover", response_model=VideoOut)
def delete_cover(video_id: int, db: Session = Depends(get_db)):
    video = db.get(Video, video_id)
    if video is None:
        raise HTTPException(status_code=404, detail="视频不存在")
    if video.cover_path:
        try:
            (get_settings().covers_dir / video.cover_path).unlink(missing_ok=True)
        except OSError:
            pass
        video.cover_path = ""
        db.commit()
        db.refresh(video)
    return video


@router.delete("/{video_id}", response_model=dict)
def delete_video(video_id: int, db: Session = Depends(get_db)):
    """删除本地素材（逻辑清理：删除记录/转写/指标，解除云端作品绑定，本地视频文件一并删除）。"""
    from ..config import get_settings
    from ..models.draft import Draft
    from ..models.metrics import MetricsSnapshot
    from ..models.platform import PlatformPost

    video = db.get(Video, video_id)
    if video is None:
        raise HTTPException(status_code=404, detail="素材不存在")
    if video.filename:
        try:
            (get_settings().videos_dir / video.filename).unlink(missing_ok=True)
        except OSError:
            pass
    if video.cover_path:
        try:
            (get_settings().covers_dir / video.cover_path).unlink(missing_ok=True)
        except OSError:
            pass
    db.query(PlatformPost).filter(PlatformPost.local_video_id == video_id).update({"local_video_id": None})
    db.query(Draft).filter(Draft.video_id == video_id).update({"video_id": None})
    db.query(MetricsSnapshot).filter(MetricsSnapshot.video_id == video_id).delete()
    if video.transcript:
        db.delete(video.transcript)
    db.delete(video)
    db.commit()
    return {"ok": True}


@router.post("/{video_id}/confirm-tags", response_model=VideoOut)
def confirm_tags(video_id: int, payload: TagConfirmIn, db: Session = Depends(get_db)):
    video = db.get(Video, video_id)
    if video is None:
        raise HTTPException(status_code=404, detail="视频不存在")
    video.tags_confirmed = payload.tags_confirmed
    db.commit()
    db.refresh(video)
    return video


def _first_platform(video: Video) -> str:
    """素材绑定的第一个平台（用于文件名平台前缀）。"""
    try:
        arr = json.loads(video.platforms or "[]") if isinstance(video.platforms, str) else (video.platforms or [])
        return arr[0] if arr else ""
    except (TypeError, ValueError):
        return ""


def _rename_by_title(db: Session, video: Video) -> None:
    """R-058：标题确定后，把本地视频文件与封面统一改名为「标题-视频 / 标题-封面」。"""
    settings = get_settings()
    plat = _first_platform(video)
    stem_v = media_stem(plat, video.title, "视频")
    stem_c = media_stem(plat, video.title, "封面")
    if video.filename:
        try:
            old = settings.videos_dir / video.filename
            if old.name != f"{stem_v}{old.suffix}":  # 已是目标名则跳过，避免 -2 重复
                video.filename = rename_to(old, stem_v)
        except Exception:  # noqa: BLE001  改名失败保留旧名
            db.rollback()
    if video.cover_path:
        try:
            old = settings.covers_dir / video.cover_path
            if old.name != f"{stem_c}{old.suffix}":
                video.cover_path = rename_to(old, stem_c)
        except Exception:  # noqa: BLE001
            db.rollback()
    db.commit()
