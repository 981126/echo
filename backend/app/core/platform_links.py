"""平台作品网页链接构造（R-035：编辑页展示三平台视频链接）。

同步侧不下载视频、video_url 多为空；用平台作品 id + 原始 JSON 中
的 bvid/share_url 等字段拼出可在浏览器打开的作品页链接。

R-179：列表页要处理几百条作品，逐条 `json.loads(raw)`（每条还解析两次）是纯浪费，
故拆出「已解析 raw」的入口 `build_platform_page_url_from_data` / `parse_raw` / `extract_data_field`，
原 `build_platform_page_url(platform, id, raw)` 行为不变（内部解析后委托）。
"""

from __future__ import annotations

import json
import re


def parse_raw(raw: str) -> dict:
    """解析 raw JSON（容错：坏 JSON → 空 dict），供一次解析多处复用。"""
    try:
        data = json.loads(raw or "{}")
    except (TypeError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def extract_data_field(data: dict, key: str) -> str:
    """从**已解析**的 raw 里取字符串字段；含嵌套一层容错（如 data/aweme_detail），与原来同语义。"""
    if isinstance(data.get(key), str):
        return data[key].strip()
    for value in data.values():
        if isinstance(value, dict) and isinstance(value.get(key), str):
            return value[key].strip()
    return ""


def extract_raw_field(raw: str, key: str) -> str:
    return extract_data_field(parse_raw(raw), key)


def build_platform_page_url(platform: str, platform_post_id: str, raw: str = "") -> str:
    """返回平台作品网页链接；无法构造时返回空串。"""
    return build_platform_page_url_from_data(platform, platform_post_id, parse_raw(raw))


def build_platform_page_url_from_data(platform: str, platform_post_id: str, data: dict) -> str:
    """同上，但接收**已解析**的 raw（列表页批量构造时用，省掉重复解析）。"""
    pid = (platform_post_id or "").strip()
    if platform == "bilibili":
        bvid = extract_data_field(data, "bvid")
        if not bvid:
            bvid = pid if pid.upper().startswith("BV") else ""
        if bvid:
            return f"https://www.bilibili.com/video/{bvid}"
        match = re.fullmatch(r"aid:(\d+)", pid)
        if match:
            return f"https://www.bilibili.com/video/av{match.group(1)}"
        return ""
    if platform == "douyin":
        share = extract_data_field(data, "share_url") or extract_data_field(data, "permalink")
        if share.startswith("http"):
            return share
        return f"https://www.douyin.com/video/{pid}" if pid else ""
    if platform == "xiaohongshu":
        share = extract_data_field(data, "share_url")
        if share.startswith("http"):
            return share
        return f"https://www.xiaohongshu.com/explore/{pid}" if pid else ""
    share = extract_data_field(data, "share_url")
    return share if share.startswith("http") else ""
