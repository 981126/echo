"""平台数据同步编排（M13，R-027/R-029）与选题池评论采集（R-028）。

- 预算护栏：每日请求预算（默认 2000，Kv 可覆盖），超限抛 BudgetExceeded，由任务层停止并通知。
- 封面：真实 URL 下载到本地 covers/；mock/无 URL 时生成占位 SVG（保证素材卡片有图）。
- 视频：一律不下载（D-027）。
"""

from __future__ import annotations

import json
import threading
from ..core.timeutil import now as _app_now

from sqlalchemy import text
from sqlalchemy.orm import Session

from ..config import get_settings
from ..core.pipeline import today_key
from ..models.hot_topic import TopicIdea
from ..models.task import BackgroundTask
from ..models.platform import (
    Creator,
    CreatorAccount,
    CreatorAccountSnapshot,
    PlatformPost,
    PlatformPostComment,
    PlatformPostStat,
    SyncJob,
)
from .platform_assets import _cover_path_for, _ensure_account_avatar
from .platform.budget import BudgetExceeded, _charge, ensure_budget, get_budget, set_budget  # noqa: F401
from .events import publish
from .creator_service import get_current_creator
from .platform.base import CommentData, DataSource, make_source

_PLATFORM_LABEL = {"douyin": "抖音", "xiaohongshu": "小红书", "bilibili": "B站"}


def _job_progress(db: Session, job_id: int | None, *, done: int = 0, total: int = 0, note: str | None = None) -> None:
    """R-070：累加写同步任务进度（done/total 原子累加），进度更新失败不影响同步主体。"""
    if not job_id:
        return
    try:
        if note is None:
            db.execute(
                text("UPDATE sync_jobs SET progress_done = progress_done + :d, progress_total = progress_total + :t WHERE id = :id"),
                {"d": max(0, int(done)), "t": max(0, int(total)), "id": job_id},
            )
        else:
            db.execute(
                text("UPDATE sync_jobs SET progress_done = progress_done + :d, progress_total = progress_total + :t, progress_note = :n WHERE id = :id"),
                {"d": max(0, int(done)), "t": max(0, int(total)), "n": (note or "")[:200], "id": job_id},
            )
        db.commit()
        row = db.query(SyncJob).filter(SyncJob.id == job_id).first()
        if row is not None:
            _publish_job(db, row)
    except Exception:  # noqa: BLE001
        db.rollback()


def _upsert_profile_snapshot(db: Session, account: CreatorAccount, client: DataSource) -> None:
    if not account.platform_user_id:
        return
    profile = client.fetch_profile(account.platform, account.platform_user_id, account)
    _charge(db)
    row = (
        db.query(CreatorAccountSnapshot)
        .filter(
            CreatorAccountSnapshot.account_id == account.id,
            CreatorAccountSnapshot.snapshot_date == today_key(),
        )
        .first()
    )
    if row is None:
        row = CreatorAccountSnapshot(
            account_id=account.id,
            snapshot_date=today_key(),
            nickname=profile.nickname,
            followers=profile.followers,
            likes_total=profile.likes_total,
            posts_total=profile.posts_total,
            following=profile.following,
            raw=json.dumps(profile.raw, ensure_ascii=False),
        )
        db.add(row)
    else:
        row.nickname = profile.nickname or row.nickname
        row.followers = profile.followers
        row.likes_total = profile.likes_total
        row.posts_total = profile.posts_total
        row.following = profile.following
        row.raw = json.dumps(profile.raw, ensure_ascii=False)
    if profile.nickname:
        account.nickname = profile.nickname
    _ensure_account_avatar(db, account, profile)
    db.commit()


def _ensure_post(db: Session, account: CreatorAccount, post, client: DataSource) -> PlatformPost:
    row = (
        db.query(PlatformPost)
        .filter(
            PlatformPost.platform == account.platform,
            PlatformPost.platform_post_id == post.platform_post_id,
        )
        .first()
    )
    if row is None:
        row = PlatformPost(
            account_id=account.id,
            platform=account.platform,
            platform_post_id=post.platform_post_id,
            title=post.title,
            desc=post.desc,
            cover_url=post.cover_url,
            video_url=post.video_url,
            publish_time=post.publish_time,
            raw=json.dumps(post.raw, ensure_ascii=False),
        )
        db.add(row)
        db.flush()
    else:
        row.title = post.title or row.title
        row.desc = post.desc or row.desc
        row.cover_url = post.cover_url or row.cover_url
        row.publish_time = post.publish_time or row.publish_time
        if post.raw:
            row.raw = json.dumps(post.raw, ensure_ascii=False)
    if post.tags:
        row.tags = json.dumps(list(dict.fromkeys(post.tags))[:20], ensure_ascii=False)
    if not row.cover_path:
        row.cover_path = _cover_path_for(
            db, account.platform, post.platform_post_id, post.title, post.cover_url
        )
    # 单条统计：列表自带统计则不额外请求（省额度）；否则拉单作品详情
    if post.stats:
        _write_stat(db, row, post.stats)
    else:
        try:
            stats = client.fetch_post_stats(account.platform, post.platform_post_id, account)
            _charge(db)
            _write_stat(db, row, stats)
        except BudgetExceeded:
            raise
        except Exception:  # noqa: BLE001 单条失败不中断
            db.rollback()
    db.commit()
    return row


def _write_stat(db: Session, post: PlatformPost, stats: dict) -> None:
    extra = stats.get("extra") or {}
    row = (
        db.query(PlatformPostStat)
        .filter(PlatformPostStat.post_id == post.id, PlatformPostStat.stat_date == today_key())
        .first()
    )
    data = {
        "plays": int(stats.get("plays") or 0),
        "likes": int(stats.get("likes") or 0),
        "favorites": int(stats.get("favorites") or 0),
        "shares": int(stats.get("shares") or 0),
        "comments": int(stats.get("comments") or 0),
        "extra": json.dumps(extra if isinstance(extra, dict) else {}, ensure_ascii=False),
    }
    if row is None:
        row = PlatformPostStat(post_id=post.id, stat_date=today_key(), source="tikhub", **data)
        db.add(row)
    else:
        for k, v in data.items():
            setattr(row, k, v)
    db.commit()


