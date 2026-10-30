"""跨平台同作品合并服务（M13+）。

规则：同一创作者（主博主或某个对标各自独立）下的云端作品，
规范化标题相同 → 自动归为同一作品（work）；标题不同但内容同源 → 作者手动合并。
"""

from __future__ import annotations

import json
import re
import threading
import time

from fastapi import HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..core.platform_links import build_platform_page_url_from_data, parse_raw
from ..models.platform import Creator, CreatorAccount, PlatformPost, PlatformPostStat
from ..models.video import Video
from ..models.work import Work
from .text_tags import strip_hashtags

_SPACE_RE = re.compile(r"\\s+")
_TAG_RE = re.compile(r"[#＃][^\\s#＃，,。！？!?]*")
_PUNCT_RE = re.compile(r"[，。！？!?,.;:：、|\\[\\]()（）《》\"'“”…\\-—\\s]+")


def normalize_work_title(title: str) -> str:
    """规范化标题用于跨平台匹配：去话题/标点/空白、小写。"""
    t = _TAG_RE.sub(" ", title or "")
    t = _PUNCT_RE.sub("", t)
    t = _SPACE_RE.sub("", t)
    return t.strip().lower()


def recompute_video_platforms(db: Session, video: Video) -> None:
    """R-225：按素材绑定的平台帖（local_video_id 或 work 聚合）刷新 video.platforms。"""
    posts: list[PlatformPost] = []
    seen_ids: set[int] = set()
    for p in db.query(PlatformPost).filter(PlatformPost.local_video_id == video.id).all():
        if p.id not in seen_ids:
            posts.append(p)
            seen_ids.add(p.id)
    if video.work_id:
        for p in db.query(PlatformPost).filter(PlatformPost.work_id == video.work_id).all():
            if p.id not in seen_ids:
                posts.append(p)
                seen_ids.add(p.id)
    plats = sorted({p.platform for p in posts if p.platform})
    if plats:
        video.platforms = json.dumps(plats, ensure_ascii=False)


def latest_stats_map(db: Session, post_ids: list[int]) -> dict[int, PlatformPostStat]:
    """批量取每条作品的最新统计（stat_date 升序覆盖 → 保留最新），消除 N+1。"""
    out: dict[int, PlatformPostStat] = {}
    if not post_ids:
        return out
    for row in (
        db.query(PlatformPostStat)
        .filter(PlatformPostStat.post_id.in_(post_ids))
        .order_by(PlatformPostStat.stat_date)
        .all()
    ):
        out[row.post_id] = row
    return out


def _latest_stat(db: Session, post_id: int):
    return (
        db.query(PlatformPostStat)
        .filter(PlatformPostStat.post_id == post_id)
        .order_by(PlatformPostStat.stat_date.desc())
        .first()
    )


# ---------------------------------------------------------------------------
# S5（R-240）：卡片快照进程内缓存
#
# 素材库（library_service.build_cards）与博主管理页（works_service.list_works）每次
# 翻页/筛选都会全量重建 600~1900 行 → 这次加「数据版本键 + 20s TTL」双保险快照缓存。
# 版本键是几条 count/max 轻查询：同步写入（新帖/新指标/合并/删除）会立刻换版本；
# 原地编辑（标题/标签）等不改变聚合量的写由 20s TTL 兜底，不引入跨请求 Session 缓存。
# ---------------------------------------------------------------------------

_CARD_CACHE_TTL = 20.0
_CARD_CACHE_MAX = 20
_CARD_CACHE_LOCK = threading.Lock()
_CARD_CACHE: dict[tuple, tuple[float, list[dict]]] = {}
_WORKS_CACHE: dict[tuple, tuple[float, list[dict]]] = {}


