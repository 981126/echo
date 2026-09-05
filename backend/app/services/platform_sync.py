"""平台数据同步编排（M13，R-027/R-029）与选题池评论采集（R-028）。

- 预算护栏：每日请求预算（默认 2000，Kv 可覆盖），超限抛 BudgetExceeded，由任务层停止并通知。
- 封面：真实 URL 下载到本地 covers/；mock/无 URL 时生成占位 SVG（保证素材卡片有图）。
- 视频：一律不下载（D-027）。
"""

from __future__ import annotations

import html
import json
import uuid
from datetime import datetime
from pathlib import Path

import httpx
from sqlalchemy.orm import Session

from ..config import get_settings
from ..core.pipeline import today_key
from ..models.hot_topic import TopicIdea
from ..models.kv import Kv
from ..models.platform import (
    Creator,
    CreatorAccount,
    CreatorAccountSnapshot,
    PlatformPost,
    PlatformPostComment,
    PlatformPostStat,
    SyncJob,
)
from .creator_service import current_creator_id, get_current_creator
from .platform.tikhub import TikHubClient, make_client

BUDGET_KEY = "tikhub_budget_limit"


class BudgetExceeded(RuntimeError):
    pass


def get_budget(db: Session) -> dict:
    limit = get_settings().tikhub_daily_budget
    row = db.get(Kv, BUDGET_KEY)
    if row and str(row.value).isdigit():
        limit = int(row.value)
    key = today_key()
    used_row = db.get(Kv, f"tikhub_budget_used:{key}")
    used = int(used_row.value) if used_row and str(used_row.value).isdigit() else 0
    return {"limit": limit, "used": used, "remaining": max(0, limit - used), "date": key}


def set_budget(db: Session, limit: int) -> dict:
    limit = max(1, min(limit, 10_000_000))
    row = db.get(Kv, BUDGET_KEY)
    if row is None:
        row = Kv(key=BUDGET_KEY, value=str(limit))
        db.add(row)
    else:
        row.value = str(limit)
    db.commit()
    return get_budget(db)


def _charge(db: Session, count: int = 1) -> None:
    """计一次请求；超预算抛 BudgetExceeded。"""
    budget = get_budget(db)
    if budget["used"] + count > budget["limit"]:
        raise BudgetExceeded(
            f"今日 TikHub 请求预算已用完（{budget['used']}/{budget['limit']}），已停止本轮同步"
        )
    row = db.get(Kv, f"tikhub_budget_used:{budget['date']}")
    if row is None:
        row = Kv(key=f"tikhub_budget_used:{budget['date']}", value=str(budget["used"] + count))
        db.add(row)
    else:
        row.value = str(budget["used"] + count)
    db.commit()


def _img_ext(data: bytes) -> str | None:
    """按文件头识别图片真实格式；HEIC/未知格式返回 None（需转换或放弃）。"""
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return ".png"
    if data[:3] == b"\xff\xd8\xff":
        return ".jpg"
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return ".webp"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return ".gif"
    # HEIC/HEIF（苹果格式，浏览器不支持，需转 jpeg）
    if data[4:12] in (b"ftypheic", b"ftypheix", b"ftypmif1", b"ftypmsf1", b"ftyphevc"):
        return None
    return None


def _ensure_web_image(data: bytes) -> bytes | None:
    """把下载内容转成浏览器可渲染的图片（HEIC→JPEG），非图片返回 None。"""
    ext = _img_ext(data)
    if ext is not None:
        return data
    if data[4:12].startswith(b"ftyp"):
        return _heic_to_jpeg(data)
    return None


def _heic_to_jpeg(data: bytes) -> bytes | None:
    """macOS 用 sips 把 HEIC 转 JPEG；失败返回 None（走占位图）。"""
    import shutil
    import subprocess
    import tempfile

    if not shutil.which("sips"):
        return None
    try:
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "in.heic"
            dst = Path(tmp) / "out.jpg"
            src.write_bytes(data)
            proc = subprocess.run(
                ["sips", "-s", "format", "jpeg", "-s", "formatOptions", "85", str(src), "--out", str(dst)],
                capture_output=True,
                timeout=60,
            )
            if proc.returncode == 0 and dst.exists():
                return dst.read_bytes()
    except Exception:  # noqa: BLE001
        pass
    return None