def _raw_of(post) -> dict:
    """平台帖 raw JSON 安全解析。"""
    try:
        return json.loads(post.raw or "{}") if isinstance(post.raw, str) else (post.raw or {})
    except json.JSONDecodeError:
        return {}


def _norm_comment_items(items) -> list[CommentData]:
    """把数据源返回的评论归一化为 CommentData（兼容 str / dict / CommentData）。"""
    out: list[CommentData] = []
    for it in items or []:
        if isinstance(it, CommentData):
            if (it.text or "").strip():
                out.append(it)
        elif isinstance(it, str):
            t = it.strip()
            if t:
                out.append(CommentData(text=t))
        elif isinstance(it, dict):
            t = str(it.get("text") or it.get("content") or "").strip()
            if t:
                out.append(
                    CommentData(
                        text=t,
                        likes=int(it.get("likes") or it.get("like_count") or it.get("digg_count") or 0),
                        user_nick=str(it.get("user_nick") or it.get("nickname") or it.get("user") or "")[:100],
                    )
                )
    return out


def _upsert_comments(db: Session, post: PlatformPost, comments: list[CommentData], limit: int = 50) -> dict:
    """按点赞降序保留 Top limit 条入库；同文本去重（点赞取更高值）。返回 {added, updated}。"""
    items = sorted(
        (c for c in _norm_comment_items(comments)),
        key=lambda c: (c.likes, c.text),
        reverse=True,
    )[: int(limit or 50)]
    added = 0
    updated = 0
    for c in items:
        text = c.text.strip()
        row = (
            db.query(PlatformPostComment)
            .filter(PlatformPostComment.post_id == post.id, PlatformPostComment.text == text)
            .first()
        )
        likes = int(c.likes or 0)
        nick = (c.user_nick or "")[:100]
        if row is None:
            db.add(
                PlatformPostComment(
                    post_id=post.id,
                    platform=post.platform,
                    text=text,
                    likes=likes,
                    user_nick=nick,
                )
            )
            added += 1
        else:
            if likes > int(row.likes or 0):
                row.likes = likes
                updated += 1
            if nick and nick != (row.user_nick or ""):
                row.user_nick = nick
                updated += 1
    db.commit()
    return {"added": added, "updated": updated}


def _pool_quota(db: Session, creator_id: int | None, date_key: str) -> int:
    """该博主今天还能进池几条（R-140 限量；0/负数表示不限量）。"""
    per_day = int(getattr(get_settings(), "pool_ideas_per_day", 0) or 0)
    if per_day <= 0:
        return 10**9
    used = (
        db.query(TopicIdea)
        .filter(
            TopicIdea.source == "comment",
            TopicIdea.snapshot_date == date_key,
            TopicIdea.creator_id == creator_id,
        )
        .count()
    )
    return max(0, per_day - used)


def pool_ideas_from_comments(
    db: Session,
    post: PlatformPost,
    comments: list,
    *,
    account: CreatorAccount | None = None,
    per_post: int | None = None,
) -> int:
    """把**已入库**的评论按限量写进灵感池（R-140）。

    这是「评论 → 选题池」的唯一实现：全量/每周同步（`_collect_comments`）与
    逐素材队列/单帖同步（`sync_post_comments`）都走这里，避免再出现
    「R-093 队列模式只入库不进池」这种一边有一边没有的回归。

    限量：单帖最多 `ECHO_POOL_IDEAS_PER_POST` 条（按点赞降序）、
    单博主每天最多 `ECHO_POOL_IDEAS_PER_DAY` 条；仍保留「标题 ≥4 字」与按天去重。
    返回本次新增条数。
    """
    if account is None and post.account_id:
        account = db.get(CreatorAccount, post.account_id)
    creator_id = account.creator_id if account is not None else None
    platform = (account.platform if account is not None else post.platform) or ""
    nickname = (account.nickname if account is not None else "") or platform
    limit_post = int(
        per_post if per_post is not None else getattr(get_settings(), "pool_ideas_per_post", 0) or 0
    )
    date_key = today_key()
    quota = _pool_quota(db, creator_id, date_key)
    if quota <= 0:
        return 0

    usable = [c for c in comments if len((c.text or "").strip()) >= 4]
    usable.sort(key=lambda c: int(c.likes or 0), reverse=True)
    if limit_post > 0:
        usable = usable[:limit_post]

    added = 0
    for c in usable:
        if added >= quota:
            break
        text = (c.text or "").strip()
        likes = int(c.likes or 0)
        exists = (
            db.query(TopicIdea)
            .filter(
                TopicIdea.source == "comment",
                TopicIdea.title == text,
                TopicIdea.snapshot_date == date_key,
            )
            .first()
        )
        if exists is None:
            db.add(
                TopicIdea(
                    source="comment",
                    platform=platform,
                    title=text,
                    detail=f"来自{nickname}作品《{(post.title or '')[:40]}》的评论",
                    post_id=post.id,
                    post_title=post.title,
                    creator_id=creator_id,
                    snapshot_date=date_key,
                    likes=likes,
                )
            )
            added += 1
        elif likes > int(exists.likes or 0):
            exists.likes = likes
    db.commit()
    return added


def sync_post_comments(
    db: Session,
    post: PlatformPost,
    *,
    limit: int = 50,
    client: DataSource | None = None,
    account=None,
    charge: bool = True,
    pool: bool = True,
) -> dict:
    """拉取单帖评论并入库（点赞 Top limit；R-067）。charge=True 时计一次预算。

    R-140：入库后同时按限量写灵感池（`pool=False` 可关闭），这样 daily 走
    「逐素材队列」时灵感池也会被持续填充。
    """
    client = client or make_source(post.platform)
    comments = _norm_comment_items(
        client.fetch_comments(
            post.platform, post.platform_post_id, max(1, int(limit)), account, raw=_raw_of(post)
        )
    )
    if charge:
        _charge(db)
    result = _upsert_comments(db, post, comments, limit=limit)
    if pool:
        result["pool_added"] = pool_ideas_from_comments(db, post, comments, account=account)
    return result


