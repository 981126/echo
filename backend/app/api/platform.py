"""平台数据接口（M13，R-027/R-028/R-029）：云端作品/指标/同步任务/预算/选题池/转素材。"""

from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..core.pipeline import today_key
from ..db import get_db
from ..models.hot_topic import TopicIdea
from ..models.platform import (
    Creator,
    CreatorAccount,
    CreatorAccountSnapshot,
    PlatformPost,
    PlatformPostStat,
    SyncJob,
)
from ..models.video import Video
from ..schemas.platform import SyncRequest
from ..services.creator_service import current_creator_id
from ..services.platform.tikhub import make_client
from ..services.platform_sync import (
    get_budget,
    run_sync,
    set_budget,
    sync_local_video_metrics,
    sync_single_post,
)
from ..tasks import start_task

router = APIRouter()


# ---------- 云端作品 ----------
def _post_item(db: Session, p: PlatformPost, account=None, stat=None) -> dict:
    if account is None:
        account = db.get(CreatorAccount, p.account_id)
    if stat is None:
        stat = (
            db.query(PlatformPostStat)
            .filter(PlatformPostStat.post_id == p.id)
            .order_by(PlatformPostStat.stat_date.desc())
            .first()
        )
    acc = account
    creator = db.get(Creator, acc.creator_id) if acc else None
    return {
        "id": p.id,
        "account_id": p.account_id,
        "creator_id": acc.creator_id if acc else None,
        "creator_name": (creator.name if creator else (acc.nickname if acc else "")),
        "creator_kind": creator.kind if creator else "owner",
        "platform": p.platform,
        "platform_post_id": p.platform_post_id,
        "title": p.title,
        "desc": p.desc,
        "cover": p.cover_url_local,
        "video_url": p.video_url,
        "publish_time": p.publish_time.isoformat() if p.publish_time else None,
        "local_video_id": p.local_video_id,
        "latest_stat": {
            "date": stat.stat_date,
            "plays": stat.plays,
            "likes": stat.likes,
            "favorites": stat.favorites,
            "shares": stat.shares,
            "comments": stat.comments,
            "extra": stat.extra,
        }
        if stat
        else None,
        "created_at": p.created_at.isoformat() if p.created_at else None,
    }


@router.get("/posts")
def list_posts(
    creator_id: int = 0,
    account_id: int = 0,
    platform: str = "",
    kind: str = "",  # owner | benchmark
    limit: int = 50,
    offset: int = 0,
    db: Session = Depends(get_db),
):
    q = db.query(PlatformPost).join(CreatorAccount, CreatorAccount.id == PlatformPost.account_id)
    if creator_id:
        q = q.filter(CreatorAccount.creator_id == creator_id)
    elif kind:
        cids = [c.id for c in db.query(Creator).filter(Creator.kind == kind).all()]
        q = q.filter(CreatorAccount.creator_id.in_(cids)) if cids else q.filter(CreatorAccount.creator_id < 0)
    if account_id:
        q = q.filter(PlatformPost.account_id == account_id)
    if platform:
        q = q.filter(PlatformPost.platform == platform)
    total = q.count()
    items = q.order_by(PlatformPost.publish_time.desc().nullslast(), PlatformPost.id.desc()).offset(offset).limit(limit).all()
    # 批量预取账号与最新统计，避免 N+1
    ids = [p.id for p in items]
    account_map = {
        a.id: a for a in db.query(CreatorAccount).filter(CreatorAccount.id.in_({p.account_id for p in items})).all()
    }
    from ..services.works_service import latest_stats_map

    stat_map = latest_stats_map(db, ids)
    return {
        "total": total,
        "items": [_post_item(db, p, account_map.get(p.account_id), stat_map.get(p.id)) for p in items],
    }


