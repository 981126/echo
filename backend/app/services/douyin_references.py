from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from ..core.log import get_logger
from ..core.timeutil import now as _app_now
from ..models.platform import Creator
from ..models.video import Video
from ..models.video_review import DouyinReferenceVideo
from .platform.budget import _charge
from .platform.tikhub import make_client

log = get_logger("douyin_references")


def _loads(value: str, fallback: Any) -> Any:
    try:
        return json.loads(value or "null") or fallback
    except json.JSONDecodeError:
        return fallback


def _first(item: dict, *names: str) -> Any:
    for name in names:
        if item.get(name) is not None:
            return item[name]
    stats = item.get("statistics") or item.get("stats") or {}
    for name in names:
        if stats.get(name) is not None:
            return stats[name]
    author = item.get("author") or item.get("user") or {}
    for name in names:
        if author.get(name) is not None:
            return author[name]
    return None


def _int(item: dict, *names: str) -> int | None:
    value = _first(item, *names)
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _time(item: dict) -> datetime | None:
    value = _first(item, "publish_time", "create_time", "createTime")
    try:
        if isinstance(value, (int, float)) or str(value).isdigit():
            return datetime.fromtimestamp(int(value))
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).replace(tzinfo=None) if value else None
    except (ValueError, TypeError, OSError):
        return None


def _items(raw: dict) -> list[dict]:
    """兼容 TikHub 两种信封：data.items/… 与 data.data.objs（低粉榜 2026-10 实测）。"""
    node: Any = raw
    for _ in range(4):
        if isinstance(node, list):
            return [x for x in node if isinstance(x, dict)]
        if not isinstance(node, dict):
            return []
        for key in ("items", "list", "objs", "aweme_list"):
            value = node.get(key)
            if isinstance(value, list):
                return [x for x in value if isinstance(x, dict)]
        nested = node.get("data")
        if isinstance(nested, (dict, list)):
            node = nested
            continue
        return []
    return []


def _video_url(item: dict, external_id: str) -> str:
    """挑一个真正能打开的作品链接：低粉榜的 item_url 可能是图片贴的音乐/静态资源，不能直接当视频链接。"""
    for name in ("videoUrl", "video_url", "url", "share_url", "item_url"):
        value = item.get(name)
        if not isinstance(value, str) or not value.startswith("http"):
            continue
        if "douyin.com/video" in value or "douyin.com/note" in value or "v.douyin.com" in value:
            return value
    media_type = item.get("media_type")
    has_images = bool(item.get("image_cnt")) or item.get("media_type") == 2
    kind = "note" if has_images and media_type != 1 else "video"
    return f"https://www.douyin.com/{kind}/{external_id}"


def _stats_payload(raw: dict) -> dict:
    if any(key in raw for key in ("play_count", "digg_count", "share_count", "comment_count")):
        return raw
    for value in raw.values():
        if isinstance(value, dict):
            found = _stats_payload(value)
            if found:
                return found
        elif isinstance(value, list):
            for item in value:
                if isinstance(item, dict):
                    found = _stats_payload(item)
                    if found:
                        return found
    return {}


def _mock_items(keyword: str) -> list[dict]:
    topic = keyword or "面试"
    return [
        {
            "itemId": "mock-low-fan-1",
            "itemTitle": f"{topic}时最容易说错的一句话",
            "author": {"authorId": "mock-author-1", "nickname": "职场小周", "followers": 1800},
            "playCount": 180000,
            "likeCount": 9600,
            "commentCount": 430,
            "shareCount": 800,
            "duration": 68,
            "createTime": 1761700000,
        },
        {
            "itemId": "mock-low-fan-2",
            "itemTitle": f"普通人怎么准备{topic}，先做好这三步",
            "author": {"authorId": "mock-author-2", "nickname": "成长笔记", "followers": 3200},
            "playCount": 95000,
            "likeCount": 5200,
            "commentCount": 260,
            "shareCount": 410,
            "duration": 92,
            "createTime": 1761600000,
        },
    ]


def _text(value: Any, limit: int) -> str:
    return str(value or "")[:limit]


# 时间窗口（小时）→ 抖音指数搜索合法的 date_type（0/3/7/30）；绝不发 1（非法值）
_DATE_TYPE = {1: 0, 24: 3, 72: 3, 168: 7}


def _duration_seconds(item: dict) -> int | None:
    """低粉榜 item_duration 为毫秒、指数搜索 duration 为秒；大于 1000 一律按毫秒归一。"""
    value = _int(item, "duration", "durationSeconds", "video_duration", "item_duration")
    if value is None:
        return None
    return round(value / 1000) if value > 1000 else value