def _collect_comments(db: Session, account: CreatorAccount, client: DataSource, posts: list[PlatformPost], per_post: int = 20) -> int:
    """抓取评论区进选题池（R-028）：评论入库（含点赞）+ 选题池去重新增。

    R-140：进池逻辑统一走 `pool_ideas_from_comments`（限量），本函数只负责抓取与入库。
    """
    added = 0
    for post in posts[:]:
        try:
            comments = _norm_comment_items(
                client.fetch_comments(account.platform, post.platform_post_id, per_post, account, raw=_raw_of(post))
            )
            _charge(db)
        except BudgetExceeded:
            raise
        except Exception:  # noqa: BLE001 单个作品评论失败不中断
            continue
        try:
            _upsert_comments(db, post, comments, limit=per_post)
        except Exception:  # noqa: BLE001 入库失败不中断
            db.rollback()
            continue
        added += pool_ideas_from_comments(db, post, comments, account=account, per_post=per_post)
    return added


def _publish_job(db: Session, job: SyncJob) -> None:
    """R-091：同步任务进度/状态广播 sync.job（素材库据此让对应卡片进入同步动画）。"""
    try:
        publish(
            "sync.job",
            {
                "id": job.id,
                "job_type": job.job_type,
                "scope": job.scope,
                "creator_id": job.creator_id,
                "account_id": job.account_id,
                "post_id": job.post_id,
                "status": job.status,
                "progress_done": int(job.progress_done or 0),
                "progress_total": int(job.progress_total or 0),
                "progress_note": job.progress_note or "",
                "message": job.message or "",
            },
        )
    except Exception:  # noqa: BLE001 广播失败不影响同步
        pass


def _log_job(db: Session, job_type: str, scope: str, *, creator_id=None, account_id=None, post_id=None) -> SyncJob:
    job = SyncJob(job_type=job_type, scope=scope, creator_id=creator_id, account_id=account_id, post_id=post_id)
    db.add(job)
    db.commit()
    db.refresh(job)
    _publish_job(db, job)
    return job


def _finish_job(db: Session, job: SyncJob, message: str = "", stats: dict | None = None, failed: bool = False) -> None:
    job.status = "failed" if failed else "done"
    job.message = (message or "")[:2000]
    job.stats = json.dumps(stats or {}, ensure_ascii=False)
    job.finished_at = _app_now()
    if job.account_id:
        acc = db.get(CreatorAccount, job.account_id)
        if acc:
            acc.sync_status = "failed" if failed else "done"
            acc.sync_message = (message or "")[:500]
            if not failed:
                acc.last_sync_at = _app_now()
    db.commit()
    _publish_job(db, job)


def sync_account(
    db: Session,
    account: CreatorAccount,
    *,
    scope: str = "daily",
    top_n: int = 20,
    with_comments: bool = False,
    job_id: int | None = None,
    queue_rows: bool = False,
) -> dict:
    """同步单个账号：主页快照 + 作品列表 + 指标；scope=initial 拉更多作品。

    job_id（R-070）：传入 run_sync 的 SyncJob id 时，实时累加进度（作品数 + 阶段说明）。
    queue_rows（R-093）：分页发现已存在的作品时，立即注册 card_sync 队列任务（素材库卡片排队/动画）。
    """
    if not account.enabled:
        return {"account_id": account.id, "skipped": "disabled"}
    if not account.platform_user_id:
        raise ValueError(f"账号 {account.nickname or account.id} 未配置平台用户 ID（先解析主页链接）")
    ensure_budget(db)  # R-135：预算预检，避免"先发请求、后计费"
    label = _PLATFORM_LABEL.get(account.platform, account.platform)
    client = make_source(account.platform)
    account.sync_status = "running"
    db.commit()
    stats: dict = {"posts": 0, "comments": 0}
    queued: list[tuple[int, int]] = []  # (post_id, task_id)
    _job_progress(db, job_id, note=f"{label}：拉取主页与作品列表…")
    _upsert_profile_snapshot(db, account, client)
    posts_data = client.fetch_user_posts(account.platform, account.platform_user_id, top_n, account=account)
    _charge(db)
    if posts_data:
        _job_progress(db, job_id, total=len(posts_data), note=f"{label}：拉取到 {len(posts_data)} 条作品")
    synced: list[PlatformPost] = []
    new_posts: list[PlatformPost] = []
    total = len(posts_data)
    for i, pd in enumerate(posts_data, start=1):
        if not pd.platform_post_id:
            continue
        existed = (
            db.query(PlatformPost)
            .filter(
                PlatformPost.platform == account.platform,
                PlatformPost.platform_post_id == pd.platform_post_id,
            )
            .first()
        )
        try:
            post = _ensure_post(db, account, pd, client)
            synced.append(post)
            if existed is None:
                new_posts.append(post)
            stats["posts"] += 1
            _job_progress(db, job_id, done=1, note=f"{label}：已同步 {i}/{total} 条")
            if queue_rows:
                qrow = BackgroundTask(
                    kind="card_sync",
                    payload=json.dumps({"post_id": post.id, "job_id": job_id}, ensure_ascii=False),
                )
                db.add(qrow)
                db.commit()
                db.refresh(qrow)
                qrow.status = "running"
                qrow.progress = 4
                qrow.note = "排队中…"
                db.commit()
                publish("task.update", {"id": qrow.id, "status": "running", "progress": 4, "note": "排队中…", "payload": {"post_id": post.id}})
                queued.append((post.id, qrow.id))
        except BudgetExceeded:
            raise
        except Exception:  # noqa: BLE001
            db.rollback()
    if with_comments:
        # R-072：每次同步对最近 10 条作品的评论 Top50 都尝试进池（按天去重）；完整评论照常入库
        targets = synced[:10]
        if targets:
            _job_progress(db, job_id, note=f"{label}：拉取评论…")
            # 非队列路径下 _collect_comments 返回的就是「进池条数」（R-140 起走统一限量实现）
            stats["comments"] = _collect_comments(db, account, client, targets, per_post=50)
            stats["pool"] = stats["comments"]
    if account.platform == "bilibili":
        # B站列表不含赞/藏/评，全量时逐条详情太重；这里每轮补全最多 BACKFILL 条
        stats["backfilled"] = _backfill_bili_stats(db, account, client, job_id=job_id)
    if queue_rows:
        stats["queue"] = queued
        _job_progress(db, job_id, note=f"{label}：完成，{len(queued)} 条进入素材队列")
    else:
        _job_progress(db, job_id, note=f"{label}：完成")
    return stats


