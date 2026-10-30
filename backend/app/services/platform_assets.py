"""平台媒体资产工具（R-061-C）：图片识别/HEIC转换/封面与头像下载命名。

从 platform_sync.py 拆出，纯搬移，行为不变。
"""

from __future__ import annotations

import html
import uuid
from pathlib import Path

from ..config import get_settings
from ..core.http import get_client
from ..models.platform import CreatorAccount


def _img_ext(data: bytes) -> str | None:
    """按文件头识别图片真实格式；HEIC/未知格式返回 None（需转换或放弃）。"""
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return ".png"
    if data[:3] == b"\xff\xd8\xff":
        return ".jpg"
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return ".webp"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return ".gif"
    # HEIC/HEIF（苹果格式，浏览器不支持，需转 jpeg）
    if data[4:12] in (b"ftypheic", b"ftypheix", b"ftypmif1", b"ftypmsf1", b"ftyphevc"):
        return None
    return None


def _ensure_web_image(data: bytes) -> bytes | None:
    """把下载内容转成浏览器可渲染的图片（HEIC→JPEG），非图片返回 None。"""
    ext = _img_ext(data)
    if ext is not None:
        return data
    if data[4:12].startswith(b"ftyp"):
        return _heic_to_jpeg(data)
    return None


def _heic_to_jpeg(data: bytes) -> bytes | None:
    """macOS 用 sips 把 HEIC 转 JPEG；失败返回 None（走占位图）。"""
    import shutil
    import subprocess
    import tempfile

    if not shutil.which("sips"):
        return None
    try:
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "in.heic"
            dst = Path(tmp) / "out.jpg"
            src.write_bytes(data)
            proc = subprocess.run(
                ["sips", "-s", "format", "jpeg", "-s", "formatOptions", "85", str(src), "--out", str(dst)],
                capture_output=True,
                timeout=60,
            )
            if proc.returncode == 0 and dst.exists():
                return dst.read_bytes()
    except Exception:  # noqa: BLE001
        pass
    return None


def _cdn_headers(platform: str) -> dict:
    return {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36",
        "Referer": {"xiaohongshu": "https://www.xiaohongshu.com/", "douyin": "https://www.douyin.com/", "bilibili": "https://www.bilibili.com/"}.get(platform, ""),
    }


def _cover_path_for(platform: str, platform_post_id: str, title: str, cover_url: str) -> str:
    """返回本地封面文件名（下载真实封面或生成占位 SVG）。

    R-058：文件名用「标题-封面」（重名自动 -2/-3），文件夹里一眼可辨。
    注意：本函数只做文件 I/O，不持有数据库事务/锁。
    """

    from .media_naming import media_stem, unique_path

    settings = get_settings()
    settings.covers_dir.mkdir(parents=True, exist_ok=True)
    stem = media_stem(platform, title or platform_post_id, "封面")
    if cover_url:
        try:
            # R-241：共享 Client（cover/avatar 复用连接池），每次请求显式 8s 超时
            resp = get_client("cdn", timeout=8.0).get(
                cover_url, timeout=8.0, headers=_cdn_headers(platform)
            )
            if resp.status_code == 200 and resp.content:
                img = _ensure_web_image(resp.content)
                if img:
                    dest = unique_path(settings.covers_dir, stem, ".jpg")
                    dest.write_bytes(img)
                    # R-179：新封面立刻生成列表缩略图
                    from ..core import thumbs

                    thumbs.make_thumb(dest, thumbs.thumb_file(settings.covers_dir, dest.name, 400), 400)
                    return dest.name
        except Exception:  # noqa: BLE001  下载失败回退占位
            pass
    dest = unique_path(settings.covers_dir, stem, ".svg")
    label = {"douyin": "抖音", "xiaohongshu": "小红书", "bilibili": "B站"}.get(platform, platform)
    text = html.escape((title or "云端作品")[:26])
    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="480" height="270">'
        f'<rect width="480" height="270" fill="#f3ede4"/>'
        f'<text x="240" y="96" font-family="-apple-system,PingFang SC,sans-serif" font-size="26" fill="#a34f2c" text-anchor="middle">{label}</text>'
        f'<text x="240" y="150" font-family="-apple-system,PingFang SC,sans-serif" font-size="17" fill="#2b2823" text-anchor="middle">{text}</text>'
        f'</svg>'
    )
    dest.write_text(svg, encoding="utf-8")
    return dest.name


def _ensure_account_avatar(account: CreatorAccount, profile) -> str | None:
    """自动同步头像：有远端 URL 则下载本地；没有/失败返回 None。

    注意：本函数只做网络/文件 I/O，不持有数据库事务/锁；调用方自行在短事务里更新 avatar_path。
    """
    if account.avatar_path:
        return None
    if not profile.avatar_url:
        return None
    settings = get_settings()
    settings.covers_dir.mkdir(parents=True, exist_ok=True)
    name = f"avatar_{uuid.uuid4().hex[:12]}"
    try:
        resp = get_client("cdn", timeout=8.0).get(
            profile.avatar_url, timeout=8.0, headers=_cdn_headers(account.platform)
        )
        if resp.status_code == 200 and resp.content:
            img = _ensure_web_image(resp.content)
            if img:
                dest = settings.covers_dir / f"{name}.jpg"
                dest.write_bytes(img)
                return dest.name
    except Exception:  # noqa: BLE001 下载失败保持空，前端显示空圆框
        pass
    return None
