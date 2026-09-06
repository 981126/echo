"""R-077：素材卡「同步数据」后的媒体补齐——缺视频则下载（低清），缺转写则自动 ASR。

- API 端先做轻量预判（只查库/文件，不联网）：
  - 已有本地视频文件 + 已完成转写 → skip（不下载、不转写）
  - 缺视频或缺转写 → 投递后台任务 platform_media（下载/转写完成后右上角通知）
- 后台任务按平台优先级（抖音→小红书→B站）逐条尝试解析视频源并下载；
  B站 TikHub 取不到流时回落 yt-dlp 直连下载低清视频+音频（R-078）；
  下载成功才建本地素材行；尚无转写稿时复用现有转写流水线 import_video_task。
- mock/无真实视频源（如图文笔记）→ 不下载不编造，明确告知原因。
"""

from __future__ import annotations

import json
from pathlib import Path

from sqlalchemy.orm import Session

from ..config import get_settings
from ..models.platform import CreatorAccount, PlatformPost
from ..models.video import Video
from .creator_service import current_creator_id
from .media_downloader import (
    MediaDownloadError,
    download_bilibili_via_ytdlp,
    download_platform_video,
)
from .media_naming import media_stem, unique_path
from .platform.budget import BudgetExceeded, _charge
from .platform_sync import _bound_platform_posts
from ..tasks import start_task
from ..models.task import BackgroundTask
from .events import publish

# 下载源平台优先级：抖音单文件最简单，其次小红书，B站最重（需合并）放最后
_PLATFORM_PRIORITY = ["douyin", "xiaohongshu", "bilibili"]
_PLACEHOLDER_PREFIX = "__cloud__"  # 与 /to-local、/to-material 的占位命名保持一致


def _videos_dir() -> Path:
    return get_settings().videos_dir


def has_real_file(video: Video | None) -> bool:
    """是否有真实落盘的视频文件（占位 __cloud__* 不算）。"""
    if video is None:
        return False
    fn = video.filename or ""
    if not fn or fn.startswith(_PLACEHOLDER_PREFIX):
        return False
    return (_videos_dir() / fn).is_file()


def has_transcript(video: Video | None) -> bool:
    if video is None or video.transcript is None:
        return False
    tr = video.transcript
    return bool(tr.transcript_text and tr.asr_status == "done")


def _posts_of(
    db: Session,
    *,
    video_id: int | None = None,
    work_id: int | None = None,
    post_id: int | None = None,
) -> list[PlatformPost]:
    if work_id is not None:
        return db.query(PlatformPost).filter(PlatformPost.work_id == work_id).all()
    if post_id is not None:
        post = db.get(PlatformPost, post_id)
        return [post] if post else []
    if video_id is not None:
        video = db.get(Video, video_id)
        return _bound_platform_posts(db, video) if video else []
    return []


def _find_video(
    db: Session, posts: list[PlatformPost], *, video_id: int | None = None
) -> Video | None:
    """云端卡：返回已绑定/已存在的本地视频；本地卡直接返回自身。"""
    if video_id is not None:
        return db.get(Video, video_id)
    ids: list[int] = []
    for p in posts:
        if p.local_video_id:
            ids.append(p.local_video_id)
    if posts and posts[0].work_id:
        for wv in db.query(Video).filter(Video.work_id == posts[0].work_id).all():
            ids.append(wv.id)
    rows: list[Video] = []
    for vid in dict.fromkeys(ids):
        got = db.get(Video, vid)
        if got is not None:
            rows.append(got)
    if not rows:
        return None
    for item in rows:  # 优先已有真实文件的那条
        if has_real_file(item):
            return item
    return rows[0]