@router.post("/videos/{video_id}/bind-links", response_model=dict)
def bind_video_links(video_id: int, payload: dict, db: Session = Depends(get_db)):
    """R-036：编辑页按平台填写链接 → 解析并绑定各平台作品（支持三平台）。

    每个非空链接解析后：若平台作品表已有该作品则直接绑定（local_video_id），
    否则在当前主博主的该平台账号下创建占位作品再绑定。
    """
    from ..services.platform.tikhub import parse_post_id

    video = db.get(Video, video_id)
    if video is None:
        raise HTTPException(status_code=404, detail="素材不存在")
    links = (payload or {}).get("links") or {}
    if not isinstance(links, dict):
        raise HTTPException(status_code=400, detail="links 格式错误")
    cid = current_creator_id(db)
    bound: list[dict] = []
    errors: list[str] = []
    for platform in ("douyin", "bilibili", "xiaohongshu"):
        link = str(links.get(platform) or "").strip()
        if not link:
            continue
        parsed_platform, ext = parse_post_id(link)
        if not parsed_platform or not ext:
            errors.append(f"{platform} 链接无法解析")
            continue
        if parsed_platform != platform:
            errors.append(f"该链接是 {parsed_platform}，却填在了 {platform} 栏")
            continue
        post = (
            db.query(PlatformPost)
            .filter(PlatformPost.platform == platform, PlatformPost.platform_post_id == ext)
            .first()
        )
        if post is None:
            account = None
            if cid:
                account = (
                    db.query(CreatorAccount)
                    .filter(CreatorAccount.creator_id == cid, CreatorAccount.platform == platform)
                    .first()
                )
            if account is None:
                errors.append(f"{platform}：未配置该平台账号（请先在博主管理添加）")
                continue
            post = PlatformPost(
                account_id=account.id,
                platform=platform,
                platform_post_id=ext,
                title=video.title or "",
                raw="{}",
            )
            db.add(post)
            db.flush()
        post.local_video_id = video.id
        plats = json.loads(video.platforms or "[]") if isinstance(video.platforms, str) else (video.platforms or [])
        if platform not in plats:
            plats.append(platform)
            video.platforms = json.dumps(plats, ensure_ascii=False)
        if not (video.platform_post_id or "").strip():
            video.platform_post_id = f"{platform}:{ext}"
        bound.append({"platform": platform, "platform_post_id": ext})
    # 存在真实平台链接 => 已发布
    if bound:
        video.status = "published"
        from datetime import datetime

        if not video.published_at:
            video.published_at = datetime.utcnow()
    db.commit()
    if errors and not bound:
        raise HTTPException(status_code=400, detail="；".join(errors))
    return {"ok": True, "bound": bound, "errors": errors}


@router.post("/posts/{post_id}/sync", response_model=dict)
def sync_post(post_id: int, db: Session = Depends(get_db)):
    try:
        return sync_single_post(db, post_id)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/posts/{post_id}/to-material", response_model=dict)
def post_to_material(post_id: int, db: Session = Depends(get_db)):
    """把云端作品转为本地素材（归属当前主博主；mock 阶段无视频文件，可后补上传）。"""
    post = db.get(PlatformPost, post_id)
    if post is None:
        raise HTTPException(status_code=404, detail="云端作品不存在")
    if post.local_video_id:
        return {"ok": True, "video_id": post.local_video_id}
    cid = current_creator_id(db)
    if cid is None:
        raise HTTPException(status_code=400, detail="请先创建并切换到一个主博主")
    video = Video(
        filename="",  # mock：无真实文件，后续可上传/下载
        title=post.title,
        creator_id=cid,
        platform_post_id=f"{post.platform}:{post.platform_post_id}",
        platforms=json.dumps([post.platform], ensure_ascii=False),
        status="planned",
        cover_path=post.cover_path,
        work_id=post.work_id,
    )
    db.add(video)
    db.commit()
    db.refresh(video)
    post.local_video_id = video.id
    if post.work_id and video.work_id is None:
        video.work_id = post.work_id
    db.commit()
    return {"ok": True, "video_id": video.id, "video": {"id": video.id, "title": video.title}}