def _backfill_bili_stats(db: Session, account: CreatorAccount, client: DataSource, limit: int = 150, job_id: int | None = None) -> int:
    """B站：给“最新指标里 likes=0”的作品拉单条详情补全赞/藏/评（每轮限量，重复同步会补完）。

    job_id（R-070）：补全过程逐条累加进度。
    """
    from ..models.platform import PlatformPostStat

    posts = (
        db.query(PlatformPost)
        .filter(PlatformPost.account_id == account.id, PlatformPost.platform == "bilibili")
        .order_by(PlatformPost.id.desc())
        .all()
    )
    missing = []
    for post in posts:
        st = (
            db.query(PlatformPostStat)
            .filter(PlatformPostStat.post_id == post.id)
            .order_by(PlatformPostStat.stat_date.desc())
            .first()
        )
        if st is None or st.likes == 0:
            missing.append(post)
        if len(missing) >= limit:
            break
    done = 0
    total = len(missing)
    _job_progress(db, job_id, total=total, note=f"B站：补全 {len(missing)} 条缺失指标…")
    for i, post in enumerate(missing, start=1):
        try:
            stats = client.fetch_post_stats("bilibili", post.platform_post_id)
            _charge(db)
            _write_stat(db, post, stats)
            done += 1
            _job_progress(db, job_id, done=1, note=f"B站：补全中 {i}/{total}")
        except BudgetExceeded:
            raise
        except Exception:  # noqa: BLE001
            db.rollback()
    db.commit()
    return done


