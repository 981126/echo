
"""纯逻辑（无第三方依赖）：流水线幂等键。"""

from __future__ import annotations

import datetime


def today_key() -> str:
    return datetime.date.today().isoformat()


def can_run(status: str | None) -> bool:
    """running 状态下不允许并发重跑；done 需 force 才重跑；failed 可直接重跑。"""
    return status != "running"


def is_stale(started_at, now=None, hours: int = 2) -> bool:
    """running 是否已超时（R-133）：超时视为卡死、允许重跑，避免永久阻塞后续流水线。"""
    if started_at is None:
        return True
    current = now or datetime.datetime.now()
    if isinstance(started_at, str):
        try:
            started_at = datetime.datetime.fromisoformat(started_at)
        except ValueError:
            return True
    return (current - started_at) >= datetime.timedelta(hours=hours)