def _cdn_headers(platform: str) -> dict:
    return {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36",
        "Referer": {"xiaohongshu": "https://www.xiaohongshu.com/", "douyin": "https://www.douyin.com/", "bilibili": "https://www.bilibili.com/"}.get(platform, ""),
    }


def _cover_path_for(db: Session, platform: str, platform_post_id: str, title: str, cover_url: str) -> str:
    """返回本地封面文件名（下载真实封面或生成占位 SVG）。"""
    settings = get_settings()
    settings.covers_dir.mkdir(parents=True, exist_ok=True)
    name = f"cloud_{uuid.uuid4().hex[:12]}"
    dest: Path
    if cover_url:
        try:
            resp = httpx.get(cover_url, timeout=8, headers=_cdn_headers(platform))
            if resp.status_code == 200 and resp.content:
                img = _ensure_web_image(resp.content)
                if img:
                    dest = settings.covers_dir / f"{name}.jpg"
                    dest.write_bytes(img)
                    return dest.name
        except Exception:  # noqa: BLE001  下载失败回退占位
            pass
    dest = settings.covers_dir / f"{name}.svg"
    label = {"douyin": "抖音", "xiaohongshu": "小红书", "bilibili": "B站"}.get(platform, platform)
    text = html.escape((title or "云端作品")[:26])
    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="480" height="270">'
        f'<rect width="480" height="270" fill="#f3ede4"/>'
        f'<text x="240" y="96" font-family="-apple-system,PingFang SC,sans-serif" font-size="26" fill="#a34f2c" text-anchor="middle">{label}</text>'
        f'<text x="240" y="150" font-family="-apple-system,PingFang SC,sans-serif" font-size="17" fill="#2b2823" text-anchor="middle">{text}</text>'
        f'</svg>'
    )
    dest.write_text(svg, encoding="utf-8")
    return dest.name


def _ensure_account_avatar(db: Session, account: CreatorAccount, profile) -> None:
    """自动同步头像：有远端 URL 则下载本地；没有就保持空（前端显示空圆框）。"""
    if account.avatar_path:
        return
    if not profile.avatar_url:
        return
    settings = get_settings()
    settings.covers_dir.mkdir(parents=True, exist_ok=True)
    name = f"avatar_{uuid.uuid4().hex[:12]}"
    try:
        resp = httpx.get(profile.avatar_url, timeout=8, headers=_cdn_headers(account.platform))
        if resp.status_code == 200 and resp.content:
            img = _ensure_web_image(resp.content)
            if img:
                dest = settings.covers_dir / f"{name}.jpg"
                dest.write_bytes(img)
                account.avatar_path = dest.name
                db.commit()
    except Exception:  # noqa: BLE001 下载失败保持空，前端显示空圆框
        pass


def _upsert_profile_snapshot(db: Session, account: CreatorAccount, client: TikHubClient) -> None:
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


def _ensure_post(db: Session, account: CreatorAccount, post, client: TikHubClient) -> PlatformPost:
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


