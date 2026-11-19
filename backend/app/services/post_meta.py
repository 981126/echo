"""作品元信息解析与分诊（R-265）：时长、时长分桶、流量来源占比。

这里只做纯函数，不碰数据库，便于单测；调用方（同步/迁移/复盘）自己负责读写。
"""

from __future__ import annotations

import json
from typing import Any

# 一句话说明口径：区间左闭右开，`30-60` 表示 [30, 60)
DURATION_BUCKETS: tuple[tuple[int, str], ...] = ((30, "<30"), (60, "30-60"), (120, "60-120"))
LONG_VIDEO_SECONDS = 120
RECOMMENDED_MIN_RATIO = 0.5


def _millis_to_seconds(value: Any) -> int | None:
    """抖音两种 raw 都可能出现毫秒（>1000 视为毫秒）；非法值返回 None。"""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number <= 0:
        return None
    return round(number / 1000) if number > 1000 else int(number)


def parse_duration_seconds(raw: str | dict | None) -> int | None:
    """从作品 raw 解析时长（秒）。

    支持两种形态：
    - 创作者接口：`{"item": {"video_info": {"duration": "85774"}}}`（毫秒）
    - 公开接口：`{"duration": 147469}`（毫秒）
    """
    data: Any = raw
    if isinstance(raw, str):
        try:
            data = json.loads(raw or "{}")
        except (TypeError, ValueError):
            return None
    if not isinstance(data, dict):
        return None
    item = data.get("item") if isinstance(data.get("item"), dict) else data
    if not isinstance(item, dict):
        return None
    info = item.get("video_info")
    if isinstance(info, dict):
        seconds = _millis_to_seconds(info.get("duration"))
        if seconds:
            return seconds
    for key in ("duration", "video_duration"):
        seconds = _millis_to_seconds(item.get(key))
        if seconds:
            return seconds
    return None


def duration_bucket(seconds: int | None) -> str:
    """时长分桶：<30 / 30-60 / 60-120 / >120；未知返回空串（不参与分层）。"""
    if seconds is None or seconds < 0:
        return ""
    for upper, label in DURATION_BUCKETS:
        if seconds < upper:
            return label
    return ">120"


def recommended_ratio(traffic_sources: Any) -> float | None:
    """推荐流量占比：`[{name, ratio, keys}]` 中 name 含「推荐」或 keys 含 homepage_hot 的合计。"""
    items = traffic_sources
    if isinstance(traffic_sources, str):
        try:
            items = json.loads(traffic_sources or "[]")
        except (TypeError, ValueError):
            return None
    if not isinstance(items, list) or not items:
        return None
    total = 0.0
    for item in items:
        if not isinstance(item, dict):
            continue
        ratio = item.get("ratio")
        if not isinstance(ratio, (int, float)):
            continue
        raw_keys = item.get("keys")
        keys: list = raw_keys if isinstance(raw_keys, list) else []
        name = str(item.get("name") or "")
        if "推荐" in name or "homepage_hot" in keys:
            total += float(ratio)
    return round(min(1.0, total), 4)


def traffic_triage(traffic_sources: Any) -> dict:
    """流量分诊：unknown（无数据）/ limited（推荐 <50%）/ normal。"""
    ratio = recommended_ratio(traffic_sources)
    if ratio is None:
        return {"recommended_ratio": None, "level": "unknown"}
    level = "limited" if ratio < RECOMMENDED_MIN_RATIO else "normal"
    return {"recommended_ratio": ratio, "level": level}


def build_triage(
    duration_seconds: int | None,
    traffic_sources: Any,
    facts: dict[str, dict],
) -> dict:
    """复盘分诊快照：时长 + 流量结构 + 提示语（提示语只描述数据事实）。"""
    traffic = traffic_triage(traffic_sources)
    notes: list[str] = []
    if traffic["level"] == "limited":
        notes.append(
            f"推荐流量占比 {traffic['recommended_ratio'] * 100:.0f}%，低于一半；"
            "完播/留存偏低不能单独归因于文案"
        )
    finish5 = (facts.get("finish_5s_rate") or {}).get("state")
    finish = (facts.get("finish_rate") or {}).get("state")
    if duration_seconds and duration_seconds > LONG_VIDEO_SECONDS and finish == "low" and finish5 != "low":
        notes.append(
            f"时长 {duration_seconds} 秒，长视频完播天然更低，建议同时看平均播放占比"
        )
    return {
        "duration_seconds": duration_seconds,
        "duration_bucket": duration_bucket(duration_seconds),
        "duration_known": duration_seconds is not None,
        "traffic": traffic,
        "notes": notes,
    }
