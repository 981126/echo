"""指标服务：三通道（手动/导入/cookie best-effort）+ 留存清理。"""
from sqlalchemy.orm import Session

from ..core.metrics import normalize_snapshot, retention_cutoff_date
from ..models.hot_topic import HotTopic
from ..models.metrics import MetricsSnapshot
from ..models.video import Video


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


def summary(db: Session) -> dict:
    """按视频的最新快照汇总 + 按赛道/平台聚合。"""
    videos = db.query(Video).all()
    per_video = []
    topic_stats: dict[str, dict] = {}
    platform_stats: dict[str, dict] = {}
    for v in videos:
        latest = (
            db.query(MetricsSnapshot)
            .filter(MetricsSnapshot.video_id == v.id)
            .order_by(MetricsSnapshot.snapshot_date.desc())
            .first()
        )
        if latest is None:
            continue
        item = {
            "video_id": v.id,
            "filename": v.filename,
            "platform": v.platform,
            "main_topic": v.main_topic,
            "published_at": str(v.published_at or ""),
            "plays": latest.plays,
            "likes": latest.likes,
            "favorites": latest.favorites,
            "comments": latest.comments,
            "followers_gained": latest.followers_gained,
            "snapshot_date": latest.snapshot_date,
        }
        per_video.append(item)
        topic = v.main_topic or "未标"
        topic_stats.setdefault(topic, {"videos": 0, "plays": 0, "likes": 0, "favorites": 0, "comments": 0})
        ts = topic_stats[topic]
        ts["videos"] += 1
        ts["plays"] += latest.plays
        ts["likes"] += latest.likes
        ts["favorites"] += latest.favorites
        ts["comments"] += latest.comments
        plat = v.platform or "未定"
        platform_stats.setdefault(plat, {"videos": 0, "plays": 0, "likes": 0})
        ps = platform_stats[plat]
        ps["videos"] += 1
        ps["plays"] += latest.plays
        ps["likes"] += latest.likes
    per_video.sort(key=lambda x: x["plays"], reverse=True)
    return {
        "per_video": per_video,
        "by_topic": topic_stats,
        "by_platform": platform_stats,
    }