def _video_owner_id(db: Session, posts: list[PlatformPost]) -> int | None:
    """自动下载的本地素材应归属「素材所属博主」，而不是全局当前主博主（R-082 修复跨博主错挂）。

    优先级：合并作品 work.creator_id → 平台帖账号的 creator_id → 当前主博主兜底。
    """
    if not posts:
        return None
    work_id = posts[0].work_id
    if work_id:
        from ..models.work import Work  # 延迟导入避免循环

        work = db.get(Work, work_id)
        if work is not None and work.creator_id:
            return work.creator_id
    account = db.get(CreatorAccount, posts[0].account_id) if posts[0].account_id else None
    if account is not None and account.creator_id:
        return account.creator_id
    return current_creator_id(db)


def _create_video(db: Session, posts: list[PlatformPost], *, filename: str) -> Video | None:
    """下载成功后为云端卡建本地素材行；找不到归属博主则不建（调用方清理文件）。"""
    cid = _video_owner_id(db, posts)
    if cid is None or not posts:
        return None
    first = posts[0]
    platforms: list[str] = []
    known5 = ["求职", "面试", "赚钱", "知识", "其他"]
    main_topics: list[str] = []
    tags: list[str] = []
    for p in posts:
        if p.platform not in platforms:
            platforms.append(p.platform)
        try:
            arr = json.loads(p.tags or "[]")
        except json.JSONDecodeError:
            arr = []
        for t in arr or []:
            if t in known5:
                if t not in main_topics:
                    main_topics.append(t)
            elif t not in tags:
                tags.append(t)
    video = Video(
        filename=filename,
        title=first.title or "",
        creator_id=cid,
        platform_post_id=f"{first.platform}:{first.platform_post_id}",
        platforms=json.dumps(platforms, ensure_ascii=False),
        main_topics=json.dumps(main_topics, ensure_ascii=False),
        tags=json.dumps(tags, ensure_ascii=False),
        work_id=first.work_id,
        cover_path=first.cover_path or "",
        status="published",  # 平台已发布 => 本地素材视为已发布
        published_at=first.publish_time,
    )
    db.add(video)
    db.commit()
    db.refresh(video)
    for p in posts:
        p.local_video_id = video.id
    db.commit()
    return video


def inspect_media(
    db: Session,
    *,
    video_id: int | None = None,
    work_id: int | None = None,
    post_id: int | None = None,
) -> dict:
    """轻量预判（不联网）：返回卡片是否需要补齐视频/转写。"""
    posts = _posts_of(db, video_id=video_id, work_id=work_id, post_id=post_id)
    video = _find_video(db, posts, video_id=video_id)
    file_ok = has_real_file(video)
    tr_ok = has_transcript(video)
    if file_ok and tr_ok:
        action = "skip"
    elif file_ok:
        action = "transcribe"
    else:
        action = "download_transcribe"  # 云端卡无本地素材/占位 或本地卡缺文件
    return {
        "action": action,
        "video_id": video.id if video else None,
        "has_file": file_ok,
        "has_transcript": tr_ok,
        "source_posts": len(posts),
        "source_platforms": sorted({p.platform for p in posts if p.platform in _PLATFORM_PRIORITY}),
    }


def submit_media_task(
    db: Session,
    *,
    video_id: int | None = None,
    work_id: int | None = None,
    post_id: int | None = None,
) -> dict:
    """API 在数据同步成功后调用：预判 + 投递后台补齐任务（下载→自动转写）。"""
    info = inspect_media(db, video_id=video_id, work_id=work_id, post_id=post_id)
    if info["action"] == "skip":
        return {"status": "skip", "action": info["action"], "reason": "已有本地视频与转写，跳过"}
    payload: dict = {}
    if video_id is not None:
        payload["video_id"] = video_id
    elif work_id is not None:
        payload["work_id"] = work_id
    elif post_id is not None:
        payload["post_id"] = post_id
    task_id = start_task("platform_media", payload, platform_media_task)
    return {"status": "started", "action": info["action"], "task_id": task_id, "video_id": info["video_id"]}