def run_sync(
    db: Session,
    *,
    scope: str = "daily",
    account_id: int | None = None,
    creator_id: int | None = None,
    top_n: int | None = None,
    with_media: bool = False,
    job: SyncJob | None = None,
) -> dict:
    """手动/定时同步入口：
    - scope=daily：当前主博主全部启用账号 top15（R-085 定 10，R-086 调为 15）+ 评论选题采集；
      with_media=True 时同步后对前 N 条做视频下载+自动转写（R-085）
    - scope=initial：指定主博主（或当前）全部账号首次全量
    - scope=weekly：对标账号周同步

    job（R-162）：队列编排时传入预置的 SyncJob 复用（前端在排队阶段就能看到该博主动画）；
    缺省时行为不变（内部 `_log_job` 新建）。
    """
    owner = None
    if account_id:
        acc = db.get(CreatorAccount, account_id)
        if acc is None:
            raise ValueError("账号不存在")
        owner = db.get(Creator, acc.creator_id)
        accounts = [acc]
        if job is None:
            job = _log_job(db, "manual" if scope != "weekly" else "weekly", scope, creator_id=owner.id if owner else None, account_id=acc.id)
    else:
        if creator_id:
            owner = db.get(Creator, creator_id)
        else:
            owner = get_current_creator(db)
        if owner is None:
            raise ValueError("请先创建并切换到一个主博主")
        accounts = list(
            db.query(CreatorAccount)
            .filter(CreatorAccount.creator_id == owner.id, CreatorAccount.enabled.is_(True))
            .all()
        )
        # 小红书优先（快），再抖音，最后 B站（量大/易受限）
        _order = {"xiaohongshu": 0, "douyin": 1, "bilibili": 2}
        accounts.sort(key=lambda a: _order.get(a.platform, 9))
        if job is None:
            job = _log_job(db, "initial" if scope == "initial" else "daily", scope, creator_id=owner.id)

    try:
        per_owner = int(top_n if top_n is not None else (0 if scope == "initial" else (3 if scope == "weekly" else 15)))
        assert owner is not None
        # R-093：daily 带媒体时改“逐素材队列”（发现即入队+素材库动画），评论也由队列逐条采集
        queue_mode = bool(with_media and scope == "daily")
        with_comments = not queue_mode

        def _limit_for(acc) -> int:
            if scope == "weekly":
                return 3
            return per_owner

        def _sync_one_acc(acc_id: int) -> dict:
            from sqlalchemy.orm import sessionmaker

            s = sessionmaker(bind=db.get_bind(), autoflush=False)()
            try:
                acc = s.get(CreatorAccount, acc_id)
                if acc is None:
                    return {"account_id": acc_id, "error": "账号不存在"}
                plat = acc.platform
                acc.sync_status = "running"
                s.commit()
                st = sync_account(s, acc, scope=scope, top_n=_limit_for(acc), with_comments=with_comments, job_id=job.id, queue_rows=queue_mode)
                acc = s.get(CreatorAccount, acc_id)
                if acc is not None:
                    acc.sync_status = "done"
                    acc.last_sync_at = _app_now()
                    s.commit()
                return {"account_id": acc_id, "platform": plat, **st}
            except BudgetExceeded:
                # R-135：预算耗尽必须向上抛，否则被当作「单平台失败」吞掉 → 任务仍报「同步完成」
                s.rollback()
                acc = s.get(CreatorAccount, acc_id)
                if acc is not None:
                    acc.sync_status = "failed"
                    acc.sync_message = "今日 TikHub 请求预算已用完"
                    s.commit()
                raise
            except Exception as exc:  # noqa: BLE001 单平台失败不影响其它平台
                s.rollback()
                acc = s.get(CreatorAccount, acc_id)
                if acc is not None:
                    acc.sync_status = "failed"
                    acc.sync_message = str(exc)[:200]
                    s.commit()
                return {"account_id": acc_id, "platform": acc.platform if acc else "", "error": str(exc)[:200]}
            finally:
                s.close()

        # 多线程并发：三个平台同时同步（每个用独立会话），大幅提速
        from concurrent.futures import ThreadPoolExecutor

        results = []
        with ThreadPoolExecutor(max_workers=min(3, max(1, len(accounts)))) as ex:
            futures = {ex.submit(_sync_one_acc, acc.id): acc for acc in accounts}
            from concurrent.futures import as_completed

            for fut in as_completed(futures):
                results.append(fut.result())
        total_posts = sum(int(r.get("posts") or 0) for r in results)
        total_comments = sum(int(r.get("comments") or 0) for r in results)
        total_pool = sum(int(r.get("pool") or 0) for r in results)  # R-140：进灵感池条数
        # R-093：账号分页阶段注册的逐素材队列（post_id, task_id）
        queue_items: list[tuple[int, int]] = []
        if queue_mode:
            for r in results:
                for item in r.get("queue") or []:
                    if len(item) >= 2:
                        queue_items.append((int(item[0]), int(item[1])))
        # 跨平台同作品自动合并（同创作者 + 规范化标题相同）
        from .works_service import auto_merge_creator

        try:
            auto_merge_creator(db, owner.id)
        except Exception:  # noqa: BLE001 合并失败不影响同步主体
            db.rollback()
        # R-092：数据同步收尾给整体说明，避免显示“xx平台：完成”却被当作整体 99%
        try:
            _job_progress(db, job.id, note="数据同步完成，正在下载/转写视频…" if (with_media and scope == "daily") else "同步完成，正在汇总…")
        except Exception:  # noqa: BLE001
            db.rollback()
        # R-093：逐素材队列依次处理（每条：评论采集 → 缺视频下载/转写），素材库卡片全程显示状态
        media = {"downloaded": 0, "transcribed": 0, "skipped": 0, "errors": 0, "comments": 0, "pool": 0}
        if queue_mode:
            from .media_ensure import run_card_sync_queue  # 延迟导入避免循环

            media = run_card_sync_queue(db, queue_items, with_media=True)
            total_comments += int(media.get("comments") or 0)
            total_pool += int(media.get("pool") or 0)
        msg = f"同步 {len(results)} 个账号，更新作品 {total_posts}，采集评论 {total_comments}"
        if total_pool:
            msg += f"，灵感池新增 {total_pool}"
        if queue_mode and (media["downloaded"] or media["transcribed"] or media["errors"] or media["skipped"] or media.get("comments")):
            msg += f"；入队 {len(queue_items)} 条，下载视频 {media['downloaded']}，转写 {media['transcribed']}"
            if media["errors"]:
                msg += f"，素材失败/跳过 {media['errors'] + media['skipped']}"
        fails = [f"{r.get('platform')}({str(r.get('error'))[:60]})" for r in results if r.get("error")]
        if fails:
            msg += "；失败账号：" + "、".join(fails) + "（可单独重试该账号）"
        payload = {
            "accounts": results,
            "posts": total_posts,
            "comments": total_comments,
            "pool_ideas": total_pool,
            "failed": len(fails),
        }
        if with_media and scope == "daily":
            payload["media"] = media
        _finish_job(db, job, msg, payload)
        return {
            "job_id": job.id,
            "message": msg,
            "accounts": results,
            "posts": total_posts,
            "comments": total_comments,
            "pool_ideas": total_pool,
        }
    except BudgetExceeded as exc:
        _finish_job(db, job, str(exc), failed=True)
        raise
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        _finish_job(db, job, str(exc), failed=True)
        raise


def _sync_one_post(db: Session, post: PlatformPost) -> dict:
    """同步单条平台帖：最新指标 + 评论（点赞 Top50）入库。失败抛错。"""
    account = db.get(CreatorAccount, post.account_id)
    client = make_source(post.platform)
    stats = client.fetch_post_stats(post.platform, post.platform_post_id, account)
    _charge(db)
    _write_stat(db, post, stats)
    cres = {"added": 0, "updated": 0, "pool_added": 0}
    try:
        cres = sync_post_comments(db, post, limit=50, client=client, account=account, charge=True)
    except Exception:  # noqa: BLE001 评论失败不影响主同步
        db.rollback()
    return {
        "platform": post.platform,
        "post_id": post.id,
        "stats": stats,
        "comments_added": cres["added"],
        "comments_updated": cres["updated"],
        "pool_added": int(cres.get("pool_added") or 0),  # R-140：本次进灵感池条数
    }


def sync_single_post(db: Session, post_id: int) -> dict:
    """单条作品即时同步（云端作品"同步数据"按钮，R-067：指标 + 评论点赞 Top50）。"""
    post = db.get(PlatformPost, post_id)
    if post is None:
        raise ValueError("云端作品不存在")
    account = db.get(CreatorAccount, post.account_id)
    job = _log_job(db, "single", "post", creator_id=account.creator_id if account else None, account_id=post.account_id, post_id=post.id)
    try:
        res = _sync_one_post(db, post)
        stats = res["stats"]
        added = int(res["comments_added"])
        _finish_job(
            db, job,
            f"单条同步完成（评论新增 {added} 条）",
            {"post_id": post.id, "stats": stats, "comments_added": added, "comments_updated": res["comments_updated"]},
        )
        return {
            "job_id": job.id,
            "message": "单条同步完成",
            "platforms": [post.platform],
            "stats": stats,
            "comments_added": added,
            "comments_updated": res["comments_updated"],
        }
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        _finish_job(db, job, str(exc), failed=True)
        raise


