"""平台数据接口（M13，R-027/R-028/R-029）：云端作品/指标/同步任务/预算/选题池/转素材。"""

from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func
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
from ..services.creator_service import current_creator_id, get_current_creator
from ..services.media_ensure import inspect_media, submit_media_task
from ..services.platform.base import make_source
from ..services.platform.budget import get_budget, set_budget
from ..services.platform_sync import (
    all_top15_worker,
    enqueue_all_top15_sync,
    run_sync,
    sync_local_video_metrics,
    sync_single_post,
    sync_work_posts,
)
from ..services.text_tags import strip_hashtags
from ..tasks import start_task

router = APIRouter()


# ---------- 云端作品 ----------
def _post_item(db: Session, p: PlatformPost, account=None, stat=None) -> dict:
    """平台作品统一序列化（复用 works_service.post_item，R-061 收敛）。"""
    from ..services.works_service import post_item as _post_item_full

    return _post_item_full(db, p, account, stat)



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
        from ..core.timeutil import now as _app_now

        if not video.published_at:
            video.published_at = _app_now()
    db.commit()
    if errors and not bound:
        raise HTTPException(status_code=400, detail="；".join(errors))
    _rename_media_after_bind(db, video)
    return {"ok": True, "bound": bound, "errors": errors}


def _read_comments(db: Session, post_id: int, limit: int = 50) -> list[dict]:
    """读本地评论：按点赞降序（同赞按新到旧），文本去重，最多 200 条供分页截断。"""
    from ..models.platform import PlatformPostComment

    rows = (
        db.query(PlatformPostComment)
        .filter(PlatformPostComment.post_id == post_id)
        .order_by(PlatformPostComment.likes.desc(), PlatformPostComment.id.desc())
        .all()
    )
    seen: set[str] = set()
    items: list[dict] = []
    for r in rows:
        if r.text in seen:
            continue
        seen.add(r.text)
        items.append({"text": r.text, "likes": int(r.likes or 0), "user_nick": r.user_nick or ""})
        if len(items) >= max(1, min(int(limit or 50), 200)):
            break
    return items


@router.post("/works/{work_id}/sync", response_model=dict)
def sync_work(work_id: int, db: Session = Depends(get_db)):
    """云端合并作品卡「同步数据」（R-067/R-077）：同步全部平台帖指标+评论 Top50；缺视频/转写则补齐。"""
    try:
        res = sync_work_posts(db, work_id)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    res["media"] = submit_media_task(db, work_id=work_id)  # R-077
    return res