def _bvid_of(post: PlatformPost) -> str:
    """从 B站平台帖 raw（列表接口 archives 自带 bvid）取 BV 号；兼容 data 包装。"""
    try:
        raw = json.loads(post.raw or "{}") if isinstance(post.raw, str) else (post.raw or {})
    except json.JSONDecodeError:
        raw = {}
    bvid = raw.get("bvid") or ""
    if not bvid and isinstance(raw.get("data"), dict):
        bvid = (raw.get("data") or {}).get("bvid") or ""
    return str(bvid or "").strip()


def _pick_source_posts(posts: list[PlatformPost]) -> list[PlatformPost]:

    return sorted(
        [p for p in posts if p.platform in _PLATFORM_PRIORITY],
        key=lambda p: _PLATFORM_PRIORITY.index(p.platform),
    )


def _download_pick(
    db: Session, posts: list[PlatformPost], on_try=None
) -> tuple[str, PlatformPost]:
    """按平台优先级尝试下载；成功返回（文件名, 命中的平台帖），全失败抛 MediaDownloadError。"""
    settings = get_settings()
    settings.videos_dir.mkdir(parents=True, exist_ok=True)
    last_error = ""
    for post in _pick_source_posts(posts):
        account = db.get(CreatorAccount, post.account_id)
        try:
            if on_try is not None:
                on_try(post.platform)
            from .platform.base import make_source  # 延迟导入避免循环

            client = make_source(post.platform)
            fetch = getattr(client, "fetch_video_source", None)
            if not callable(fetch):
                continue
            source = fetch(
                post.platform, post.platform_post_id, account=account, prefer_url=post.video_url or ""
            )
            if getattr(client, "mode", "") == "real":
                _charge(db)  # real 解析请求计入每日预算
            title = post.title or post.platform_post_id
            stem = media_stem(post.platform, title, "视频")
            if source:
                dest = unique_path(settings.videos_dir, stem, ".mp4")
                download_platform_video(source, post.platform, dest)
                return dest.name, post
            # B站：TikHub 当前拿不到流（404）→ yt-dlp 直连兜底（R-078，低清视频+音频）
            if post.platform == "bilibili":
                bvid = _bvid_of(post)
                if not bvid:
                    last_error = f"{post.platform}: 缺少 BV 号（raw 未存 bvid）"
                    continue
                dest = unique_path(settings.videos_dir, stem, ".mp4")
                cookie = (account.extra() if account else {}).get("cookie") or ""
                download_bilibili_via_ytdlp(bvid, dest, cookie=cookie)
                return dest.name, post
            continue
        except BudgetExceeded:
            raise
        except Exception as exc:  # noqa: BLE001 单平台失败尝试下一个
            db.rollback()
            last_error = f"{post.platform}: {str(exc)[:160]}"
    raise MediaDownloadError(f"无可用视频源（{last_error or '该作品可能无视频或需登录'}）")


