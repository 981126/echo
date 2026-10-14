"""素材库统一卡片列表（R-179）。

素材库一个页面 = 本地素材（videos）+ 云端作品（works）**合并去重**后按日期倒序展示。
R-179 把这段口径从 `frontend_v2/src/pages/videos/types.ts` 的 `buildCards/applyFiltersTo`
整体搬到服务端：分页（每批 20、游标稳定）、筛选/搜索/计数一起下推，前端只发参数。

口径（与搬移前的 `buildCards` 完全一致）：
- 本地素材：按可见性口径取（`video_query.visible_videos_query`，含 R-107 禁用账号排除），
  再剔除**被云端作品绑定**的那些（`posts[].local_video_id`）；
- 云端作品：与 `/api/works` 同一分组（work_id 合并 + 未合并单条，成员按平台名排序），
  卡片保留 `cloudPosts`（供同步/评论/广告合并用）；
- 排序：日期倒序（同日按 kind/id 兜底，保证游标稳定可复现）。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from ..models.platform import CreatorAccount, PlatformPost
from ..models.video import Video
from ..models.work import Work
from .creator_service import current_creator_id
from .video_query import visible_videos_query
from .works_service import latest_stats_map


@dataclass
class CardFilters:
    """素材库筛选（与前端筛选控件一一对应）。"""

    platforms: list[str] = field(default_factory=list)
    status: str = ""
    video: str = ""  # yes | no | ""
    ad: str = ""  # ad | no | ""
    kw: str = ""
    tags: list[str] = field(default_factory=list)
    likes_min: int | None = None
    likes_max: int | None = None


def has_real_file(filename: str | None) -> bool:
    """占位稿（`__cloud__` 前缀）不算有视频文件——与前端 `hasRealFile` 同语义。"""
    return bool(filename) and not str(filename).startswith("__cloud__")


def _date_of(value) -> str:
    return str(value or "")[:10]


def _json_list(value) -> list[str]:
    """Video 的 platforms/main_topics/tags 都是 JSON 数组字符串（TEXT 列）。"""
    import json

    if isinstance(value, list):
        return [str(x) for x in value if x]
    try:
        data = json.loads(value or "[]")
    except (TypeError, ValueError):
        return []
    return [str(x) for x in data if x] if isinstance(data, list) else []


def _local_cards(videos: list[Video], linked: set[int]) -> list[dict]:
    out: list[dict] = []
    for v in videos:
        if v.id in linked:
            continue
        tags: list[str] = []
        for t in _json_list(v.main_topics) + _json_list(v.tags):
            if t and t not in tags:
                tags.append(t)
        out.append(
            {
                "key": f"v{v.id}",
                "kind": "local",
                "id": v.id,
                "type": None,
                "creator_id": v.creator_id,
                "title": v.title or v.filename or "",
                "cover_url": v.cover_url or "",
                "platforms": sorted(set(_json_list(v.platforms))),
                "tags": tags,
                "status": v.status or "",
                "is_ad": bool(v.is_ad),
                "ad_price": int(v.ad_price) if v.ad_price is not None else None,
                "merged": 0,
                "cloudPosts": [],
                "local_video_id": None,
                "hasVideo": has_real_file(v.filename),
                "filename": v.filename,
                "tags_confirmed": bool(v.tags_confirmed),
                "date": _date_of(v.published_at or v.planned_publish_at or v.created_at),
            }
        )
    return out


def _post_tags(p: PlatformPost) -> list[str]:
    """PlatformPost.tags 是 JSON 数组字符串（与 works_service 同解析口径）。"""
    import json

    try:
        raw = json.loads(p.tags or "[]") if isinstance(p.tags, str) else (p.tags or [])
    except json.JSONDecodeError:
        raw = []
    return [str(t) for t in raw if t]


def _slim_post(p: PlatformPost, stat) -> dict:
    """卡片只需要这些（完整字段由 `/api/works` 详情接口提供）。"""
    return {
        "id": p.id,
        "platform": p.platform,
        "is_ad": bool(p.is_ad),
        "ad_price": int(p.ad_price) if p.ad_price is not None else None,
        "local_video_id": p.local_video_id,
        "publish_time": p.publish_time.isoformat() if p.publish_time else None,
        "latest_stat": (
            {
                "likes": stat.likes,
                "comments": stat.comments,
                "favorites": stat.favorites,
                "shares": stat.shares,
                "plays": stat.plays,
            }
            if stat
            else None
        ),
    }


def _cloud_cards(db: Session, creator_id: int) -> tuple[list[dict], set[int]]:
    """云端作品 → 卡片；同时返回被绑定的本地素材 id（本地卡片要剔除它们）。"""
    cid = creator_id or current_creator_id(db)
    q = db.query(PlatformPost)
    if cid:
        acc_ids = [
            a.id
            for a in db.query(CreatorAccount)
            .filter(CreatorAccount.creator_id == cid, CreatorAccount.enabled.is_(True))
            .all()
        ]
        q = q.filter(PlatformPost.account_id.in_(acc_ids)) if acc_ids else q.filter(PlatformPost.id < 0)
    posts = q.order_by(PlatformPost.publish_time.desc().nullslast(), PlatformPost.id.desc()).all()

    work_map: dict[int, list[PlatformPost]] = {}
    singles: list[PlatformPost] = []
    for p in posts:
        if p.work_id:
            work_map.setdefault(p.work_id, []).append(p)
        else:
            singles.append(p)

    work_rows = {w.id: w for w in db.query(Work).filter(Work.id.in_(work_map.keys())).all()} if work_map else {}
    account_map = {a.id: a for a in db.query(CreatorAccount).all()}
    stat_map = latest_stats_map(db, [p.id for p in posts])
    linked = {p.local_video_id for p in posts if p.local_video_id}
    bound_videos = {v.id: v for v in db.query(Video).filter(Video.id.in_(linked)).all()} if linked else {}

    groups: list[tuple[str, int, list[PlatformPost], int | None, str]] = []
    for wid, members in work_map.items():
        work = work_rows.get(wid)
        if work is None:
            continue
        members.sort(key=lambda m: m.platform)
        groups.append(("work", wid, members, work.creator_id, work.title or members[0].title))
    for p in singles:
        acc = account_map.get(p.account_id)
        groups.append(("post", p.id, [p], acc.creator_id if acc else None, p.title))

    out: list[dict] = []
    for kind, gid, members, owner_id, title in groups:
        any_local = next((m.local_video_id for m in members if m.local_video_id), None)
        bound = bound_videos.get(any_local) if any_local else None
        tags: list[str] = []
        for m in members:
            for t in _post_tags(m):
                if t and t not in tags:
                    tags.append(t)
        # 绑定本地素材的标签也是这份内容的主数据：帖子没带话题（部分平台不返回）时也要能显示
        if bound is not None:
            for t in _json_list(bound.main_topics) + _json_list(bound.tags):
                if t and t not in tags:
                    tags.append(t)
        prices = [int(m.ad_price) for m in members if m.ad_price is not None]
        if bound is not None and bound.ad_price is not None:
            prices.append(int(bound.ad_price))
        out.append(
            {
                "key": ("w" if kind == "work" else "p") + str(gid),
                "kind": "cloud",
                "id": gid,
                "type": kind,
                "creator_id": owner_id,
                "title": title or "（无标题）",
                "cover_url": next((m.cover_url_local for m in members if m.cover_url_local), "") or "",
                "platforms": sorted({m.platform for m in members if m.platform}),
                "tags": tags,
                "status": "published",
                "is_ad": any(bool(m.is_ad) for m in members) or bool(bound is not None and bound.is_ad),
                "ad_price": max(prices) if prices else None,
                "merged": len(members) if kind == "work" else 0,
                "cloudPosts": [_slim_post(m, stat_map.get(m.id)) for m in members],
                "local_video_id": any_local,
                "hasVideo": has_real_file(bound.filename) if bound is not None else False,
                "filename": bound.filename if bound is not None else None,
                "tags_confirmed": None,
                "date": _date_of(members[0].publish_time) if members else "",
            }
        )
    return out, linked


def build_cards(db: Session, creator_id: int = 0) -> list[dict]:
    """素材库全量卡片（已合并去重、按日期倒序）。"""
    cloud, linked = _cloud_cards(db, creator_id)
    videos = (
        visible_videos_query(db, creator_id)
        .order_by(Video.created_at.desc())
        .all()
    )
    cards = _local_cards(videos, linked) + cloud
    # 日期倒序；同日用 kind/id 兜底 → 顺序确定，游标分页才稳定
    return sorted(cards, key=lambda c: (c["date"], c["kind"], c["id"]), reverse=True)


def _likes_of(card: dict) -> list[int]:
    out: list[int] = []
    for p in card.get("cloudPosts") or []:
        stat = p.get("latest_stat") or {}
        if stat.get("likes") is not None:
            out.append(int(stat["likes"]))
    return out


def apply_filters(cards: list[dict], f: CardFilters) -> list[dict]:
    """与搬移前 `applyFiltersTo` 完全同语义。"""
    kw = (f.kw or "").strip().lower()
    out: list[dict] = []
    for c in cards:
        if kw and kw not in str(c.get("title") or "").lower():
            continue
        if f.status and c.get("status") != f.status:
            continue
        if f.ad == "ad" and not c.get("is_ad"):
            continue
        if f.ad == "no" and c.get("is_ad"):
            continue
        if f.video == "yes" and not c.get("hasVideo"):
            continue
        if f.video == "no" and c.get("hasVideo"):
            continue
        if f.platforms and not any(p in (c.get("platforms") or []) for p in f.platforms):
            continue
        if f.tags and not all(t in (c.get("tags") or []) for t in f.tags):
            continue
        if f.likes_min is not None or f.likes_max is not None:
            likes = _likes_of(c)
            ok = any(
                (f.likes_min is None or v >= f.likes_min) and (f.likes_max is None or v <= f.likes_max)
                for v in likes
            )
            if not ok:
                continue
        out.append(c)
    return out


def facets(cards: list[dict]) -> dict:
    """筛选项候选（标签来自**全部**卡片，不受当前筛选影响）。"""
    tags: list[str] = []
    for c in cards:
        for t in c.get("tags") or []:
            if t and t not in tags:
                tags.append(t)
    return {"tags": sorted(tags)}


def _sort_key(card: dict) -> tuple[str, str, int]:
    return (str(card.get("date") or ""), str(card.get("kind") or ""), int(card.get("id") or 0))


def page(
    db: Session,
    *,
    creator_id: int = 0,
    filters: CardFilters | None = None,
    cursor: tuple[str, str, int] | None = None,
    limit: int = 20,
) -> dict:
    """一页卡片：`{total, filtered_total, facets, items, next_cursor}`。

    `cursor` 是上一页最后一条的 `(date, kind, id)`：滚动期间后台同步插入新条目也**不会重复/漏条**。
    """
    cards = build_cards(db, creator_id)
    f = filters or CardFilters()
    filtered = apply_filters(cards, f)
    filtered_total = len(filtered)
    if cursor is not None:
        # 与排序同序（日期倒序）→ 只取严格排在游标之后的
        filtered = [c for c in filtered if _sort_key(c) < cursor]
    limit = max(1, min(int(limit or 20), 100))
    items = filtered[: limit + 1]
    has_more = len(items) > limit
    items = items[:limit]
    return {
        "total": len(cards),
        "filtered_total": filtered_total,
        "facets": facets(cards),
        "items": items,
        "next_cursor": _encode_cursor(items[-1]) if has_more and items else None,
        "has_more": has_more,
    }


def _encode_cursor(card: dict) -> str:
    import base64
    import json

    date, kind, cid = _sort_key(card)
    raw = json.dumps({"d": date, "k": kind, "i": cid}, ensure_ascii=False).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def decode_cursor(token: str) -> tuple[str, str, int] | None:
    """坏游标不致命：解不出来就当作从头开始。"""
    import base64
    import json

    if not token:
        return None
    try:
        pad = "=" * (-len(token) % 4)
        data = json.loads(base64.urlsafe_b64decode(token + pad).decode())
        return (str(data["d"]), str(data["k"]), int(data["i"]))
    except Exception:  # noqa: BLE001
        return None