def cards_version(db: Session, creator_id: int | None) -> tuple:
    """卡片快照的数据版本键（4 条便宜聚合，≤3ms）。

    `creator_id` 为空时按全量口径（与 `build_cards`/`list_works` 的「无当前博主」行为一致）。
    """
    if creator_id:
        posts_count, posts_max_id, posts_updated = (
            db.query(
                func.count(PlatformPost.id),
                func.max(PlatformPost.id),
                func.max(PlatformPost.updated_at),
            )
            .join(CreatorAccount, CreatorAccount.id == PlatformPost.account_id)
            .filter(CreatorAccount.creator_id == creator_id, CreatorAccount.enabled.is_(True))
            .one()
        )
        videos_count, videos_max_id, videos_created = (
            db.query(func.count(Video.id), func.max(Video.id), func.max(Video.created_at))
            .filter(Video.creator_id == creator_id)
            .one()
        )
        works_count, works_updated = (
            db.query(func.count(Work.id), func.max(Work.updated_at))
            .filter(Work.creator_id == creator_id)
            .one()
        )
    else:
        posts_count, posts_max_id, posts_updated = db.query(
            func.count(PlatformPost.id),
            func.max(PlatformPost.id),
            func.max(PlatformPost.updated_at),
        ).one()
        videos_count, videos_max_id, videos_created = db.query(
            func.count(Video.id), func.max(Video.id), func.max(Video.created_at)
        ).one()
        works_count, works_updated = db.query(
            func.count(Work.id), func.max(Work.updated_at)
        ).one()
    stats_count = int(db.query(func.count(PlatformPostStat.id)).scalar() or 0)
    return (
        creator_id or 0,
        int(posts_count or 0),
        int(posts_max_id or 0),
        posts_updated,
        int(videos_count or 0),
        int(videos_max_id or 0),
        videos_created,
        int(works_count or 0),
        works_updated,
        stats_count,
    )


def _cache_get(cache: dict[tuple, tuple[float, list[dict]]], key: tuple) -> list[dict] | None:
    """缓存命中返回**浅拷贝**（防调用方修改污染缓存）；过期/未命中返回 None。"""
    now = time.monotonic()
    with _CARD_CACHE_LOCK:
        hit = cache.get(key)
        if hit is None or hit[0] <= now:
            return None
        return [dict(item) for item in hit[1]]


def _cache_put(cache: dict[tuple, tuple[float, list[dict]]], key: tuple, items: list[dict]) -> None:
    """写入快照；条目上限 20，超限整体清空（与设计一致，单用户缓存不会持续增长）。"""
    with _CARD_CACHE_LOCK:
        if len(cache) >= _CARD_CACHE_MAX:
            cache.clear()
        cache[key] = (time.monotonic() + _CARD_CACHE_TTL, items)


def post_item(db: Session, p: PlatformPost, account=None, stat=None, creator=None) -> dict:
    """平台作品统一序列化（works/platform 共用，R-061 收敛）。

    返回字段为两类消费方字段的并集；多返回的字段不影响既有前端。
    R-179：可传入已预取的 `account` / `creator`（列表页批量序列化时避免 N+1 的 `db.get(Creator)`）；
    `raw` 只解析一次（原来每条作品要 json.loads 两次）。
    """
    if account is None:
        account = db.get(CreatorAccount, p.account_id)
    if stat is None:
        stat = _latest_stat(db, p.id)
    acc = account
    if creator is None and acc is not None:
        creator = db.get(Creator, acc.creator_id)
    tags = []
    try:
        tags = json.loads(p.tags or "[]") if isinstance(p.tags, str) else (p.tags or [])
    except json.JSONDecodeError:
        tags = []
    return {
        "id": p.id,
        "account_id": p.account_id,
        "creator_id": acc.creator_id if acc else None,
        "creator_name": (creator.name if creator else (acc.nickname if acc else "")),
        "creator_kind": creator.kind if creator else "owner",
        "platform": p.platform,
        "tags": tags,
        "is_ad": p.is_ad,
        "ad_price": p.ad_price,
        "platform_post_id": p.platform_post_id,
        "page_url": build_platform_page_url_from_data(p.platform, p.platform_post_id, parse_raw(p.raw or "")),
        "title": p.title,
        "desc": p.desc,
        "cover": p.cover_url_local,
        "video_url": p.video_url,
        "publish_time": p.publish_time.isoformat() if p.publish_time else None,
        "local_video_id": p.local_video_id,
        "account_nickname": acc.nickname if acc else "",
        "latest_stat": {
            "date": stat.stat_date,
            "plays": stat.plays,
            "likes": stat.likes,
            "favorites": stat.favorites,
            "shares": stat.shares,
            "comments": stat.comments,
            "extra": getattr(stat, "extra", None),
        }
        if stat
        else None,
        "created_at": p.created_at.isoformat() if p.created_at else None,
    }