@router.post("/posts/{post_id}/comments/refresh", response_model=dict)
def refresh_post_comments(post_id: int, limit: int = 30, db: Session = Depends(get_db)):
    """点“加载评论”：实时调第三方拉取 → 去重落库 → 返回（下次直接读本地）。"""
    import json as _json

    from ..models.platform import PlatformPostComment

    post = db.get(PlatformPost, post_id)
    if post is None:
        raise HTTPException(status_code=404, detail="云端作品不存在")
    acc = db.get(CreatorAccount, post.account_id)
    raw = {}
    try:
        raw = _json.loads(post.raw or "{}") if isinstance(post.raw, str) else (post.raw or {})
    except _json.JSONDecodeError:
        raw = {}
    client = make_client()
    try:
        texts = client.fetch_comments(post.platform, post.platform_post_id, max(1, min(limit, 50)), acc, raw=raw)
    except Exception:  # noqa: BLE001
        texts = []
    added = 0
    for c in texts:
        c = (c or "").strip()
        if not c:
            continue
        dup = (
            db.query(PlatformPostComment)
            .filter(PlatformPostComment.post_id == post_id, PlatformPostComment.text == c)
            .first()
        )
        if dup is None:
            db.add(PlatformPostComment(post_id=post_id, platform=post.platform, text=c))
            added += 1
    db.commit()
    rows = (
        db.query(PlatformPostComment)
        .filter(PlatformPostComment.post_id == post_id)
        .order_by(PlatformPostComment.id.desc())
        .limit(200)
        .all()
    )
    return {"post_id": post_id, "platform": post.platform, "items": [r.text for r in rows], "added": added}


@router.get("/posts/{post_id}/comments", response_model=dict)
def post_comments(post_id: int, limit: int = 50, refresh: int = 0, db: Session = Depends(get_db)):
    """评论：默认读本地库；refresh=1 时实时调第三方并把新评论去重落库后再返回。"""
    import json as _json

    from ..models.platform import PlatformPostComment

    post = db.get(PlatformPost, post_id)
    if post is None:
        raise HTTPException(status_code=404, detail="云端作品不存在")
    if int(refresh or 0):
        acc = db.get(CreatorAccount, post.account_id)
        raw = {}
        try:
            raw = _json.loads(post.raw or "{}") if isinstance(post.raw, str) else (post.raw or {})
        except _json.JSONDecodeError:
            raw = {}
        try:
            client = make_client()
            texts = client.fetch_comments(post.platform, post.platform_post_id, 50, acc, raw=raw)
        except Exception:  # noqa: BLE001 拉取失败不阻断
            texts = []
        added = 0
        for t in texts:
            t = (t or "").strip()
            if not t:
                continue
            dup = (
                db.query(PlatformPostComment)
                .filter(PlatformPostComment.post_id == post_id, PlatformPostComment.text == t)
                .first()
            )
            if dup is None:
                db.add(PlatformPostComment(post_id=post_id, platform=post.platform, text=t))
                added += 1
        db.commit()
    rows = (
        db.query(PlatformPostComment)
        .filter(PlatformPostComment.post_id == post_id)
        .order_by(PlatformPostComment.id)
        .all()
    )
    seen = set()
    items = []
    for r in rows:
        if r.text in seen:
            continue
        seen.add(r.text)
        items.append(r.text)
        if len(items) >= max(1, min(limit, 200)):
            break
    return {"post_id": post_id, "platform": post.platform, "items": items}



@router.get("/posts/{post_id}/stats", response_model=dict)
def post_stats_series(post_id: int, db: Session = Depends(get_db)):
    rows = (
        db.query(PlatformPostStat)
        .filter(PlatformPostStat.post_id == post_id)
        .order_by(PlatformPostStat.stat_date)
        .all()
    )
    return {
        "post_id": post_id,
        "series": [
            {
                "date": r.stat_date,
                "plays": r.plays,
                "likes": r.likes,
                "favorites": r.favorites,
                "shares": r.shares,
                "comments": r.comments,
            }
            for r in rows
        ],
    }


