"""链接解析工具（纯逻辑 + 少量网络重定向）：从主页/作品分享链接解析平台 ID。

从 tikhub.py 拆出（R-061-C）：保持 parse_post_id / parse_link 等旧导入路径可用。
"""

from __future__ import annotations

import httpx


def parse_post_id(link: str) -> tuple[str, str]:
    """从作品分享链接解析 (platform, 作品ID)。支持抖音/B站/小红书常见形态。"""
    link = (link or "").strip()
    if not link:
        return "", ""
    low = link.lower()
    if "bilibili.com/video/" in low:
        marker = "/video/"
        idx = low.find(marker)
        tail = link[idx + len(marker):].split("?")[0].split("/")[0]
        if not tail:
            return "", ""
        low_tail = tail.lower()
        if low_tail.startswith("bv"):
            return "bilibili", f"bvid:{tail}"
        if low_tail.startswith("av") and tail[2:].isdigit():
            return "bilibili", f"aid:{tail[2:]}"
        return "bilibili", f"bvid:{tail}"
    if "douyin.com/video/" in low:
        marker = "/video/"
        idx = low.find(marker)
        tail = link[idx + len(marker):].split("?")[0].split("/")[0]
        return ("douyin", tail) if tail else ("", "")
    if "xiaohongshu.com/explore/" in low:
        marker = "/explore/"
        idx = low.find(marker)
        tail = link[idx + len(marker):].split("?")[0].split("/")[0]
        return ("xiaohongshu", tail) if tail else ("", "")
    if "xiaohongshu.com/discovery/item/" in low:
        marker = "/discovery/item/"
        idx = low.find(marker)
        tail = link[idx + len(marker):].split("?")[0].split("/")[0]
        return ("xiaohongshu", tail) if tail else ("", "")
    return "", ""


_SHORT_HOSTS = ("v.douyin.com", "xhslink.com", "b23.tv", "douyin.com", "xiaohongshu.com", "bilibili.com")


def _resolve_redirect(link: str) -> str:
    """分享短链解析：跟随重定向拿到真实主页 URL（失败返回原链接）。"""
    low = (link or "").lower()
    if not low.startswith(("http://", "https://")):
        return link
    if not any(h in low for h in _SHORT_HOSTS):
        return link
    try:
        resp = httpx.get(link, follow_redirects=True, timeout=12, headers={"User-Agent": "Mozilla/5.0"})
        return str(resp.url)
    except Exception:  # noqa: BLE001 无法联网/超时时原样返回，走本地规则
        return link


def _extract_after(link: str, marker: str) -> str:
    idx = link.find(marker)
    if idx < 0:
        return ""
    tail = link[idx + len(marker):]
    # 截断到 路径段结束 / ? # 空白
    out = ""
    for ch in tail:
        if ch in "/?# \t\r\n":
            break
        out += ch
    return out.strip()


def parse_link(platform: str, link: str) -> str:
    """从主页分享链接解析平台用户 ID。

    规则：先按完整 URL 结构解析；识别不了短链域名时跟随重定向后再解析；
    解析不出合法 ID 一律返回空（不返回乱码尾巴，避免存错 ID）。
    """
    link = _resolve_redirect((link or "").strip())
    if not link:
        return ""
    low = link.lower()
    if platform == "bilibili":
        marker = "space.bilibili.com/"
        if marker in low:
            tail = _extract_after(link, marker)
            return tail if tail.isdigit() else ""
        return ""
    if platform == "xiaohongshu":
        # 两种形态：/user/profile?userId=xxx 与 /user/profile/xxx
        if "userid=" in low:
            return _extract_after(link.split("userId=", 1)[1].split("&")[0], "")
        for marker in ("/user/profile/", "/user/"):
            if marker in low:
                uid = _extract_after(link, marker)
                if uid and len(uid) >= 6:
                    return uid
        return ""
    if platform == "douyin":
        marker = "douyin.com/user/"
        if marker in low:
            uid = _extract_after(link, marker)
            # sec_user_id 允许字母数字与 _- 等，但不能带 .html 之类
            if uid and not uid.lower().endswith((".html", ".do")):
                return uid
        # v.douyin.com 已重定向仍失败时
        return ""
    return ""
