
"""纯逻辑（无第三方依赖）：转写文本处理。"""

from __future__ import annotations

import re


def normalize_text(text: str) -> str:
    """规范化：全角空格转半角、压缩空白、去首尾。"""
    if not text:
        return ""
    text = text.replace("\u3000", " ")
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def estimate_duration_seconds(text: str, chars_per_second: float = 4.0) -> int:
    """按口播语速估算时长（中文约每秒 4 字）。"""
    n = len(normalize_text(text))
    return max(1, round(n / chars_per_second))


def split_sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[。！？!?；;])", normalize_text(text))
    return [p for p in parts if p.strip()]
