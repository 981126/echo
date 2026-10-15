"""R-226：标题话题（#标签）解析与清洗的统一实现。

- `extract_hashtags`：从任意文本里提取 #话题（去重、去纯平台词），供标签聚合使用。
- `strip_hashtags`：把标题里的 #话题 整段去掉并规整空格，供标题清洗使用。
"""

from __future__ import annotations

import re

# 匹配 #话题 / ＃话题：话题到空白或常见标点为止
_TAG_RE = re.compile(r"[#＃]([^\s#＃，。！？!?、]+)")
_SPACE_RE = re.compile(r"\s+")

# 纯平台词/无意义词：不作为标签
DEFAULT_SKIP = {
    "抖音",
    "douyin",
    "小红书",
    "xiaohongshu",
    "bilibili",
    "B站",
    "b站",
    "哔哩哔哩",
    "视频",
    "vlog",
    "话题",
    "tag",
}


def _clean_tag(raw: str) -> str:
    return raw.strip().replace("[话题]", "").replace("]", "").strip()


def extract_hashtags(*texts: str, skip: set[str] | None = None, limit: int = 20) -> list[str]:
    """从文本里提取 #话题：去重（精确）、去纯平台词，最多 limit 条。"""
    skip_set = DEFAULT_SKIP if skip is None else skip
    norm = {s.lower() for s in skip_set}
    out: list[str] = []
    for text in texts:
        for m in _TAG_RE.findall(text or ""):
            tag = _clean_tag(m)
            if tag and tag.lower() not in norm and tag not in out:
                out.append(tag)
            if len(out) >= limit:
                return out
    return out


def strip_hashtags(text: str) -> str:
    """去掉标题里的 #话题 整段并规整空格（含全角 ＃）；不处理其它空白字符。"""
    if not text or ("#" not in text and "＃" not in text):
        return (text or "").strip()
    cleaned = _TAG_RE.sub(" ", text)
    cleaned = _SPACE_RE.sub(" ", cleaned).strip()
    return cleaned.strip(" ，,、|｜")
