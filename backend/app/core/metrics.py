"""纯逻辑（无第三方依赖）：互动率、留存日期。"""

from __future__ import annotations

import datetime


def engagement_rate(plays: int, likes: int, favorites: int, comments: int) -> float:
    """互动率 = (赞+藏+评)/播放 × 100。"""
    if plays <= 0:
        return 0.0
    return round((likes + favorites + comments) / plays * 100, 2)


def retention_cutoff_date(days: int) -> str:
    """N 天前的日期（YYYY-MM-DD），用于数据保留清理。"""
    return (datetime.date.today() - datetime.timedelta(days=days)).isoformat()
