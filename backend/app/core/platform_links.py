"""平台作品网页链接构造（R-035：编辑页展示三平台视频链接）。

同步侧不下载视频、video_url 多为空；用平台作品 id + 原始 JSON 中
的 bvid/share_url 等字段拼出可在浏览器打开的作品页链接。
"""

from __future__ import annotations

import json
import re


def extract_raw_field(raw: str, key: str) -> str:
    try:
        data = json.loads(raw or "{}")
    except (TypeError, ValueError):
        data = {}
    if isinstance(data, dict) and isinstance(data.get(key), str):
        return data[key].strip()
    # 容错：raw 可能是嵌套（如 data/aweme_detail），递归一层找字符串字段
    if isinstance(data, dict):
        for value in data.values():
            if isinstance(value, dict) and isinstance(value.get(key), str):
                return value[key].strip()
    return ""


def build_platform_page_url(platform: str, platform_post_id: str, raw: str = "") -> str:
    """返回平台作品网页链接；无法构造时返回空串。"""
    pid = (platform_post_id or "").strip()
    if platform == "bilibili":
        bvid = extract_raw_field(raw, "bvid")
        if not bvid:
            bvid = pid if pid.upper().startswith("BV") else ""
        if bvid:
            return f"https://www.bilibili.com/video/{bvid}"
        match = re.fullmatch(r"aid:(\d+)", pid)
        if match:
            return f"https://www.bilibili.com/video/av{match.group(1)}"
        return ""
    if platform == "douyin":
        share = extract_raw_field(raw, "share_url") or extract_raw_field(raw, "permalink")
        if share.startswith("http"):
            return share
        return f"https://www.douyin.com/video/{pid}" if pid else ""
    if platform == "xiaohongshu":
        share = extract_raw_field(raw, "share_url")
        if share.startswith("http"):
            return share
        return f"https://www.xiaohongshu.com/explore/{pid}" if pid else ""
    share = extract_raw_field(raw, "share_url")
    return share if share.startswith("http") else ""
