
"""纯逻辑（无第三方依赖）：流水线幂等键。"""

from __future__ import annotations

import datetime


def today_key() -> str:
    return datetime.date.today().isoformat()


def can_run(status: str | None) -> bool:
    """running 状态下不允许并发重跑；done 需 force 才重跑；failed 可直接重跑。"""
    return status != "running"
