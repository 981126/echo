"""R-267：草稿 → 云端作品绑定、发布后效果回填与资产效果回流。

- 绑定：显式选作品（必填）+ 本地视频（可选），写入 post_id/work_id/video_id/发布信息；
- 回填：复用 `build_comparison` 的同话题同时长基线，写 `drafts.performance`；
- 回流：AI 稿用到的作者资产按 5 秒完播分位写 `usage_stats.performance`。
"""

from __future__ import annotations

import json
from statistics import median
from typing import Any

from sqlalchemy.orm import Session

from ..core.timeutil import now as _app_now
from ..models.author_generation import AuthorAsset, GenerationRun
from ..models.draft import Draft
from ..models.platform import CreatorAccount, PlatformPost, PlatformPostStat
from ..models.video import Video
from ..models.video_review import DouyinPostMetric
from .creator_service import current_creator_id
from .video_review_comparison import build_comparison

CACHE_HOURS = 6
RECENT_PERCENTILES = 5
METRIC_KEYS = (
    "plays",
    "likes",
    "favorites",
    "comments",
    "shares",
    "finish_5s_rate",
    "bounce_2s_rate",
    "finish_rate",
    "avg_view_proportion",
)


def _loads(text: str | None) -> dict:
    try:
        data = json.loads(text or "{}")
    except (TypeError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _hours_since(iso: str) -> float:
    from datetime import datetime

    try:
        moment = datetime.fromisoformat(str(iso))
    except ValueError:
        return 10**9
    return (_app_now() - moment).total_seconds() / 3600


def owner_account_ids(db: Session, creator_id: int) -> list[int]:
    rows = db.query(CreatorAccount.id).filter(CreatorAccount.creator_id == creator_id).all()
    return [int(row[0]) for row in rows]


def candidates(db: Session, query: str = "", limit: int = 20) -> list[dict]:
    """当前主博主账号下的作品（按发布时间倒序），供绑定选择器搜索。"""
    creator_id = current_creator_id(db)
    if creator_id is None:
        raise ValueError("请先选择当前主博主")
    account_ids = owner_account_ids(db, creator_id)
    if not account_ids:
        raise ValueError("请先绑定当前主博主的平台账号")
    q = db.query(PlatformPost).filter(PlatformPost.account_id.in_(account_ids))
    if query.strip():
        q = q.filter(PlatformPost.title.contains(query.strip()))
    rows = (
        q.order_by(PlatformPost.publish_time.desc().nulls_last(), PlatformPost.id.desc())
        .limit(max(1, min(int(limit), 50)))
        .all()
    )
    post_ids = [row.id for row in rows]
    stats: dict[int, PlatformPostStat] = {}
    if post_ids:
        for stat in (
            db.query(PlatformPostStat)
            .filter(PlatformPostStat.post_id.in_(post_ids))
            .order_by(PlatformPostStat.stat_date)
            .all()
        ):
            stats[int(stat.post_id)] = stat
    return [
        {
            "post_id": row.id,
            "platform": row.platform,
            "title": row.title,
            "publish_time": row.publish_time.isoformat() if row.publish_time else None,
            "plays": int(stats[row.id].plays or 0) if row.id in stats else None,
            "video_id": row.local_video_id,
            "has_local_video": bool(row.local_video_id),
        }
        for row in rows
    ]


def bind(
    db: Session,
    draft: Draft,
    *,
    post_id: int,
    video_id: int | None = None,
    publish_url: str = "",
) -> dict:
    """绑定作品并立即回填；返回 performance。"""
    post = db.get(PlatformPost, post_id)
    if post is None:
        raise ValueError("作品不存在")
    account = db.get(CreatorAccount, post.account_id)
    if account is None or account.creator_id != draft.creator_id:
        raise ValueError("该作品不属于当前主博主")
    if video_id is not None:
        video = db.get(Video, video_id)
        if video is None or video.creator_id != draft.creator_id:
            raise ValueError("视频不属于当前主博主")
        draft.video_id = video_id
    elif post.local_video_id:
        draft.video_id = post.local_video_id
    draft.post_id = post.id
    draft.work_id = post.work_id
    draft.publish_platform = post.platform or ""
    draft.publish_url = (publish_url or post.video_url or "").strip()[:500]
    draft.published_at = post.publish_time or _app_now()
    db.commit()
    return refresh(db, draft, force=True) or {}


def unbind(db: Session, draft: Draft) -> None:
    """解除绑定：清空作品与发布信息，performance 一并清空；保留手动关联的 video_id。"""
    draft.post_id = None
    draft.work_id = None
    draft.publish_platform = ""
    draft.publish_url = ""
    draft.published_at = None
    draft.performance = "{}"
    db.commit()


def _data_time(db: Session, post_id: int) -> str | None:
    metric = (
        db.query(DouyinPostMetric)
        .filter(DouyinPostMetric.post_id == post_id)
        .order_by(DouyinPostMetric.snapshot_date.desc())
        .first()
    )
    if metric is not None:
        return metric.captured_at.isoformat() if metric.captured_at else None
    stat = (
        db.query(PlatformPostStat)
        .filter(PlatformPostStat.post_id == post_id)
        .order_by(PlatformPostStat.stat_date.desc())
        .first()
    )
    return stat.stat_date if stat is not None else None


def refresh(db: Session, draft: Draft, *, force: bool = False) -> dict | None:
    """按绑定作品回填指标与基线；6 小时缓存，force 忽略缓存。"""
    if not draft.post_id:
        return None
    current = _loads(draft.performance)
    if not force and current.get("refreshed_at") and _hours_since(current["refreshed_at"]) < CACHE_HOURS:
        return current
    post = db.get(PlatformPost, draft.post_id)
    if post is None:
        return None
    comparison = build_comparison(db, post)
    facts: dict[str, dict] = comparison.get("facts") or {}
    metrics: dict[str, dict] = {}
    for key in METRIC_KEYS:
        item = facts.get(key) or {}
        value = item.get("value")
        metrics[key] = {
            "value": value,
            "baseline": item.get("baseline"),
            "percentile": item.get("percentile"),
            "state": item.get("state"),
            "sample_count": item.get("sample_count"),
            "unit": item.get("unit"),
            "missing": value is None,
        }
    private = any(metrics[key]["value"] is not None for key in ("finish_5s_rate", "bounce_2s_rate", "finish_rate"))
    payload: dict[str, Any] = {
        "post_id": post.id,
        "platform": post.platform,
        "post_title": post.title,
        "published_at": post.publish_time.isoformat() if post.publish_time else None,
        "private_metrics": private,
        "metrics": metrics,
        "baseline_note": (comparison.get("baseline") or {}).get("note", ""),
        "data_time": _data_time(db, post.id),
        "refreshed_at": _app_now().isoformat(),
    }
    draft.performance = json.dumps(payload, ensure_ascii=False)
    db.commit()
    _writeback_assets(db, draft, metrics.get("finish_5s_rate") or {}, post.id)
    return payload


def _writeback_assets(db: Session, draft: Draft, finish5: dict, post_id: int) -> None:
    """把 5 秒完播分位写回这篇稿用到的资产（最近 5 次取中位数）。"""
    percentile = finish5.get("percentile")
    if not isinstance(percentile, (int, float)):
        return
    run = (
        db.query(GenerationRun)
        .filter(GenerationRun.draft_id == draft.id)
        .order_by(GenerationRun.id.desc())
        .first()
    )
    if run is None:
        return
    evidence = _loads(run.evidence_json)
    ids = [
        int(item["id"])
        for item in evidence.get("author_assets") or []
        if isinstance(item, dict) and item.get("id") is not None
    ]
    if not ids:
        return
    for asset in db.query(AuthorAsset).filter(AuthorAsset.id.in_(ids)).all():
        stats = _loads(asset.usage_stats)
        raw_published = stats.get("published")
        published: dict = raw_published if isinstance(raw_published, dict) else {}
        recent = [float(x) for x in published.get("recent") or [] if isinstance(x, (int, float))]
        recent = (recent + [float(percentile)])[-RECENT_PERCENTILES:]
        published.update(
            {
                "count": int(published.get("count") or 0) + 1,
                "last_post_id": post_id,
                "last_percentile": float(percentile),
                "recent": recent,
            }
        )
        stats["published"] = published
        stats["performance"] = round(median(recent), 2)
        asset.usage_stats = json.dumps(stats, ensure_ascii=False)
    db.commit()


def refresh_all(db: Session, limit: int = 200) -> int:
    """刷新全部已绑定草稿（每日任务用）；单条失败不影响其它。"""
    rows = db.query(Draft).filter(Draft.post_id.isnot(None)).order_by(Draft.id.desc()).limit(limit).all()
    updated = 0
    for draft in rows:
        try:
            if refresh(db, draft, force=False) is not None:
                updated += 1
        except Exception:  # noqa: BLE001 单条失败不拖垮整批
            db.rollback()
    return updated