def auto_merge_creator(db: Session, creator_id: int) -> int:
    """自动合并：同创作者 + 规范化标题相同 → 同一 work。返回新建 work 数。"""
    accounts = (
        db.query(CreatorAccount).filter(CreatorAccount.creator_id == creator_id).all()
    )
    if not accounts:
        return 0
    acc_ids = [a.id for a in accounts]
    posts = (
        db.query(PlatformPost)
        .filter(PlatformPost.account_id.in_(acc_ids), PlatformPost.title != "")
        .order_by(PlatformPost.id)
        .all()
    )
    groups: dict[str, list[PlatformPost]] = {}
    for p in posts:
        key = normalize_work_title(p.title)
        if not key:
            continue
        groups.setdefault(key, []).append(p)

    created = 0
    touched_videos: set[int] = set()
    for key, members in groups.items():
        if len(members) < 2:
            continue
        # 已有 work：取任一成员的 work；否则新建
        existing = next((m.work_id for m in members if m.work_id), None)
        work = db.get(Work, existing) if existing else None
        if work is None:
            longest = max(members, key=lambda m: len(m.title)).title or members[0].title
            work = Work(creator_id=creator_id, title=strip_hashtags(longest))
            db.add(work)
            db.flush()
            created += 1
        assert work is not None  # 上面已查询到或新建
        for m in members:
            if m.work_id != work.id:
                m.work_id = work.id
            if m.local_video_id:
                touched_videos.add(m.local_video_id)
                v = db.get(Video, m.local_video_id)
                if v is not None and v.work_id != work.id:
                    v.work_id = work.id
    if touched_videos:
        db.flush()
    for vid in touched_videos:
        v = db.get(Video, vid)
        if v is not None:
            recompute_video_platforms(db, v)
    db.commit()
    return created


def merge_manual(db: Session, platform_post_ids: list[int], creator_id: int | None = None) -> dict:
    """手动把多条素材标识为同一作品（可跨不同标题）。"""
    ids = [int(x) for x in (platform_post_ids or []) if x]
    if len(ids) < 2:
        raise HTTPException(status_code=400, detail="至少选择 2 条才能合并为同一作品")
    posts = db.query(PlatformPost).filter(PlatformPost.id.in_(ids)).all()
    if len(posts) != len(ids):
        raise HTTPException(status_code=400, detail="部分素材不存在")
    cids = set()
    for p in posts:
        acc = db.get(CreatorAccount, p.account_id)
        if acc:
            cids.add(acc.creator_id)
    if len(cids) > 1:
        raise HTTPException(status_code=400, detail="只能合并同一博主下的素材")
    creator_id = creator_id or next(iter(cids), None)
    existing = next((p.work_id for p in posts if p.work_id), None)
    work = db.get(Work, existing) if existing else None
    if work is None:
        first = posts[0]
        work = Work(
            creator_id=creator_id,
            title=strip_hashtags(first.title or ""),
            cover_path=first.cover_path,
        )
        db.add(work)
        db.flush()
    assert work is not None  # 上面已查询到或新建
    touched_videos: set[int] = set()
    for p in posts:
        p.work_id = work.id
        if p.local_video_id:
            touched_videos.add(p.local_video_id)
            v = db.get(Video, p.local_video_id)
            if v is not None and v.work_id != work.id:
                v.work_id = work.id
    if touched_videos:
        db.flush()
    for vid in touched_videos:
        v = db.get(Video, vid)
        if v is not None:
            recompute_video_platforms(db, v)
    if not work.title and posts:
        work.title = strip_hashtags(posts[0].title or "")
    db.commit()
    return {"ok": True, "work_id": work.id, "members": len(posts)}