def refresh_references(db: Session, owner: Creator, filters: dict) -> dict:
    keyword = str(filters.get("keyword") or "").strip()
    category_id = str(filters.get("category_id") or "0")
    date_window = int(filters.get("date_window") or 168)
    if date_window not in (1, 24, 72, 168):
        raise ValueError("时间窗口只支持1/24/72/168小时")
    client = make_client()
    if keyword:
        raw = client.search_douyin_items(
            query=keyword,
            category_id=category_id,
            date_type=_DATE_TYPE[date_window],
            label_type=1,
            duration_type=int(filters.get("duration_type") or 0),
        )
        source = "index_search"
    else:
        raw = client.fetch_douyin_low_fan(
            page_size=int(filters.get("limit") or 20),
            date_window=date_window,
            keyword=keyword,
            tags=filters.get("tags") or [],
        )
        source = "low_fan_billboard"
    items = _items(raw) or (_mock_items(keyword) if client.mode != "real" else [])
    items = items[:max(1, min(50, int(filters.get("limit") or 20)))]
    saved = 0
    warnings: list[str] = []
    stats_failed = 0
    for item in items:
        external_id = _text(_first(item, "itemId", "item_id", "aweme_id", "id"), 200)
        if not external_id:
            continue
        row = db.query(DouyinReferenceVideo).filter_by(external_post_id=external_id).first()
        if row is None:
            row = DouyinReferenceVideo(external_post_id=external_id, first_seen_at=_app_now())
            db.add(row)
        row.source = source
        row.source_label = "官方低粉爆款榜" if source == "low_fan_billboard" else "低粉爆款筛选"
        row.author_id = _text(_first(item, "authorId", "author_id", "uid", "user_id"), 200)
        row.author_nickname = _text(_first(item, "nickname", "nick_name", "authorNickname", "author_nickname", "name"), 100)
        row.author_followers = _int(item, "followers", "followerCount", "authorFollowers", "fans", "fans_cnt")
        row.title = _text(_first(item, "itemTitle", "title", "item_title", "desc"), 500)
        row.cover_url = _text(_first(item, "cover", "coverUrl", "cover_url", "thumbnail", "item_cover_url"), 1000)
        row.video_url = _text(_video_url(item, external_id), 1000)
        row.publish_time = _time(item)
        row.duration_seconds = _duration_seconds(item)
        row.plays = _int(item, "playCount", "play_count", "plays", "play", "play_cnt")
        row.likes = _int(item, "likeCount", "digg_count", "likes", "like", "like_cnt")
        row.comments = _int(item, "commentCount", "comment_count", "comments", "comment", "comment_cnt")
        row.shares = _int(item, "shareCount", "share_count", "shares", "share", "share_cnt")
        # 指数搜索没有播放量字段，前 5 条用作品统计补全（列表接口不返回播放量是平台限制）
        if client.mode == "real" and row.plays is None and saved < 5:
            try:
                stats = _stats_payload(client.fetch_douyin_video_statistics(external_id))
                row.plays = int(stats["play_count"]) if stats.get("play_count") is not None else None
                row.likes = row.likes if row.likes is not None else (int(stats["digg_count"]) if stats.get("digg_count") is not None else None)
                row.comments = row.comments if row.comments is not None else (int(stats["comment_count"]) if stats.get("comment_count") is not None else None)
                row.shares = row.shares if row.shares is not None else (int(stats["share_count"]) if stats.get("share_count") is not None else None)
            except Exception as exc:
                stats_failed += 1
                log.warning("低粉爆款播放补全失败 %s：%s", external_id, exc)
        row.category_id = category_id[:40]
        row.keyword = keyword[:200]
        row.raw = json.dumps(item, ensure_ascii=False, default=str)
        row.last_seen_at = _app_now()
        saved += 1
    db.commit()
    if client.mode == "real":
        for _ in range(client.requests_used):
            _charge(db)
    if saved == 0:
        warnings.append("当前条件下没有获取到低粉爆款视频，可换关键词或时间窗口重试")
    if stats_failed:
        warnings.append(f"{stats_failed} 条低粉爆款缺少播放量（平台统计接口未返回），页面显示暂无数据")
    return {"saved": saved, "kind": "low_fan", "filters": filters, "warnings": warnings}


def _owner_keywords(db: Session, owner: Creator) -> set[str]:
    result: set[str] = set()
    for video in db.query(Video).filter_by(creator_id=owner.id).all():
        for value in _loads(video.main_topics, []) + _loads(video.tags, []):
            if str(value).strip():
                result.add(str(value).strip().lower())
    return result or {"求职", "面试", "赚钱", "知识"}


def relevance_for(db: Session, owner: Creator, row: DouyinReferenceVideo, keywords: set[str] | None = None) -> int:
    """相关性打分（R-240 S6：批量场景可传入已算好的 `keywords`，避免逐行查库）。"""
    score = 40 if row.category_id and row.category_id != "0" else 0
    words = _owner_keywords(db, owner) if keywords is None else keywords
    haystack = f"{row.title} {row.keyword}".lower()
    matches = sum(1 for word in words if word.lower() in haystack)
    score += min(30, matches * 15)
    if row.keyword and row.keyword.lower() in haystack:
        score += 20
    if row.duration_seconds and 45 <= row.duration_seconds <= 150:
        score += 10
    return min(100, score)


def reference_out(
    db: Session,
    owner: Creator,
    row: DouyinReferenceVideo,
    keywords: set[str] | None = None,
) -> dict:
    return {
        "id": f"low_fan:{row.id}",
        "kind": "low_fan",
        "title": row.title,
        "cover_url": row.cover_url,
        "author_nickname": row.author_nickname,
        "author_followers": row.author_followers,
        "publish_time": row.publish_time,
        "plays": row.plays,
        "likes": row.likes,
        "comments": row.comments,
        "video_url": row.video_url,
        "verdict": "低粉爆款",
        "verdict_evidence": {"source": row.source, "label": row.source_label},
        "relevance": relevance_for(db, owner, row, keywords=keywords),
        "analysis": _loads(row.analysis, {}) or None,
    }
