"""作品合并接口（M13+）：素材库云端作品合并/拆分。"""

from __future__ import annotations

import json
import shutil
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..db import get_db
from ..services.creator_service import current_creator_id
from ..services.text_tags import extract_hashtags, strip_hashtags
from ..services.works_service import list_works, merge_manual, split_work

router = APIRouter()


class MergeIn(BaseModel):
    platform_post_ids: list[int] = []


@router.post("/to-local", response_model=dict)
def cloud_to_local(
    db: Session = Depends(get_db),
    file: UploadFile | None = File(default=None),
    text: str = Form(default=""),
    work_id: int | None = Form(default=None),
    post_id: int | None = Form(default=None),
    is_ad: str = Form(default=""),
    ad_price: str = Form(default=""),
):
    ad_flag = is_ad in ("1", "true", "True", "on")
    ad_val = None
    if ad_price not in ("", "null", "None"):
        try:
            ad_val = int(float(ad_price))
        except (TypeError, ValueError):
            ad_val = None
    """把云端作品转成本地素材：上传视频（可选，不自动转写）+ 文案（可选）后变成本地素材。"""
    from ..config import get_settings
    from ..core.pipeline import today_key
    from ..models.metrics import MetricsSnapshot
    from ..models.video import Transcript, Video
    from ..services.creator_service import current_creator_id
    from ..models.platform import PlatformPost

    cid = current_creator_id(db)
    if cid is None:
        raise HTTPException(status_code=400, detail="请先创建并切换到一个主博主")

    posts: list[PlatformPost] = []
    if work_id:
        posts = db.query(PlatformPost).filter(PlatformPost.work_id == work_id).all()
    elif post_id:
        p = db.get(PlatformPost, post_id)
        posts = [p] if p else []
    if not posts:
        raise HTTPException(status_code=404, detail="云端作品不存在")
    first = posts[0]

    settings = get_settings()
    filename = ""
    if file is not None and (file.filename or ""):
        filename = f"{uuid.uuid4().hex[:8]}_{Path(file.filename or 'video').name}"
        settings.videos_dir.mkdir(parents=True, exist_ok=True)
        dest = settings.videos_dir / filename
        with dest.open("wb") as out:
            shutil.copyfileobj(file.file, out)

    platforms = []
    tag_cloud: list[str] = []
    seen_tags: set[str] = set()

    def _add_tags(items) -> None:
        for t in items:
            t = str(t).strip()
            if t and t.lower() not in seen_tags:
                seen_tags.add(t.lower())
                tag_cloud.append(t)

    for post in posts:
        if post.platform not in platforms:
            platforms.append(post.platform)
        try:
            ptags = json.loads(post.tags or "[]")
            if isinstance(ptags, list):
                _add_tags(ptags)
        except json.JSONDecodeError:
            pass
        # R-226：帖子无话题标签时，从标题/简介补提 #话题
        _add_tags(extract_hashtags(post.title or "", post.desc or ""))
    known5 = ["求职", "面试", "赚钱", "知识", "其他"]
    main_topics = [t for t in tag_cloud if t in known5]
    video_tags = [t for t in tag_cloud if t not in known5]
    if not filename and first.id:
        filename = f"__cloud__{first.id}"
    video = Video(
        filename=filename,
        title=strip_hashtags(first.title or ""),
        creator_id=cid,
        platforms=json.dumps(platforms, ensure_ascii=False),
        main_topics=json.dumps(main_topics, ensure_ascii=False),
        tags=json.dumps(video_tags, ensure_ascii=False),
        platform_post_id=f"{first.platform}:{first.platform_post_id}",
        work_id=posts[0].work_id,
        cover_path=first.cover_path or "",
        status="published",  # 云端有真实发布链接/时间 => 已发布
        published_at=first.publish_time,
        is_ad=ad_flag if is_ad else False,
        ad_price=ad_val if is_ad else None,
    )
    db.add(video)
    db.commit()
    db.refresh(video)

    if (text or "").strip():
        if video.transcript is None:
            video.transcript = Transcript(video_id=video.id)
            db.add(video.transcript)
        video.transcript.source_text = text.strip()
        video.transcript.corrected_text = text.strip()
    db.commit()

    # 各平台作品绑定到该本地素材
    for post in posts:
        post.local_video_id = video.id
    db.commit()

    # 复制云端最新指标到本地（复盘可用）
    from ..models.platform import PlatformPostStat

    stat = (
        db.query(PlatformPostStat)
        .filter(PlatformPostStat.post_id == first.id)
        .order_by(PlatformPostStat.stat_date.desc())
        .first()
    )
    if stat:
        db.add(
            MetricsSnapshot(
                video_id=video.id,
                snapshot_date=today_key(),
                plays=stat.plays,
                likes=stat.likes,
                favorites=stat.favorites,
                comments=stat.comments,
                source="tikhub",
            )
        )
        db.commit()
    # R-033：转本地不自动转写，编辑页「语音转文字」手动触发
    return {"ok": True, "video_id": video.id, "filename": filename}


@router.get("", response_model=dict)
def get_works(creator_id: int = 0, db: Session = Depends(get_db)):
    cid = creator_id or current_creator_id(db)
    items = list_works(db, cid)
    return {"total": len(items), "items": items}


