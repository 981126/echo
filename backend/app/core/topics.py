
"""纯逻辑（无第三方依赖）：赛道与平台规范化。"""

from __future__ import annotations

MAIN_TOPICS = ["求职", "面试", "赚钱", "知识", "其他"]
PLATFORMS = ["douyin", "bilibili", "xiaohongshu"]


def normalize_main_topic(value: str) -> str:
    """把任意输入归一化为主赛道之一（求职/面试/赚钱/知识/其他）。"""
    v = (value or "").strip()
    if not v:
        return "其他"
    for topic in MAIN_TOPICS:
        if topic in v or v in topic:
            return topic
    return "其他"


def is_valid_platform(value: str) -> bool:
    return (value or "").strip().lower() in PLATFORMS


def normalize_platform(value: str) -> str:
    v = (value or "").strip().lower()
    return v if v in PLATFORMS else ""


def normalize_platforms(values) -> list[str]:
    """把任意输入归一化为平台集合（去重、只保留合法项）。"""
    if isinstance(values, str):
        values = [values]
    out: list[str] = []
    for v in values or []:
        p = normalize_platform(str(v))
        if p and p not in out:
            out.append(p)
    return out


def normalize_topics(values) -> list[str]:
    """把任意输入归一化为赛道集合（去重；空项忽略）。"""
    if isinstance(values, str):
        values = [values]
    out: list[str] = []
    for v in values or []:
        s = str(v).strip()
        if not s:
            continue
        topic = normalize_main_topic(s)
        if topic not in out:
            out.append(topic)
    return out