def split_work(db: Session, work_id: int, keep_ids: list[int] | None = None) -> dict:
    """拆分作品：未指定的成员移出该 work；全部移出后删除空 work。"""
    work = db.get(Work, work_id)
    if work is None:
        raise HTTPException(status_code=404, detail="作品不存在")
    keep = set(int(x) for x in (keep_ids or []))
    members = db.query(PlatformPost).filter(PlatformPost.work_id == work_id).all()
    touched_videos: set[int] = {p.local_video_id for p in members if p.local_video_id}
    for p in members:
        if p.id not in keep:
            p.work_id = None
    if not keep:
        db.delete(work)
    db.commit()
    for vid in touched_videos:
        v = db.get(Video, vid)
        if v is not None:
            recompute_video_platforms(db, v)
    if touched_videos:
        db.commit()
    return {"ok": True}


def _work_member_item(db: Session, m: PlatformPost, account_map: dict, stat_map: dict, creator_map: dict) -> dict:
    """列表内单条作品的序列化：账号/创作者都用预取好的 map（R-179 去掉 N+1）。"""
    acc = account_map.get(m.account_id)
    creator = creator_map.get(acc.creator_id) if acc is not None else None
    return post_item(db, m, acc, stat_map.get(m.id), creator)


def list_works(db: Session, creator_id: int | None = None) -> list[dict]:
    """素材库云端作品列表：已合并作品在前（含各平台数据），未合并单条在后。

    S5（R-240）：按数据版本键 + 20s TTL 缓存卡片快照，命中直接返回浅拷贝，
    翻页/深链（`/api/works`、`/api/works/by-post`）不再全量重建；版本查询失败时降级直算。
    """
    try:
        key = cards_version(db, creator_id)
    except Exception:  # noqa: BLE001 缓存版本查询失败 → fail-open 到原逻辑
        return _list_works(db, creator_id)
    cached = _cache_get(_WORKS_CACHE, key)
    if cached is not None:
        return cached
    items = _list_works(db, creator_id)
    _cache_put(_WORKS_CACHE, key, items)
    return items


def _list_works(db: Session, creator_id: int | None = None) -> list[dict]:
    """全量构建作品列表（缓存未命中时执行）。"""
    q = db.query(PlatformPost)
    if creator_id:
        acc_ids = [a.id for a in db.query(CreatorAccount).filter(CreatorAccount.creator_id == creator_id, CreatorAccount.enabled.is_(True)).all()]
        q = q.filter(PlatformPost.account_id.in_(acc_ids)) if acc_ids else q.filter(PlatformPost.id < 0)
    posts = q.order_by(PlatformPost.publish_time.desc().nullslast(), PlatformPost.id.desc()).all()

    work_map: dict[int, list[PlatformPost]] = {}
    singles: list[PlatformPost] = []
    for p in posts:
        if p.work_id:
            work_map.setdefault(p.work_id, []).append(p)
        else:
            singles.append(p)

    # 批量预取：账号、作品、每条最新统计、创作者（避免 N+1 逐条查询）
    account_map = {a.id: a for a in db.query(CreatorAccount).all()}
    creator_map = {c.id: c for c in db.query(Creator).all()}
    work_map_cache = {
        w.id: w for w in db.query(Work).filter(Work.id.in_(work_map.keys())).all()
    }
    post_ids = [p.id for p in posts]
    stat_map = latest_stats_map(db, post_ids)

    out: list[dict] = []
    for wid, members in work_map.items():
        work = work_map_cache.get(wid)
        if work is None:
            continue
        members.sort(key=lambda m: m.platform)
        out.append(
            {
                "type": "work",
                "id": wid,
                "title": work.title or members[0].title,
                "creator_id": work.creator_id,
                "cover": next((m.cover_url_local for m in members if m.cover_url_local), None),
                "platforms": [m.platform for m in members],
                "posts": [_work_member_item(db, m, account_map, stat_map, creator_map) for m in members],
            }
        )
    for p in singles:
        acc = account_map.get(p.account_id)
        out.append(
            {
                "type": "post",
                "id": p.id,
                "title": p.title,
                "creator_id": acc.creator_id if acc else None,
                "cover": p.cover_url_local,
                "platforms": [p.platform],
                "posts": [post_item(db, p, acc, stat_map.get(p.id), creator_map.get(acc.creator_id) if acc else None)],
            }
        )
    return out