# ---------- 主页快照 ----------
@router.get("/accounts/{account_id}/snapshots")
def account_snapshots(account_id: int, db: Session = Depends(get_db)):
    rows = (
        db.query(CreatorAccountSnapshot)
        .filter(CreatorAccountSnapshot.account_id == account_id)
        .order_by(CreatorAccountSnapshot.snapshot_date)
        .all()
    )
    return {
        "account_id": account_id,
        "items": [
            {
                "date": r.snapshot_date,
                "nickname": r.nickname,
                "followers": r.followers,
                "likes_total": r.likes_total,
                "posts_total": r.posts_total,
                "following": r.following,
            }
            for r in rows
        ],
    }


# ---------- 同步触发与任务 ----------
def _start_sync(payload: dict, scope: str = "daily"):
    def fn(db: Session, pl: dict):
        return run_sync(
            db,
            scope=pl.get("scope", scope),
            account_id=pl.get("account_id"),
            creator_id=pl.get("creator_id"),
            top_n=pl.get("top_n"),
        )

    return start_task("platform_sync", payload, fn)


@router.post("/sync", response_model=dict)
def trigger_sync(payload: SyncRequest, db: Session = Depends(get_db)):
    """手动同步：initial=首次全量；daily=top10；weekly=对标每周；可限定 account/creator。"""
    task_id = _start_sync(
        {
            "scope": payload.scope,
            "account_id": payload.account_id,
            "creator_id": payload.creator_id,
            "top_n": payload.top_n,
        },
        scope=payload.scope,
    )
    return {"task_id": task_id, "scope": payload.scope}


@router.post("/videos/{video_id}/sync", response_model=dict)
def sync_video_data(video_id: int, db: Session = Depends(get_db)):
    """素材库单条"同步数据"（本地素材需已绑定发布链接）。"""
    video = db.get(Video, video_id)
    if video is None:
        raise HTTPException(status_code=404, detail="素材不存在")
    try:
        return sync_local_video_metrics(db, video)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/jobs", response_model=dict)
def list_jobs(limit: int = 30, db: Session = Depends(get_db)):
    rows = db.query(SyncJob).order_by(SyncJob.id.desc()).limit(limit).all()
    return {
        "items": [
            {
                "id": r.id,
                "job_type": r.job_type,
                "scope": r.scope,
                "status": r.status,
                "message": r.message,
                "stats": json.loads(r.stats or "{}"),
                "started_at": r.started_at.isoformat() if r.started_at else None,
                "finished_at": r.finished_at.isoformat() if r.finished_at else None,
            }
            for r in rows
        ]
    }


# ---------- 预算 / 余额 ----------
@router.get("/budget", response_model=dict)
def budget(db: Session = Depends(get_db), refresh_balance: bool = False):
    """预算额度（本地 Kv，毫秒级）；余额查询第三方较慢，默认不阻塞页面，
    需要时显式 ?refresh_balance=true 再拉取。"""
    b = get_budget(db)
    bal = None
    if refresh_balance:
        try:
            bal = make_client().get_balance()
        except Exception:  # noqa: BLE001
            bal = {"mode": "unknown"}
    return {**b, "balance": bal}


@router.put("/budget", response_model=dict)
def update_budget(payload: dict, db: Session = Depends(get_db)):
    try:
        limit = int(payload.get("limit") or 0)
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail="limit 必须为数字") from exc
    return set_budget(db, limit)


