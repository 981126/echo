"""应用统一时间（默认北京时间 Asia/Shanghai，可用 ECHO_TIMEZONE 覆盖）。

SQLite DateTime 一律存“无时区的应用本地时间”（北京时间），展示即对；
避免用 datetime.utcnow 存 UTC 导致界面差 8 小时。
"""

from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo


def tz() -> ZoneInfo:
    from ..config import get_settings

    name = getattr(get_settings(), "timezone", None) or "Asia/Shanghai"
    try:
        return ZoneInfo(name)
    except Exception:  # noqa: BLE001 时区名非法时回落北京时间
        return ZoneInfo("Asia/Shanghai")


def now() -> datetime:
    """当前应用时区时间（naive，直接落库/展示）。"""
    return datetime.now(tz()).replace(tzinfo=None)


def today() -> date:
    return now().date()
