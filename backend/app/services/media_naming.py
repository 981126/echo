"""媒体文件命名（R-058）：落盘文件名用「标题-封面 / 标题-视频」。

提供安全清理（去掉路径非法字符、控制长度、重名自动加 -2/-3），
上传/同步/改标题后统一调用，保证文件夹里一眼能认出是哪个素材。
"""

from __future__ import annotations

import re
from pathlib import Path

_ILLEGAL = re.compile(r'[\\/:*?"<>|\x00-\x1f]+')
_WS = re.compile(r"\s+")


def clean_component(text: str, limit: int = 40) -> str:
    """标题 → 可安全用作文件名的片段（保留中文/字母/数字/_-）。"""
    t = _WS.sub("_", str(text or "").strip())
    t = _ILLEGAL.sub("_", t)
    t = t.strip("._ ")
    t = re.sub(r"_+", "_", t)
    return (t[:limit] or "未命名").rstrip("._ ")


def unique_path(directory: Path, stem: str, ext: str) -> Path:
    """同目录下不重名：已存在则追加 -2、-3…"""
    ext = ext if ext.startswith(".") else f".{ext}"
    target = directory / f"{stem}{ext}"
    index = 2
    while target.exists():
        target = directory / f"{stem}-{index}{ext}"
        index += 1
    return target


def rename_to(path: Path, new_stem: str) -> str:
    """把文件改名为 new_stem + 原后缀（重名自动加后缀），返回新文件名。"""
    if not path.exists():
        return path.name
    ext = path.suffix or ""
    dest = unique_path(path.parent, new_stem, ext)
    path.replace(dest)
    return dest.name


PLATFORM_LABEL = {"douyin": "抖音", "bilibili": "B站", "xiaohongshu": "小红书"}
_TAG_RE = re.compile(r"[#＃][^\s#＃，,。！？!?、；;：:]*")


def clean_title(text: str, limit: int = 30) -> str:
    """标题清洗：去掉 #话题 等标签、非法字符，保留主标题。"""
    t = _TAG_RE.sub(" ", str(text or ""))
    t = _WS.sub(" ", t)
    t = _ILLEGAL.sub("_", t)
    t = t.strip("._ ")
    t = re.sub(r"[_\-]+", "_", t)
    return (t[:limit] or "未命名").rstrip("._ ")


def media_stem(platform: str, title: str, kind: str) -> str:
    """统一命名：{平台前缀}-{主标题}-{视频/封面}；无平台前缀则从主标题开始。"""
    label = PLATFORM_LABEL.get((platform or "").strip().lower(), "")
    parts = [label, clean_title(title), kind]
    return "-".join(x for x in parts if x)