# ---------- 选题池（R-028） ----------
@router.get("/topic-pool")
def topic_pool(date: str = "", db: Session = Depends(get_db)):
    key = date or today_key()
    ideas = (
        db.query(TopicIdea)
        .filter(TopicIdea.snapshot_date == key, TopicIdea.used.is_(False))
        .order_by(TopicIdea.id.desc())
        .all()
    )
    return {
        "date": key,
        "total": len(ideas),
        "items": [
            {
                "id": r.id,
                "source": r.source,
                "platform": r.platform,
                "title": r.title,
                "detail": r.detail,
                "post_title": r.post_title,
            }
            for r in ideas
        ],
    }


@router.post("/topic-pool/{idea_id}/generate", response_model=dict)
def generate_from_idea(idea_id: int, db: Session = Depends(get_db)):
    """从选题池灵感生成草稿（人工挑选后触发；不自动推送）。"""
    idea = db.get(TopicIdea, idea_id)
    if idea is None:
        raise HTTPException(status_code=404, detail="选题灵感不存在")
    from .drafts import GenerateIn
    from .drafts import generate as generate_draft_api

    # 复用草稿生成逻辑（同步生成，页面等待）
    result = generate_draft_api(GenerateIn(topic=idea.title), db)
    idea.used = True
    db.commit()
    return {"ok": True, "draft": result}


@router.delete("/topic-pool/{idea_id}", response_model=dict)
def dismiss_idea(idea_id: int, db: Session = Depends(get_db)):
    idea = db.get(TopicIdea, idea_id)
    if idea is None:
        raise HTTPException(status_code=404, detail="选题灵感不存在")
    idea.used = True
    db.commit()
    return {"ok": True}


@router.get("/creator-summary")
def creator_summary(db: Session = Depends(get_db)):
    """复盘/博主页"我 vs 对标"汇总（粉丝/作品数/互动中位数/爆款率，基于最新快照与统计）。"""
    creators = db.query(Creator).order_by(Creator.id).all()
    out = []
    for c in creators:
        accounts = db.query(CreatorAccount).filter(CreatorAccount.creator_id == c.id).all()
        totals = {"followers": 0, "posts": 0, "plays": 0, "likes": 0, "favorites": 0, "comments": 0}
        account_info = []
        for a in accounts:
            snap = (
                db.query(CreatorAccountSnapshot)
                .filter(CreatorAccountSnapshot.account_id == a.id)
                .order_by(CreatorAccountSnapshot.snapshot_date.desc())
                .first()
            )
            posts = (
                db.query(PlatformPost)
                .filter(PlatformPost.account_id == a.id)
                .order_by(PlatformPost.publish_time.desc())
                .limit(50)
                .all()
            )
            stat_rows = []
            for p in posts:
                st = (
                    db.query(PlatformPostStat)
                    .filter(PlatformPostStat.post_id == p.id)
                    .order_by(PlatformPostStat.stat_date.desc())
                    .first()
                )
                if st:
                    stat_rows.append(st)
            followers = snap.followers if snap else 0
            plays_list = [s.plays for s in stat_rows]
            med_plays = sorted(plays_list)[len(plays_list) // 2] if plays_list else 0
            hot_count = sum(1 for s in stat_rows if s.plays >= 100000)
            totals["followers"] += followers
            totals["posts"] += len(stat_rows) or len(posts)
            totals["plays"] += sum(plays_list)
            totals["likes"] += sum(s.likes for s in stat_rows)
            totals["favorites"] += sum(s.favorites for s in stat_rows)
            totals["comments"] += sum(s.comments for s in stat_rows)
            account_info.append(
                {
                    "platform": a.platform,
                    "nickname": snap.nickname if snap else a.nickname,
                    "followers": followers,
                    "posts": len(posts),
                    "median_plays": med_plays,
                    "hot_posts": hot_count,
                }
            )
        out.append(
            {
                "creator": {"id": c.id, "kind": c.kind, "parent_id": c.parent_id, "name": c.name, "is_current": c.is_current},
                "totals": totals,
                "accounts": account_info,
            }
        )
    return {"items": out}
