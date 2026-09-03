"""纯逻辑（无第三方依赖）：指标规范化、互动率、留存日期。"""

from __future__ import annotations

import datetime

METRIC_FIELDS = ["plays", "likes", "favorites", "comments", "followers_gained"]


def normalize_snapshot(values: dict) -> dict:
    """指标字段统一为非负整数。"""
    out = {}
    for key in METRIC_FIELDS:
        try:
            v = int(values.get(key, 0) or 0)
        except (TypeError, ValueError):
            v = 0
        out[key] = max(v, 0)
    return out


def engagement_rate(plays: int, likes: int, favorites: int, comments: int) -> float:
    """互动率 = (赞+藏+评)/播放 × 100。"""
    if plays <= 0:
        return 0.0
    return round((likes + favorites + comments) / plays * 100, 2)


def retention_cutoff_date(days: int) -> str:
    """N 天前的日期（YYYY-MM-DD），用于数据保留清理。"""
    return (datetime.date.today() - datetime.timedelta(days=days)).isoformat()
