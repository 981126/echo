"""指标服务：三通道（手动/导入/cookie best-effort）+ 留存清理。"""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy.orm import Session

from ..core.metrics import retention_cutoff_date
from ..models.hot_topic import HotTopic
from ..models.metrics import MetricsSnapshot
from ..models.video import Video


def _parse_list(raw) -> list:
    """解析 JSON 数组字段；非法/空返回 []。"""
    if not raw:
        return []
    try:
        data = json.loads(raw)
        return [str(x) for x in data] if isinstance(data, list) else []
    except (ValueError, TypeError):
        return []


def apply_retention(db: Session, hot_days: int = 30) -> dict:
    """数据保留策略：热点快照只留 N 天。"""
    cutoff = retention_cutoff_date(hot_days)
    deleted = (
        db.query(HotTopic)
        .filter(HotTopic.topic_date < cutoff)
        .delete(synchronize_session=False)
    )
    db.commit()
    return {"hot_topics_deleted": deleted}


def _platform_breakdown(db, v) -> list[dict[str, Any]]:
    """素材三个平台（抖音/B站/小红书）各自的最新互动数据（无则 None）。"""
    from ..models.platform import PlatformPost, PlatformPostStat

    order = ["douyin", "bilibili", "xiaohongshu"]
    seen: dict[int, PlatformPost] = {}
    for p in db.query(PlatformPost).filter(PlatformPost.local_video_id == v.id).all():
        seen[p.id] = p
    if v.work_id:
        for p in db.query(PlatformPost).filter(PlatformPost.work_id == v.work_id).all():
            seen[p.id] = p
    if v.platform_post_id and ":" in v.platform_post_id:
        platform, ext = v.platform_post_id.split(":", 1)
        p = db.query(PlatformPost).filter(PlatformPost.platform == platform, PlatformPost.platform_post_id == ext).first()
        if p is not None:
            seen[p.id] = p
    by_platform: dict[str, PlatformPost] = {}
    for p in seen.values():
        if p.platform not in by_platform:
            by_platform[p.platform] = p
    out = []
    for platform in order:
        p = by_platform.get(platform)
        stat = None
        if p is not None:
            stat = (
                db.query(PlatformPostStat)
                .filter(PlatformPostStat.post_id == p.id)
                .order_by(PlatformPostStat.stat_date.desc())
                .first()
            )
        out.append(
            {
                "platform": platform,
                "plays": stat.plays if stat else None,
                "likes": stat.likes if stat else None,
                "favorites": stat.favorites if stat else None,
                "comments": stat.comments if stat else None,
            }
        )
    return out


def summary(db: Session) -> dict:
    """按视频的最新快照汇总 + 按赛道/平台聚合。"""
    videos = db.query(Video).all()
    per_video: list[dict[str, Any]] = []
    topic_stats: dict[str, dict[str, int]] = {}
    platform_stats: dict[str, dict[str, int]] = {}
    for v in videos:
        latest = (
            db.query(MetricsSnapshot)
            .filter(MetricsSnapshot.video_id == v.id)
            .order_by(MetricsSnapshot.snapshot_date.desc())
            .first()
        )
        if latest is None:
            continue
        platforms = _parse_list(v.platforms)
        main_topics = _parse_list(v.main_topics)
        item: dict[str, Any] = {
            "video_id": v.id,
            "filename": v.filename,
            "title": v.title or v.filename,
            "platforms": platforms,
            "main_topics": main_topics,
            "published_at": str(v.published_at or ""),
            "plays": latest.plays,
            "likes": latest.likes,
            "favorites": latest.favorites,
            "comments": latest.comments,
            "followers_gained": latest.followers_gained,
            "snapshot_date": latest.snapshot_date,
            "platform_breakdown": _platform_breakdown(db, v),
        }
        per_video.append(item)
        for topic in main_topics or ["未标"]:
            ts = topic_stats.setdefault(
                topic, {"videos": 0, "plays": 0, "likes": 0, "favorites": 0, "comments": 0}
            )
            ts["videos"] += 1
            ts["plays"] += latest.plays
            ts["likes"] += latest.likes
            ts["favorites"] += latest.favorites
            ts["comments"] += latest.comments
        for plat in platforms or ["未定"]:
            ps = platform_stats.setdefault(plat, {"videos": 0, "plays": 0, "likes": 0})
            ps["videos"] += 1
            ps["plays"] += latest.plays
            ps["likes"] += latest.likes
    per_video.sort(key=lambda x: (x["published_at"] is not None, str(x["published_at"] or "")), reverse=True)
    return {
        "per_video": per_video,
        "by_topic": topic_stats,
        "by_platform": platform_stats,
    }


def radar(db: Session) -> list[dict[str, Any]]:
    """赛道雷达（R-007）：按赛道统计互动率并降序（从已下线的 review 服务迁来，功能仍被 AI 对话使用）。"""
    from ..core.metrics import engagement_rate

    data = summary(db)
    out = [
        {
            "topic": topic,
            "videos": s["videos"],
            "plays": s["plays"],
            "likes": s["likes"],
            "engagement": engagement_rate(s["plays"], s["likes"], s["favorites"], s["comments"]),
        }
        for topic, s in data["by_topic"].items()
    ]
    out.sort(key=lambda x: x["engagement"], reverse=True)
    return out