def _collect_comments(db: Session, account: CreatorAccount, client: TikHubClient, posts: list[PlatformPost], per_post: int = 20) -> int:
    """抓取评论区进选题池（R-028）。"""
    added = 0
    date_key = today_key()
    for post in posts[:]:
        try:
            raw = {}
            try:
                raw = json.loads(post.raw or "{}") if isinstance(post.raw, str) else (post.raw or {})
            except json.JSONDecodeError:
                raw = {}
            comments = client.fetch_comments(account.platform, post.platform_post_id, per_post, account, raw=raw)
            _charge(db)
        except BudgetExceeded:
            raise
        except Exception:  # noqa: BLE001 单个作品评论失败不中断
            continue
        for text in comments:
            text = (text or "").strip()
            if not text or len(text) < 4:
                continue
            dup_c = (
                db.query(PlatformPostComment)
                .filter(PlatformPostComment.post_id == post.id, PlatformPostComment.text == text)
                .first()
            )
            if dup_c is None:
                db.add(PlatformPostComment(post_id=post.id, platform=account.platform, text=text))
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
                    )
                )
                added += 1
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
    job.finished_at = datetime.utcnow()
    if job.account_id:
        acc = db.get(CreatorAccount, job.account_id)
        if acc:
            acc.sync_status = "failed" if failed else "done"
            acc.sync_message = (message or "")[:500]
            if not failed:
                acc.last_sync_at = datetime.utcnow()
    db.commit()


def sync_account(db: Session, account: CreatorAccount, *, scope: str = "daily", top_n: int = 10, with_comments: bool = False) -> dict:
    """同步单个账号：主页快照 + 作品列表 + 指标；scope=initial 拉更多作品。"""
    if not account.enabled:
        return {"account_id": account.id, "skipped": "disabled"}
    if not account.platform_user_id:
        raise ValueError(f"账号 {account.nickname or account.id} 未配置平台用户 ID（先解析主页链接）")
    client = make_client()
    account.sync_status = "running"
    db.commit()
    stats: dict = {"posts": 0, "comments": 0}
    _upsert_profile_snapshot(db, account, client)
    posts_data = client.fetch_user_posts(account.platform, account.platform_user_id, top_n, account=account)
    _charge(db)
    synced: list[PlatformPost] = []
    new_posts: list[PlatformPost] = []
    for pd in posts_data:
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
        except BudgetExceeded:
            raise
        except Exception:  # noqa: BLE001
            db.rollback()
    if with_comments:
        # 增量：评论只抓新增作品；无新增时刷新最新 3 条（省额度）
        targets = (new_posts or synced)[:10] if new_posts else synced[:3]
        if targets:
            stats["comments"] = _collect_comments(db, account, client, targets)
    if account.platform == "bilibili":
        # B站列表不含赞/藏/评，全量时逐条详情太重；这里每轮补全最多 BACKFILL 条
        stats["backfilled"] = _backfill_bili_stats(db, account, client)
    return stats


def _backfill_bili_stats(db: Session, account: CreatorAccount, client: TikHubClient, limit: int = 150) -> int:
    """B站：给“最新指标里 likes=0”的作品拉单条详情补全赞/藏/评（每轮限量，重复同步会补完）。"""
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
    for post in missing:
        try:
            stats = client.fetch_post_stats("bilibili", post.platform_post_id)
            _charge(db)
            _write_stat(db, post, stats)
            done += 1
        except BudgetExceeded:
            raise
        except Exception:  # noqa: BLE001
            db.rollback()
    db.commit()
    return done