def sync_work_posts(db: Session, work_id: int) -> dict:
    """云端合并作品卡「同步数据」（R-067）：遍历 work 下全部平台帖同步指标+评论。

    修复：之前卡片只同步 cloudPosts[0]（第一个平台）；现合并作品全部平台帖逐个同步，
    单平台失败不中断其它平台。
    """
    from ..models.work import Work

    work = db.get(Work, work_id)
    if work is None:
        raise ValueError("云端合并作品不存在")
    posts = db.query(PlatformPost).filter(PlatformPost.work_id == work_id).all()
    if not posts:
        raise ValueError("该合并作品下没有平台帖子")
    job = _log_job(db, "single", "work", creator_id=work.creator_id)
    results: list[dict] = []
    for post in posts:
        try:
            results.append(_sync_one_post(db, post))
        except Exception as exc:  # noqa: BLE001 单平台失败不影响其它平台
            db.rollback()
            results.append({"platform": post.platform, "post_id": post.id, "error": str(exc)[:300]})
    totals = {"plays": 0, "likes": 0, "favorites": 0, "comments": 0, "shares": 0}
    for r in results:
        st = r.get("stats") or {}
        for field in totals:
            totals[field] += int(st.get(field) or 0)
    synced = [r["platform"] for r in results if r.get("platform") and "error" not in r]
    added = sum(int(r.get("comments_added") or 0) for r in results)
    updated = sum(int(r.get("comments_updated") or 0) for r in results)
    fails = [f"{r.get('platform')}({str(r.get('error'))[:80]})" for r in results if r.get("error")]
    msg = f"同步完成（{len(synced)} 个平台，评论新增 {added} 条）"
    if fails:
        msg += "；失败：" + "、".join(fails)
    stats_payload = {
        "platforms": synced,
        "posts": results,
        "stats": totals,
        "comments_added": added,
        "comments_updated": updated,
    }
    if not synced:
        _finish_job(db, job, msg, stats_payload, failed=True)
        raise ValueError(msg)
    _finish_job(db, job, msg, stats_payload)
    return {
        "job_id": job.id,
        "message": msg,
        "platforms": synced,
        "stats": totals,
        "comments_added": added,
        "comments_updated": updated,
    }



def _bound_platform_posts(db: Session, video) -> list[PlatformPost]:
    """本地素材绑定的平台作品：local_video_id / work 聚合 / platform_post_id 三路汇总去重。"""
    posts: dict[int, PlatformPost] = {}
    for bound in db.query(PlatformPost).filter(PlatformPost.local_video_id == video.id).all():
        posts[bound.id] = bound
    if video.work_id:
        for bound in db.query(PlatformPost).filter(PlatformPost.work_id == video.work_id).all():
            posts[bound.id] = bound
    key = (video.platform_post_id or "").strip()
    if key and ":" in key:
        platform, ext = key.split(":", 1)
        found = (
            db.query(PlatformPost)
            .filter(PlatformPost.platform == platform, PlatformPost.platform_post_id == ext)
            .first()
        )
        if found is not None:
            posts[found.id] = found
    return list(posts.values())


def sync_local_video_metrics(db: Session, video) -> dict:
    """本地素材的"同步数据"（R-067）：同步其绑定的各平台最新数据 + 每平台评论点赞 Top50。

    一个本地素材可绑定抖音/B站/小红书多条作品，逐个拉取最新数据写入
    平台作品表与指标快照（当天多平台聚合），供看板/复盘使用；单平台失败不中断其它平台。
    """
    posts = _bound_platform_posts(db, video)
    if not posts:
        raise ValueError("该素材未绑定平台作品（请先在编辑页填写平台链接并保存）")
    totals = {"plays": 0, "likes": 0, "favorites": 0, "comments": 0, "shares": 0}
    synced: list[str] = []
    errors: list[str] = []
    added = 0
    updated = 0
    for post in posts:
        account = db.get(CreatorAccount, post.account_id)
        client = make_source(post.platform)
        try:
            stats = client.fetch_post_stats(post.platform, post.platform_post_id, account)
            _charge(db)
        except Exception as exc:  # noqa: BLE001 单平台失败不中断
            errors.append(f"{post.platform}: {exc}")
            continue
        _write_stat(db, post, stats)
        for field in totals:
            totals[field] += int(stats.get(field) or 0)
        synced.append(post.platform)
        try:
            cres = sync_post_comments(db, post, limit=50, client=client, account=account, charge=True)
            added += int(cres["added"])
            updated += int(cres["updated"])
        except BudgetExceeded:
            raise
        except Exception:  # noqa: BLE001 评论失败不影响该平台指标
            db.rollback()
    # 同步写回本地指标快照（当天多平台聚合），供现有看板/复盘复用
    from ..models.metrics import MetricsSnapshot

    row = (
        db.query(MetricsSnapshot)
        .filter(
            MetricsSnapshot.video_id == video.id,
            MetricsSnapshot.snapshot_date == today_key(),
        )
        .first()
    )
    if row is None:
        db.add(
            MetricsSnapshot(
                video_id=video.id,
                snapshot_date=today_key(),
                plays=totals["plays"],
                likes=totals["likes"],
                favorites=totals["favorites"],
                comments=totals["comments"],
                source="tikhub",
            )
        )
    else:
        row.plays = totals["plays"]
        row.likes = totals["likes"]
        row.favorites = totals["favorites"]
        row.comments = totals["comments"]
        row.source = "tikhub"
    db.commit()
    if not synced and errors:
        raise ValueError("；".join(errors))
    msg = f"同步完成（{len(synced)} 个平台，评论新增 {added} 条）"
    if errors:
        msg += "；部分失败：" + "；".join(errors)
    return {
        "message": msg,
        "platforms": synced,
        "stats": totals,
        "errors": errors,
        "comments_added": added,
        "comments_updated": updated,
    }