def platform_media_task(db: Session, payload: dict, update=None) -> dict:
    """后台任务：补视频 →（成功且缺转写）自动转写。

    update(pct, note) 可选：由 tasks 运行器注入，实时回写进度百分比与阶段说明（R-081）。
    """
    def _up(pct: int, note: str = "") -> None:
        if update is not None:
            update(pct, note)

    video_id = payload.get("video_id")
    work_id = payload.get("work_id")
    post_id = payload.get("post_id")
    _up(15, "检查视频文件与转写状态…")
    posts = _posts_of(db, video_id=video_id, work_id=work_id, post_id=post_id)
    video = _find_video(db, posts, video_id=video_id)

    downloaded = False
    file_name = ""
    hit_post: PlatformPost | None = None
    if not has_real_file(video):
        _up(35, "准备下载视频…")

        def _on_try(platform: str) -> None:
            label = {"douyin": "抖音", "xiaohongshu": "小红书", "bilibili": "B站"}.get(platform, platform)
            _up(40, f"正在下载视频（{label}）…")

        file_name, hit_post = _download_pick(db, posts, on_try=_on_try)
        if video is None:
            video = _create_video(db, posts, filename=file_name)
            if video is None:  # 无主博主：不留死文件，明确失败
                (_videos_dir() / file_name).unlink(missing_ok=True)
                return {"status": "no_creator", "reason": "未找到主博主，未创建本地素材", "video_id": None}
        else:
            video.filename = file_name
            video.cover_path = video.cover_path or hit_post.cover_path or ""
            if not video.platform_post_id:
                video.platform_post_id = f"{hit_post.platform}:{hit_post.platform_post_id}"
            db.commit()
        downloaded = True

    # 有真实文件但缺转写 => 自动触发转写（复用完整流水线：ASR→校对→预打标签）
    transcribed = False
    if video is not None and has_real_file(video) and not has_transcript(video):
        _up(88, "语音转写中（可能需要几分钟）…")
        from .ingest import import_video_task  # 延迟导入避免循环

        import_video_task(db, {"video_id": video.id})
        transcribed = True
        _up(96, "转写完成，整理中…")

    if not downloaded and not transcribed:
        return {"status": "skip", "reason": "已有本地视频与转写", "video_id": video.id if video else None}
    msg = []
    if downloaded and hit_post is not None:
        msg.append(f"已下载视频（{hit_post.platform}）")
    if transcribed:
        msg.append("已自动转写")
    return {
        "status": "done",
        "message": "；".join(msg) or "完成",
        "video_id": video.id if video else None,
        "downloaded": downloaded,
        "transcribed": transcribed,
        "file": video.filename if video else "",
    }


def run_media_seq(db: Session, posts: list[PlatformPost]) -> dict:
    """顺序执行多条帖子的媒体补齐（R-088）。

    每条帖子注册为一条 platform_media 后台任务行并实时广播 task.update，
    这样博主页触发的前N条/每日自动同步，素材库对应卡片也能显示覆盖进度、切页可恢复。
    """
    import json as _json

    stats = {"downloaded": 0, "transcribed": 0, "skipped": 0, "errors": 0}
    for post in posts:
        row = BackgroundTask(
            kind="platform_media", payload=_json.dumps({"post_id": post.id}, ensure_ascii=False)
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        tid = row.id

        def _up(pct: int | None = None, note: str = "") -> None:
            t = db.get(BackgroundTask, tid)
            if t is None:
                return
            if pct is not None:
                t.progress = max(0, min(100, int(pct)))
            if note:
                t.note = note[:255]
            t.status = "running"
            db.commit()
            publish(
                "task.update",
                {"id": tid, "status": "running", "progress": t.progress, "note": t.note or "", "payload": {"post_id": post.id}},
            )

        def _fail(err: str) -> None:
            t = db.get(BackgroundTask, tid)
            if t is not None:
                t.status = "failed"
                t.error = err[:500]
                db.commit()
                publish(
                    "task.update",
                    {"id": tid, "status": "failed", "progress": t.progress, "note": t.note or "", "error": err[:500], "payload": {"post_id": post.id}},
                )

        _up(5, "准备同步该作品…")
        try:
            res = platform_media_task(db, {"post_id": post.id}, _up)
            t = db.get(BackgroundTask, tid)
            if t is not None:
                t.status = "done"
                t.progress = 100
                t.note = "完成"
                db.commit()
                publish("task.update", {"id": tid, "status": "done", "progress": 100, "note": "完成", "payload": {"post_id": post.id}})
            if res.get("status") == "done":
                if res.get("downloaded"):
                    stats["downloaded"] += 1
                if res.get("transcribed"):
                    stats["transcribed"] += 1
            else:
                stats["skipped"] += 1
        except BudgetExceeded:
            _fail("预算不足，停止媒体补齐")
            stats["errors"] += 1
            db.rollback()
            break
        except Exception as exc:  # noqa: BLE001 单条失败不影响其它条
            db.rollback()
            _fail(str(exc))
            stats["errors"] += 1
    return stats