def run_sync(db: Session, *, scope: str = "daily", account_id: int | None = None, creator_id: int | None = None, top_n: int | None = None) -> dict:
    """手动/定时同步入口：
    - scope=daily：当前主博主全部启用账号 top10 + 评论选题采集
    - scope=initial：指定主博主（或当前）全部账号首次全量（主 50/对标 20）
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
        per_owner = int(top_n if top_n is not None else (0 if scope == "initial" else (3 if scope == "weekly" else 10)))
        assert owner is not None
        with_comments = True  # 前10条/每周/全量都会按新增作品把评论入库（本地查询）

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
                st = sync_account(s, acc, scope=scope, top_n=_limit_for(acc), with_comments=with_comments)
                acc = s.get(CreatorAccount, acc_id)
                if acc is not None:
                    acc.sync_status = "done"
                    acc.last_sync_at = datetime.utcnow()
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


def sync_single_post(db: Session, post_id: int) -> dict:
    """单条作品即时同步（素材/云端作品"同步数据"按钮）。"""
    post = db.get(PlatformPost, post_id)
    if post is None:
        raise ValueError("云端作品不存在")
    account = db.get(CreatorAccount, post.account_id)
    job = _log_job(db, "single", "post", creator_id=account.creator_id if account else None, account_id=post.account_id, post_id=post.id)
    try:
        client = make_client()
        stats = client.fetch_post_stats(post.platform, post.platform_post_id, account)
        _charge(db)
        _write_stat(db, post, stats)
        # 同步数据同时把评论入库（本地查询）
        added_comments = 0
        try:
            raw = {}
            try:
                raw = json.loads(post.raw or "{}") if isinstance(post.raw, str) else (post.raw or {})
            except json.JSONDecodeError:
                raw = {}
            texts = client.fetch_comments(post.platform, post.platform_post_id, 20, account, raw=raw)
            for c in texts:
                c = (c or "").strip()
                if not c:
                    continue
                dup = (
                    db.query(PlatformPostComment)
                    .filter(PlatformPostComment.post_id == post.id, PlatformPostComment.text == c)
                    .first()
                )
                if dup is None:
                    db.add(PlatformPostComment(post_id=post.id, platform=post.platform, text=c))
                    added_comments += 1
            db.commit()
        except Exception:  # noqa: BLE001 评论失败不影响主同步
            db.rollback()
        _finish_job(db, job, f"单条同步完成（新增评论 {added_comments}）", {"post_id": post.id, "stats": stats, "comments_added": added_comments})
        return {"job_id": job.id, "message": "单条同步完成", "stats": stats, "comments_added": added_comments}
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        _finish_job(db, job, str(exc), failed=True)
        raise


def daily_top_sync_job(db: Session) -> dict:
    """定时任务：每日两轮同步当前主博主 top10 + 评论选题采集（R-027/R-028）。"""
    return run_sync(db, scope="daily")


def sync_local_video_metrics(db: Session, video) -> dict:
    """本地素材（已绑定 platform_post_id）的"同步数据"按钮。"""
    key = (video.platform_post_id or "").strip()
    if not key or ":" not in key:
        raise ValueError("该素材未绑定平台作品（请在编辑里填发布链接）")
    platform, ext = key.split(":", 1)
    if not ext:
        raise ValueError("发布链接解析失败，请检查")
    client = make_client()
    stats = client.fetch_post_stats(platform, ext)
    _charge(db)
    # 写云端作品表（若有同名 post 则同步其快照）
    post = (
        db.query(PlatformPost)
        .filter(PlatformPost.platform == platform, PlatformPost.platform_post_id == ext)
        .first()
    )
    if post is None:
        account = None
        cid = current_creator_id(db)
        if cid:
            account = (
                db.query(CreatorAccount)
                .filter(CreatorAccount.creator_id == cid, CreatorAccount.platform == platform)
                .first()
            )
        if account is None:
            raise ValueError("未找到该平台的账号配置，无法写回云端作品表")
        post = PlatformPost(
            account_id=account.id,
            platform=platform,
            platform_post_id=ext,
            title=video.title,
            raw="{}",
        )
        db.add(post)
        db.flush()
        if not post.cover_path:
            post.cover_path = _cover_path_for(db, platform, ext, video.title, "")
        db.commit()
    _write_stat(db, post, stats)
    # 同步写回本地指标快照，供现有看板/复盘复用
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
                plays=int(stats.get("plays") or 0),
                likes=int(stats.get("likes") or 0),
                favorites=int(stats.get("favorites") or 0),
                comments=int(stats.get("comments") or 0),
                source="tikhub",
            )
        )
    else:
        row.plays = int(stats.get("plays") or 0)
        row.likes = int(stats.get("likes") or 0)
        row.favorites = int(stats.get("favorites") or 0)
        row.comments = int(stats.get("comments") or 0)
        row.source = "tikhub"
    db.commit()
    return {"message": "同步完成", "stats": stats}