@router.get("/by-post/{post_id}", response_model=dict)
def get_work_by_post(post_id: int, db: Session = Depends(get_db)):
    """按平台作品 id 返回其所属云端条目（可跨博主，素材库深链/来源素材跳转用，R-122）。

    与素材库列表同口径：按该作品所属博主取 list_works，命中即返回包含它的合并作品或单条；
    找不到（已删除/账号禁用）返回 404，前端提示而不是静默打不开。
    """
    from ..models.platform import CreatorAccount, PlatformPost

    p = db.get(PlatformPost, post_id)
    if p is None or not p.account_id:
        raise HTTPException(status_code=404, detail="云端素材不存在或已删除")
    acc = db.get(CreatorAccount, p.account_id)
    if acc is None:
        raise HTTPException(status_code=404, detail="云端素材不存在或已删除")
    for item in list_works(db, acc.creator_id):
        if any(x.get("id") == p.id for x in (item.get("posts") or [])):
            return item
    raise HTTPException(status_code=404, detail="云端素材不存在或已删除")


class MetaIn(BaseModel):
    work_id: int | None = None
    post_id: int | None = None
    is_ad: bool = False
    ad_price: int | None = None


@router.post("/meta", response_model=dict)
def set_meta(payload: MetaIn, db: Session = Depends(get_db)):
    """设置云端作品广告/价格（作用于整个合并作品，并同步已转的本地素材）。"""
    from ..models.platform import PlatformPost
    from ..models.video import Video

    posts: list = []
    if payload.work_id:
        posts = db.query(PlatformPost).filter(PlatformPost.work_id == payload.work_id).all()
    elif payload.post_id:
        p = db.get(PlatformPost, payload.post_id)
        posts = [p] if p else []
    if not posts:
        raise HTTPException(status_code=404, detail="云端作品不存在")
    vid_ids = set()
    for post in posts:
        post.is_ad = payload.is_ad
        post.ad_price = payload.ad_price
        if post.local_video_id:
            vid_ids.add(post.local_video_id)
    if vid_ids:
        for v in db.query(Video).filter(Video.id.in_(list(vid_ids))).all():
            v.is_ad = payload.is_ad
            v.ad_price = payload.ad_price
    db.commit()
    return {"ok": True, "updated": len(posts)}


@router.delete("/{item_id}", response_model=dict)
def delete_item(item_id: int, kind: str = "post", db: Session = Depends(get_db)):
    """删除云端素材：kind=work 删整个合并作品及其平台记录；kind=post 只删单条。"""
    from ..models.hot_topic import TopicIdea
    from ..models.platform import PlatformPost, PlatformPostStat
    from ..models.work import Work

    posts = []
    work = None
    if kind == "work":
        work = db.get(Work, item_id)
        if work is None:
            raise HTTPException(status_code=404, detail="作品不存在")
        posts = db.query(PlatformPost).filter(PlatformPost.work_id == item_id).all()
    else:
        p = db.get(PlatformPost, item_id)
        posts = [p] if p else []
    if not posts:
        raise HTTPException(status_code=404, detail="云端素材不存在")
    for post in posts:
        db.query(PlatformPostStat).filter(PlatformPostStat.post_id == post.id).delete()
        db.query(TopicIdea).filter(TopicIdea.post_id == post.id).delete()
        db.delete(post)
    if work is not None:
        db.delete(work)
    db.commit()
    return {"ok": True, "removed": len(posts)}



@router.post("/cleanup-tags", response_model=dict)
def cleanup_tags(db: Session = Depends(get_db)):
    """清理标签里的平台词与 [\u8bdd\u9898] 话题后缀（维护用）。"""
    import json as _json
    from ..models.platform import PlatformPost

    suffix = "[" + "\u8bdd\u9898" + "]"
    skip = {"douyin", "\u6296\u97f3", "xiaohongshu", "\u5c0f\u7ea2\u4e66", "bilibili", "B\u7ad9", "b\u7ad9", "\u89c6\u9891", "vlog", "\u8bdd\u9898", "tag"}
    norms = {x.lower() for x in skip}
    changed = 0
    for post in db.query(PlatformPost).all():
        try:
            tags = _json.loads(post.tags or "[]") if isinstance(post.tags, str) else (post.tags or [])
        except Exception:
            continue
        if not isinstance(tags, list):
            continue
        out = []
        for t in tags:
            t = str(t).replace(suffix, "").replace("[", "").replace("]", "").strip()
            if (not t) or (t.lower() in norms) or (t in out):
                continue
            out.append(t)
        new = _json.dumps(out, ensure_ascii=False)
        if not (new == post.tags):
            post.tags = new
            changed += 1
    db.commit()
    return {"ok": True, "cleaned": changed}


@router.post("/auto-merge", response_model=dict)
def auto_merge_all(creator_id: int = 0, db: Session = Depends(get_db)):
    """自动合并：把所有博主（或指定博主）下“同创作者+规范化标题相同”的跨平台作品合并为一。"""
    from ..models.platform import Creator
    from ..services.works_service import auto_merge_creator

    creators = []
    if creator_id:
        c = db.get(Creator, creator_id)
        if c:
            creators = [c]
    else:
        creators = db.query(Creator).all()
    created = 0
    for c in creators:
        try:
            created += auto_merge_creator(db, c.id)
        except Exception:  # noqa: BLE001 单博主失败不影响其它
            db.rollback()
    return {"ok": True, "merged_groups": created}


@router.post("/merge", response_model=dict)
def merge_items(payload: MergeIn, db: Session = Depends(get_db)):
    try:
        return merge_manual(db, payload.platform_post_ids)
    except HTTPException:
        raise


@router.post("/{work_id}/split", response_model=dict)
def split_items(work_id: int, payload: MergeIn, db: Session = Depends(get_db)):
    return split_work(db, work_id, keep_ids=payload.platform_post_ids)
