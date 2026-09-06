"""平台数据同步编排（M13，R-027/R-029）与选题池评论采集（R-028）。

- 预算护栏：每日请求预算（默认 2000，Kv 可覆盖），超限抛 BudgetExceeded，由任务层停止并通知。
- 封面：真实 URL 下载到本地 covers/；mock/无 URL 时生成占位 SVG（保证素材卡片有图）。
- 视频：一律不下载（D-027）。
"""

from __future__ import annotations

import json
from ..core.timeutil import now as _app_now

from sqlalchemy import text
from sqlalchemy.orm import Session

from ..core.pipeline import today_key
from ..models.hot_topic import TopicIdea
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
from .platform.budget import BudgetExceeded, _charge, get_budget, set_budget  # noqa: F401
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


def sync_post_comments(db: Session, post: PlatformPost, *, limit: int = 50, client: DataSource | None = None, account=None, charge: bool = True) -> dict:
    """拉取单帖评论并入库（点赞 Top limit；R-067）。charge=True 时计一次预算。"""
    client = client or make_source(post.platform)
    comments = client.fetch_comments(
        post.platform, post.platform_post_id, max(1, int(limit)), account, raw=_raw_of(post)
    )
    if charge:
        _charge(db)
    return _upsert_comments(db, post, comments, limit=limit)


def _collect_comments(db: Session, account: CreatorAccount, client: DataSource, posts: list[PlatformPost], per_post: int = 20) -> int:
    """抓取评论区进选题池（R-028）：评论入库（含点赞）+ 选题池去重新增。"""
    added = 0
    date_key = today_key()
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
        for c in comments:
            text = (c.text or "").strip()
            if not text or len(text) < 4:
                continue
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
                        platform=account.platform,
                        title=text,
                        detail=f"来自{account.nickname or account.platform}作品《{(post.title or '')[:40]}》的评论",
                        post_id=post.id,
                        post_title=post.title,
                        creator_id=account.creator_id,
                        snapshot_date=date_key,
                        likes=likes,
                    )
                )
                added += 1
            elif likes > int(exists.likes or 0):
                exists.likes = likes
    db.commit()
    return added


def _log_job(db: Session, job_type: str, scope: str, *, creator_id=None, account_id=None, post_id=None) -> SyncJob:
    job = SyncJob(job_type=job_type, scope=scope, creator_id=creator_id, account_id=account_id, post_id=post_id)
    db.add(job)
    db.commit()
    db.refresh(job)
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


def sync_account(db: Session, account: CreatorAccount, *, scope: str = "daily", top_n: int = 20, with_comments: bool = False, job_id: int | None = None) -> dict:
    """同步单个账号：主页快照 + 作品列表 + 指标；scope=initial 拉更多作品。

    job_id（R-070）：传入 run_sync 的 SyncJob id 时，实时累加进度（作品数 + 阶段说明）。
    """
    if not account.enabled:
        return {"account_id": account.id, "skipped": "disabled"}
    if not account.platform_user_id:
        raise ValueError(f"账号 {account.nickname or account.id} 未配置平台用户 ID（先解析主页链接）")
    label = _PLATFORM_LABEL.get(account.platform, account.platform)
    client = make_source(account.platform)
    account.sync_status = "running"
    db.commit()
    stats: dict = {"posts": 0, "comments": 0}
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
        except BudgetExceeded:
            raise
        except Exception:  # noqa: BLE001
            db.rollback()
    if with_comments:
        # R-072：每次同步对最近 10 条作品的评论 Top50 都尝试进池（按天去重）；完整评论照常入库
        targets = synced[:10]
        if targets:
            _job_progress(db, job_id, note=f"{label}：拉取评论…")
            stats["comments"] = _collect_comments(db, account, client, targets, per_post=50)
    if account.platform == "bilibili":
        # B站列表不含赞/藏/评，全量时逐条详情太重；这里每轮补全最多 BACKFILL 条
        stats["backfilled"] = _backfill_bili_stats(db, account, client, job_id=job_id)
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


def run_sync(db: Session, *, scope: str = "daily", account_id: int | None = None, creator_id: int | None = None, top_n: int | None = None) -> dict:
    """手动/定时同步入口：
    - scope=daily：当前主博主全部启用账号 top20（R-070 由前10条改为前20条）+ 评论选题采集
    - scope=initial：指定主博主（或当前）全部账号首次全量
    - scope=weekly：对标账号周同步
    """
    owner = None
    if account_id:
        acc = db.get(CreatorAccount, account_id)
        if acc is None:
            raise ValueError("账号不存在")
        owner = db.get(Creator, acc.creator_id)
        accounts = [acc]
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
        job = _log_job(db, "initial" if scope == "initial" else "daily", scope, creator_id=owner.id)

    try:
        per_owner = int(top_n if top_n is not None else (0 if scope == "initial" else (3 if scope == "weekly" else 20)))
        assert owner is not None
        with_comments = True  # 前20条/每周/全量都会按新增作品把评论入库（本地查询）

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
                st = sync_account(s, acc, scope=scope, top_n=_limit_for(acc), with_comments=with_comments, job_id=job.id)
                acc = s.get(CreatorAccount, acc_id)
                if acc is not None:
                    acc.sync_status = "done"
                    acc.last_sync_at = _app_now()
                    s.commit()
                return {"account_id": acc_id, "platform": plat, **st}
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
        # 跨平台同作品自动合并（同创作者 + 规范化标题相同）
        from .works_service import auto_merge_creator

        try:
            auto_merge_creator(db, owner.id)
        except Exception:  # noqa: BLE001 合并失败不影响同步主体
            db.rollback()
        msg = f"同步 {len(results)} 个账号，更新作品 {total_posts}，采集评论 {total_comments}"
        fails = [f"{r.get('platform')}({str(r.get('error'))[:60]})" for r in results if r.get("error")]
        if fails:
            msg += "；失败账号：" + "、".join(fails) + "（可单独重试该账号）"
        _finish_job(db, job, msg, {"accounts": results, "posts": total_posts, "comments": total_comments, "failed": len(fails)})
        return {"job_id": job.id, "message": msg, "accounts": results}
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
    cres = {"added": 0, "updated": 0}
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
