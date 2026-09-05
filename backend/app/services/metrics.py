"""指标服务：三通道（手动/导入/cookie best-effort）+ 留存清理。"""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy.orm import Session

from ..core.metrics import normalize_snapshot, retention_cutoff_date
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


def upsert_snapshot(
    db: Session,
    video_id: int,
    snapshot_date: str,
    values: dict,
    source: str = "manual",
) -> MetricsSnapshot:
    """按 (video_id, date) 幂等写入/更新。"""
    norm = normalize_snapshot(values)
    row = (
        db.query(MetricsSnapshot)
        .filter(MetricsSnapshot.video_id == video_id, MetricsSnapshot.snapshot_date == snapshot_date)
        .first()
    )
    if row is None:
        row = MetricsSnapshot(video_id=video_id, snapshot_date=snapshot_date, source=source, **norm)
        db.add(row)
    else:
        for k, v in norm.items():
            setattr(row, k, v)
        row.source = source
    db.commit()
    db.refresh(row)
    return row


def import_snapshots(db: Session, rows: list[dict]) -> int:
    """批量导入（平台导出/手动填报）。rows: [{video_id, snapshot_date, plays, ...}]"""
    count = 0
    for row in rows:
        try:
            video_id = int(row["video_id"])
            snapshot_date = str(row["snapshot_date"])
        except (KeyError, TypeError, ValueError):
            continue
        if db.get(Video, video_id) is None:
            continue
        upsert_snapshot(db, video_id, snapshot_date, row, source="import")
        count += 1
    return count


def fetch_daily(db: Session) -> dict:
    """每日 cookie 抓取（best-effort）。real 模式需在 NAS 联调；mock 模式不造假数据。"""
    from ..config import get_settings

    settings = get_settings()
    if (settings.hot_source_mode or "mock").lower() == "mock":
        return {"fetched": 0, "note": "mock 模式不抓取指标，请用导入/手动通道录入"}
    # real 模式：此处为占位，需按平台（抖音/B站/小红书）创作者后台实现 cookie 抓取
    return {"fetched": 0, "note": "cookie 抓取需在 NAS 联调（见 PRD §3.6 三通道设计）"}


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


def series_for_video(db: Session, video_id: int) -> list[dict]:
    rows = (
        db.query(MetricsSnapshot)
        .filter(MetricsSnapshot.video_id == video_id)
        .order_by(MetricsSnapshot.snapshot_date)
        .all()
    )
    return [
        {
            "date": r.snapshot_date,
            "plays": r.plays,
            "likes": r.likes,
            "favorites": r.favorites,
            "comments": r.comments,
            "followers_gained": r.followers_gained,
            "source": r.source,
        }
        for r in rows
    ]


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