@router.post("/posts/{post_id}/sync", response_model=dict)
def sync_post(post_id: int, db: Session = Depends(get_db)):
    """云端单条作品卡「同步数据」（R-067/R-077）：指标+评论 Top50；缺视频/转写则补齐。"""
    try:
        res = sync_single_post(db, post_id)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    res["media"] = submit_media_task(db, post_id=post_id)  # R-077
    return res


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
    # R-225：若该帖已属于合并 work，素材的平台应包含全部成员平台
    if post.work_id:
        work_platforms = sorted(
            {p.platform for p in db.query(PlatformPost).filter(PlatformPost.work_id == post.work_id).all() if p.platform}
        )
    else:
        work_platforms = [post.platform]
    video = Video(
        filename=f"__cloud__{post.id}",  # 无真实文件：占位名保证唯一（前端据此不显示转写）
        title=strip_hashtags(post.title or ""),
        creator_id=cid,
        platform_post_id=f"{post.platform}:{post.platform_post_id}",
        platforms=json.dumps(work_platforms, ensure_ascii=False),
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
def refresh_post_comments(post_id: int, limit: int = 50, db: Session = Depends(get_db)):
    """点“加载评论”：实时调第三方拉取（点赞 Top50）→ 去重落库 → 返回（下次直接读本地）。"""
    import json as _json

    from ..services.platform_sync import _upsert_comments

    post = db.get(PlatformPost, post_id)
    if post is None:
        raise HTTPException(status_code=404, detail="云端作品不存在")
    acc = db.get(CreatorAccount, post.account_id)
    if acc is not None:
        from ..services.douyin_account_policy import resolve_data_policy

        policy = resolve_data_policy(db, acc)
        if policy.is_blocked:
            raise HTTPException(status_code=400, detail=policy.reason)
    raw = {}
    try:
        raw = _json.loads(post.raw or "{}") if isinstance(post.raw, str) else (post.raw or {})
    except _json.JSONDecodeError:
        raw = {}
    client = make_source(post.platform)
    want = max(1, min(int(limit or 50), 50))
    try:
        items = client.fetch_comments(post.platform, post.platform_post_id, want, acc, raw=raw)
    except Exception:  # noqa: BLE001
        items = []
    cres = _upsert_comments(db, post, items, limit=want)
    return {
        "post_id": post_id,
        "platform": post.platform,
        "items": _read_comments(db, post_id, 200),
        "added": cres["added"],
        "updated": cres["updated"],
    }


@router.get("/posts/{post_id}/comments", response_model=dict)
def post_comments(post_id: int, limit: int = 50, refresh: int = 0, db: Session = Depends(get_db)):
    """评论：默认读本地库（按点赞降序）；refresh=1 时实时调第三方（点赞 Top50）落库后再返回。"""
    import json as _json

    from ..services.platform_sync import _upsert_comments

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
            client = make_source(post.platform)
            items = client.fetch_comments(post.platform, post.platform_post_id, 50, acc, raw=raw)
        except Exception:  # noqa: BLE001 拉取失败不阻断
            items = []
        _upsert_comments(db, post, items, limit=50)
    return {
        "post_id": post_id,
        "platform": post.platform,
        "items": _read_comments(db, post_id, limit),
    }



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
            with_media=(pl.get("scope", scope) == "daily"),  # R-085：前10条同步带视频下载+转写
        )

    return start_task("platform_sync", payload, fn)


@router.post("/sync", response_model=dict)
def trigger_sync(payload: SyncRequest, db: Session = Depends(get_db)):
    """手动同步：initial=首次全量；daily=top20（R-070）；weekly=对标每周；可限定 account/creator。"""
    # R-135：相同 scope/账号/博主的同步已在排队或执行中 → 拒绝重复入队（连点会重复拉 TikHub + 重复下载）
    from ..models.task import BackgroundTask

    for row in (
        db.query(BackgroundTask)
        .filter(BackgroundTask.kind == "platform_sync", BackgroundTask.status.in_(["pending", "running"]))
        .all()
    ):
        try:
            pl = json.loads(row.payload or "{}")
        except (TypeError, ValueError):
            continue
        if (
            pl.get("scope") == payload.scope
            and pl.get("account_id") == payload.account_id
            and pl.get("creator_id") == payload.creator_id
        ):
            raise HTTPException(status_code=409, detail="相同的同步任务正在进行中，请稍候")
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


@router.post("/sync-all", response_model=dict)
def trigger_sync_all(db: Session = Depends(get_db)):
    """R-162：一键同步当前主博主 + 其全部对标博主最新15条（daily 同口径）。

    点击后为每个博主入队一条任务并预置同步记录（前端所有卡片立即可见动画），
    由**一个后台消费者按队列顺序逐个消费**；运行中的博主跳过并汇总。完成后自动重新对标。
    """
    from ..models.task import BackgroundTask

    owner = get_current_creator(db)
    if owner is None:
        raise HTTPException(status_code=400, detail="请先创建并切换到主博主")
    for row in (
        db.query(BackgroundTask)
        .filter(BackgroundTask.kind == "platform_sync", BackgroundTask.status.in_(["pending", "running"]))
        .all()
    ):
        try:
            pl = json.loads(row.payload or "{}")
        except (TypeError, ValueError):
            continue
        if pl.get("scope") == "all_top15" and pl.get("owner_id") == owner.id:
            raise HTTPException(status_code=409, detail="全部博主同步任务正在进行中，请稍候")
    enq = enqueue_all_top15_sync(db, owner)
    if not enq["entries"]:
        detail = "没有可同步的博主（可能都在运行中或未配置账号）"
        if enq["skipped"]:
            # R-219：skipped 为结构化 [{creator_id, name, reason}]
            detail += "：" + "、".join(f"{s['name']}({s['reason']})" for s in enq["skipped"])
        raise HTTPException(status_code=400, detail=detail)
    task_id = start_task(
        "platform_sync",
        {"scope": "all_top15", "owner_id": owner.id, "entries": enq["entries"]},
        all_top15_worker,
    )
    return {"task_id": task_id, "creator_count": len(enq["entries"]), "skipped": enq["skipped"]}