def _running_sync_creator_ids(db: Session) -> set[int]:
    """R-160：正在排队/执行的 platform_sync 任务涉及的 creator_id 集合（用于跳过硬在跑的对标）。"""
    out: set[int] = set()
    for row in (
        db.query(BackgroundTask)
        .filter(BackgroundTask.kind == "platform_sync", BackgroundTask.status.in_(["pending", "running"]))
        .all()
    ):
        try:
            pl = json.loads(row.payload or "{}")
        except (TypeError, ValueError):
            continue
        cid = pl.get("creator_id")
        if cid is not None:
            try:
                out.add(int(cid))
            except (TypeError, ValueError):
                continue
    return out


def _enabled_account_count(db: Session, creator_id: int) -> int:
    from sqlalchemy import func

    return int(
        db.query(func.count(CreatorAccount.id))
        .filter(CreatorAccount.creator_id == creator_id, CreatorAccount.enabled.is_(True))
        .scalar()
        or 0
    )


def enqueue_all_top15_sync(db: Session, owner: Creator) -> dict:
    """R-162：把「当前主博主 + 其全部对标博主」的前15条同步任务写入队列（每个博主一条）。

    - 已有 platform_sync pending/running 的博主（含无启用账号者）跳过，汇总在 skipped；
    - 为每个入队博主**预置一条 running 的 SyncJob**（阶段「排队中…」），
      这样前端轮询 `/api/platform/jobs?status=running` 时所有博主卡片立即出现动画；
    - 返回 `{entries, skipped, total}`；entries 元素为 `{task_id, creator_id, job_id, name}`。
    """
    from .benchmark import benchmarks_of_owner

    creators = [owner] + benchmarks_of_owner(db, owner)
    running = _running_sync_creator_ids(db)
    skipped: list[str] = []
    entries: list[dict] = []
    for c in creators:
        name = c.name or f"博主#{c.id}"
        if c.id in running:
            skipped.append(f"{name}(已在运行)")
            continue
        if _enabled_account_count(db, c.id) == 0:
            skipped.append(f"{name}(无启用账号)")
            continue
        job = SyncJob(job_type="daily", scope="daily", creator_id=c.id, status="running", progress_note="排队中…")
        db.add(job)
        db.commit()
        db.refresh(job)
        _publish_job(db, job)
        row = BackgroundTask(
            kind="platform_sync",
            status="pending",
            payload=json.dumps({"scope": "daily", "creator_id": c.id, "queued": True}, ensure_ascii=False),
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        entries.append({"task_id": row.id, "creator_id": c.id, "job_id": job.id, "name": name})
    return {"entries": entries, "skipped": skipped, "total": len(creators)}


def _fail_creator_task(db: Session, task_id: int, error: str) -> None:
    """把某个博主队列任务置 failed 并广播（R-163）。"""
    try:
        row = db.get(BackgroundTask, task_id)
        if row is not None and row.status in ("pending", "running"):
            row.status = "failed"
            row.progress = row.progress or 0
            row.error = error[:500]
            row.note = error[:255]
            db.commit()
            publish(
                "task.update",
                {"id": task_id, "status": "failed", "progress": row.progress, "note": row.note, "error": row.error[:500]},
            )
    except Exception:  # noqa: BLE001 失败标记不影响其它博主
        db.rollback()


def run_all_top15_sync(db: Session, owner: Creator, entries: list[dict], update=None) -> dict:
    """R-163：并发消费者——线程池并行同步 entries 里的博主（daily 同口径：评论+缺视频下载+缺转写）。

    - 每个博主一个消费者（独立 Session），`claim_task` 原子认领其 pending 队列任务；
    - 每个博主复用 `enqueue_all_top15_sync` 预置的 SyncJob（前端动画连续）；
    - 单个博主失败不阻断其余；任一博主 `BudgetExceeded` 触发取消标记，未开始的博主标记失败；
    - 完成后只要有博主实际同步成功，自动触发一次「重新对标」（refetch=False，不重捞）。
    """
    from .benchmark import maybe_start_benchmark_rerun
    from .sync_pool import claim_task, gather, new_cancel, pool_size, session_factory

    total = max(1, len(entries))
    workers = pool_size("creator")
    cancel = new_cancel()
    counter = {"done": 0}
    lock = threading.Lock()
    new_session = session_factory(db)

    def _one(entry: dict) -> dict:
        try:
            task_id = int(entry.get("task_id") or 0)
            creator_id = int(entry.get("creator_id") or 0)
            job_id = int(entry.get("job_id") or 0)
        except (TypeError, ValueError):
            return {"status": "skip", "name": entry.get("name") or "", "creator_id": 0}
        name = entry.get("name") or f"博主#{creator_id}"
        s = new_session()
        try:
            if cancel.is_set():  # 预算已耗尽：不再开始新的博主
                _fail_creator_task(s, task_id, "已取消：同步预算不足")
                return {"status": "cancelled", "name": name, "creator_id": creator_id}
            task_row = s.get(BackgroundTask, task_id)
            job = s.get(SyncJob, job_id)
            if task_row is not None and task_row.status == "failed":  # 重启等导致的中断
                if job is not None and job.status == "running":
                    _finish_job(s, job, "任务中断", failed=True)
                return {"status": "failed", "name": name, "creator_id": creator_id, "reason": "任务中断"}
            if task_row is not None:
                claim_task(s, task_id)  # 原子认领（pending→running）
                task_row = s.get(BackgroundTask, task_id)
                if task_row is not None:
                    task_row.status = "running"
                    task_row.note = "同步中…"
                    s.commit()
                    publish("task.update", {"id": task_id, "status": "running", "progress": task_row.progress or 5, "note": "同步中…", "payload": {"creator_id": creator_id}})
            try:
                run_sync(s, scope="daily", creator_id=creator_id, with_media=True, job=job)
            except BudgetExceeded as exc:  # 预算耗尽：取消后续
                s.rollback()
                _fail_creator_task(s, task_id, str(exc))
                cancel.set()
                return {"status": "budget", "name": name, "creator_id": creator_id, "reason": str(exc)[:80]}
            except Exception as exc:  # noqa: BLE001 单个博主失败不阻断其余
                s.rollback()
                _fail_creator_task(s, task_id, str(exc))
                return {"status": "failed", "name": name, "creator_id": creator_id, "reason": str(exc)[:80]}
            if task_row is not None:
                task_row = s.get(BackgroundTask, task_id)
                if task_row is not None:
                    task_row.status = "done"
                    task_row.progress = 100
                    task_row.note = "完成"
                    s.commit()
                    publish("task.update", {"id": task_id, "status": "done", "progress": 100, "note": "完成", "payload": {"creator_id": creator_id}})
            return {"status": "done", "name": name, "creator_id": creator_id}
        finally:
            s.close()

    def _on_result(_entry: object, res: object) -> None:
        with lock:
            counter["done"] += 1
            n = counter["done"]
        if update:
            name = res.get("name") if isinstance(res, dict) else ""
            update(max(5, min(95, int(n / total * 100))), f"[{n}/{total}] {name}：同步完成")

    results = gather(_one, entries, workers=workers, on_result=_on_result)
    synced = sum(1 for _, r in results if isinstance(r, dict) and r.get("status") == "done")
    failed: list[str] = []
    for _, r in results:
        if not isinstance(r, dict):
            continue
        if r.get("status") in ("failed", "budget", "cancelled"):
            reason = r.get("reason") or ("已取消：预算不足" if r.get("status") == "cancelled" else "失败")
            failed.append(f"{r.get('name')}({reason})")
    rerun = "no_sync"
    if synced:
        rerun = maybe_start_benchmark_rerun(db, refetch=False)  # 同步完自动重新对标（不重捞）
    parts = [f"全量同步：共 {len(entries)} 个博主，已同步 {synced} 个（并发 {workers}）"]
    if failed:
        parts.append("失败：" + "、".join(failed))
    if synced:
        if isinstance(rerun, str) and rerun.startswith("started:"):
            parts.append("已自动触发「重新对标」")
        elif rerun == "already_running":
            parts.append("已有「重新对标」在跑，跳过自动触发")
    if update:
        update(100, "完成")
    return {
        "message": "；".join(parts),
        "creators": len(entries),
        "synced": synced,
        "failed": failed,
        "rerun": rerun,
    }


def all_top15_worker(db: Session, payload: dict, update=None) -> dict:
    """R-162 后台任务体：消费 `enqueue_all_top15_sync` 写入的博主同步队列。"""
    payload = payload or {}
    entries = payload.get("entries") or []
    owner = None
    oid = payload.get("owner_id")
    if oid:
        try:
            owner = db.get(Creator, int(oid))
        except (TypeError, ValueError):
            owner = None
    if owner is None:
        owner = get_current_creator(db)
    if owner is None:
        raise ValueError("请先创建并切换到主博主")
    return run_all_top15_sync(db, owner, entries, update=update)



def run_daily_sync_all(db: Session) -> dict:
    """R-109：每日定时两轮（06:00/17:00）统一同步——主博主 + 全部对标博主。

    主博主与对标博主同规格：每账号最新 15 条 + 下载视频 + 自动转写
    （已下载/已转写自动跳过，不重复花 ASR 钱）；同步完成后自动触发一次
    「重新对标」（refetch=False：不重复拉取 TikHub，只基于刚同步的数据重算
    前3+最新/补齐极个别缺转写）。
    """
    from .benchmark import benchmarks_of_owner, maybe_start_benchmark_rerun
    from .sync_pool import gather, pool_size, session_factory

    owner = get_current_creator(db)
    if owner is None:
        raise ValueError("请先创建并切换到主博主")
    benchmarks = benchmarks_of_owner(db, owner)
    # 主博主保持 creator_id=None（走「当前主博主」语义，与既有行为一致），对标显式指定
    creator_ids: list[int | None] = [None, *(bm.id for bm in benchmarks)]
    new_session = session_factory(db)

    def _sync_one(creator_id: int | None) -> dict:
        s = new_session()
        try:
            # 主博主与对标同规格（daily：15 条 + 评论 + 缺视频下载/转写，已下载/已转写跳过）
            return run_sync(s, scope="daily", creator_id=(None if creator_id is None else int(creator_id)), with_media=True)
        finally:
            s.close()

    # R-163：主博主 + 全部对标博主并发同步（每个博主独立 Session），全局 TikHub 令牌桶控速
    results = [r for _, r in gather(_sync_one, creator_ids, workers=pool_size("creator")) if isinstance(r, dict)]
    rerun = maybe_start_benchmark_rerun(db, refetch=False)  # 同步完自动重新对标（不重捞）
    accounts = [a for res in results for a in (res.get("accounts") or [])]
    posts = sum(int(r.get("posts") or 0) for r in results)
    comments = sum(int(r.get("comments") or 0) for r in results)
    pool_ideas = sum(int(r.get("pool_ideas") or 0) for r in results)  # R-140：进灵感池条数
    msg = (
        f"每日同步完成：主博主 + {len(benchmarks)} 个对标，共同步 {len(accounts)} 个账号，"
        f"更新作品 {posts}，采集评论 {comments}"
    )
    if pool_ideas:
        msg += f"，灵感池新增 {pool_ideas}"
    if isinstance(rerun, str) and rerun.startswith("started:"):
        msg += "；已自动触发「重新对标」"
    elif rerun == "already_running":
        msg += "；已有「重新对标」在跑，本轮跳过自动触发"
    return {
        "job_id": results[-1].get("job_id") if results else None,
        "message": msg,
        "accounts": accounts,
        "posts": posts,
        "comments": comments,
        "pool_ideas": pool_ideas,
        "rerun": rerun,
    }