@router.post("/videos/{video_id}/sync", response_model=dict)
def sync_video_data(video_id: int, db: Session = Depends(get_db)):
    """素材库本地卡"同步数据"（R-067/R-077）：同步绑定平台指标+评论 Top50；缺转写则自动补齐。

    未绑定平台帖时不再硬报错：有本地视频缺转写仍会触发转写（数据同步部分跳过）。
    """
    video = db.get(Video, video_id)
    if video is None:
        raise HTTPException(status_code=404, detail="素材不存在")
    from ..services.douyin_creator_sync import CredentialError

    try:
        res = sync_local_video_metrics(db, video)
    except CredentialError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ValueError as exc:
        info = inspect_media(db, video_id=video.id)
        if info["action"] == "skip":  # 已完整则无需处理，维持原提示
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        res = {"message": "该素材未绑定平台作品，已跳过数据同步", "platforms": []}
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    res["media"] = submit_media_task(db, video_id=video.id)  # R-077
    return res


@router.get("/jobs", response_model=dict)
def list_jobs(limit: int = 30, status: str = "", db: Session = Depends(get_db)):
    q = db.query(SyncJob)
    if status:
        q = q.filter(SyncJob.status == status)
    rows = q.order_by(SyncJob.id.desc()).limit(limit).all()
    return {
        "items": [
            {
                "id": r.id,
                "job_type": r.job_type,
                "scope": r.scope,
                "status": r.status,
                "message": r.message,
                "stats": json.loads(r.stats or "{}"),
                "creator_id": r.creator_id,
                "account_id": r.account_id,
                "progress_done": r.progress_done or 0,
                "progress_total": r.progress_total or 0,
                "progress_note": r.progress_note or "",
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
            bal = make_source().get_balance()
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
    q = db.query(TopicIdea).filter(TopicIdea.snapshot_date == key, TopicIdea.used.is_(False))
    cid = current_creator_id(db)  # R-135：选题池按博主隔离，避免对标博主评论灵感串味
    if cid:
        q = q.filter(TopicIdea.creator_id == cid)
    ideas = q.order_by(TopicIdea.likes.desc(), TopicIdea.id.desc()).all()
    items = [
        {
            "id": r.id,
            "source": r.source,
            "platform": r.platform,
            "title": r.title,
            "detail": r.detail,
            "post_title": r.post_title,
            "likes": r.likes or 0,
        }
        for r in ideas
    ]
    # R-072：标注人设相关度（评论不剔除，只供排序/展示）
    from ..services.ideas_service import annotate_items

    annotated = annotate_items(db, items)
    return {
        "date": key,
        "total": len(annotated),
        "items": annotated,
    }


@router.post("/topic-pool/{idea_id}/generate", response_model=dict)
def generate_from_idea(idea_id: int, db: Session = Depends(get_db)):
    """从选题池灵感生成草稿（人工挑选后触发；不自动推送）。

    遗留同步接口（R-240 M7 仅标注，不改契约）：前端等待完整生成（分钟级），
    后续应迁到 `/api/drafts/generate-async` 后台任务；本次不动返回结构，避免前端改动。
    """
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
    """复盘/博主页"我 vs 对标"汇总（粉丝/作品数/互动中位数/爆款率，基于最新快照与统计）。

    R-241：原实现每 creator/账号/帖子逐条查询（实测 703 条 SQL / 380ms）→ 改为 5 条批量
    SQL（创作者、账号、DISTINCT ON 最新快照、ROW_NUMBER 各账号最近 50 帖、DISTINCT ON
    最新统计），Python 聚合算法与输出结构/排序完全不变。
    """
    creators = db.query(Creator).order_by(Creator.id).all()
    # 与原实现同口径：不显式排序（PG 堆序遍历），按 creator 分组后保持原相对顺序
    accounts = db.query(CreatorAccount).all()
    accounts_by_creator: dict[int, list[CreatorAccount]] = {}
    for account in accounts:
        accounts_by_creator.setdefault(account.creator_id, []).append(account)
    account_ids = [account.id for account in accounts]

    snap_by_account: dict[int, CreatorAccountSnapshot] = {}
    posts_by_account: dict[int, list[int]] = {}
    stat_by_post: dict[int, PlatformPostStat] = {}
    if account_ids:
        for row_snap in (
            db.query(CreatorAccountSnapshot)
            .filter(CreatorAccountSnapshot.account_id.in_(account_ids))
            .distinct(CreatorAccountSnapshot.account_id)
            .order_by(CreatorAccountSnapshot.account_id, CreatorAccountSnapshot.snapshot_date.desc())
            .all()
        ):
            snap_by_account.setdefault(row_snap.account_id, row_snap)  # DESC 序首个即最新
        numbered = (
            db.query(
                PlatformPost.account_id.label("account_id"),
                PlatformPost.id.label("post_id"),
                func.row_number()
                .over(
                    partition_by=PlatformPost.account_id,
                    order_by=PlatformPost.publish_time.desc(),
                )
                .label("rn"),
            )
            .filter(PlatformPost.account_id.in_(account_ids))
            .subquery()
        )
        post_rows = (
            db.query(numbered.c.account_id, numbered.c.post_id)
            .filter(numbered.c.rn <= 50)
            .all()
        )
        post_ids: list[int] = []
        for account_id, post_id in post_rows:
            posts_by_account.setdefault(account_id, []).append(post_id)
            post_ids.append(post_id)
        if post_ids:
            for row_stat in (
                db.query(PlatformPostStat)
                .filter(PlatformPostStat.post_id.in_(post_ids))
                .distinct(PlatformPostStat.post_id)
                .order_by(PlatformPostStat.post_id, PlatformPostStat.stat_date.desc())
                .all()
            ):
                stat_by_post.setdefault(row_stat.post_id, row_stat)  # DESC 序首个即最新

    out = []
    for c in creators:
        totals = {"followers": 0, "posts": 0, "plays": 0, "likes": 0, "favorites": 0, "comments": 0}
        account_info = []
        for a in accounts_by_creator.get(c.id, []):
            snap = snap_by_account.get(a.id)
            post_id_list = posts_by_account.get(a.id, [])
            stats = [stat_by_post[pid] for pid in post_id_list if pid in stat_by_post]
            followers = snap.followers if snap else 0
            plays_list = [s.plays for s in stats]
            med_plays = sorted(plays_list)[len(plays_list) // 2] if plays_list else 0
            hot_count = sum(1 for s in stats if s.plays >= 100000)
            totals["followers"] += followers
            totals["posts"] += len(stats) or len(post_id_list)
            totals["plays"] += sum(plays_list)
            totals["likes"] += sum(s.likes for s in stats)
            totals["favorites"] += sum(s.favorites for s in stats)
            totals["comments"] += sum(s.comments for s in stats)
            account_info.append(
                {
                    "platform": a.platform,
                    "nickname": snap.nickname if snap else a.nickname,
                    "followers": followers,
                    "posts": len(post_id_list),
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


def _rename_media_after_bind(db: Session, video: Video) -> None:
    """绑定平台后，把已存在的本地视频/封面补成「平台-主标题-视频/封面」。"""
    try:
        from ..services.media_naming import media_stem, rename_to
        import json as _json

        plats = _json.loads(video.platforms or "[]") if isinstance(video.platforms, str) else (video.platforms or [])
        plat = plats[0] if plats else ""
        if not plat or not video.title:
            return
        from ..config import get_settings as _gs

        settings = _gs()
        if video.filename and not video.filename.startswith("__cloud__"):
            old = settings.videos_dir / video.filename
            if old.exists():
                video.filename = rename_to(old, media_stem(plat, video.title, "视频"))
        if video.cover_path and not video.cover_path.startswith("avatar_"):
            old = settings.covers_dir / video.cover_path
            if old.exists():
                video.cover_path = rename_to(old, media_stem(plat, video.title, "封面"))
        db.commit()
    except Exception:  # noqa: BLE001 改名失败不影响绑定
        db.rollback()

