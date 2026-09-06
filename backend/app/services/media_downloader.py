"""平台视频流下载（R-077）：把数据源解析出的 mp4/dash 流式落盘。

- mp4 直链（抖音/小红书/个别 B站 durl）：httpx 流式下载，带平台防盗链头
- B站 DASH：视频/音频两条 m4s → ffmpeg 合并成 mp4（复用 media_tools 的 ffmpeg）
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import httpx

from .media_tools import _ffmpeg_exe
from .platform_assets import _cdn_headers

_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
)


class MediaDownloadError(RuntimeError):
    pass


def _headers(platform: str) -> dict:
    headers = dict(_cdn_headers(platform) or {})
    headers.setdefault("User-Agent", _UA)
    headers.setdefault("Accept", "*/*")
    headers.setdefault("Accept-Encoding", "identity")  # 避免压缩，方便流式写盘
    return headers


def _stream_to(url: str, headers: dict, dest: Path) -> None:
    try:
        with httpx.Client(follow_redirects=True, timeout=httpx.Timeout(30.0, read=600.0)) as client:
            with client.stream("GET", url, headers=headers) as resp:
                if resp.status_code not in (200, 206):
                    raise MediaDownloadError(f"HTTP {resp.status_code} 下载失败: {url[:140]}")
                with dest.open("wb") as f:
                    for chunk in resp.iter_bytes(chunk_size=65536):
                        f.write(chunk)
    except MediaDownloadError:
        dest.unlink(missing_ok=True)
        raise
    except httpx.HTTPError as exc:
        dest.unlink(missing_ok=True)
        raise MediaDownloadError(f"网络异常: {exc}") from exc
    if not dest.is_file() or dest.stat().st_size == 0:
        dest.unlink(missing_ok=True)
        raise MediaDownloadError("下载内容为空")


def download_platform_video(source: dict, platform: str, dest: Path) -> None:
    """按数据源结构下载到 dest（mp4 单文件 / B站 dash 合并）。失败抛 MediaDownloadError。"""
    kind = source.get("kind") or ""
    headers = _headers(platform)
    if kind == "mp4":
        urls = [u for u in (source.get("urls") or []) if u]
        if not urls:
            raise MediaDownloadError("数据源未返回视频地址")
        last: Exception | None = None
        for u in urls:
            try:
                _stream_to(u, headers, dest)
                return
            except MediaDownloadError as exc:
                last = exc  # 尝试下一个备用地址
        raise last or MediaDownloadError("无可用视频地址")
    if kind == "dash":
        vurl = source.get("video_url") or ""
        aurl = source.get("audio_url") or ""
        if not vurl or not aurl:
            raise MediaDownloadError("B站 DASH 数据不完整（缺视频/音频流）")
        v_tmp = dest.parent / f"{dest.name}.video.m4s"
        a_tmp = dest.parent / f"{dest.name}.audio.m4s"
        try:
            _stream_to(vurl, headers, v_tmp)
            _stream_to(aurl, headers, a_tmp)
            cmd = [
                _ffmpeg_exe(),
                "-y",
                "-i", str(v_tmp),
                "-i", str(a_tmp),
                "-c", "copy",
                str(dest),
            ]
            proc = subprocess.run(cmd, capture_output=True, timeout=1800)
            if proc.returncode != 0 or not dest.is_file() or dest.stat().st_size == 0:
                detail = (proc.stderr or b"").decode("utf-8", errors="ignore")[-300:]
                raise MediaDownloadError(f"ffmpeg 合并失败: {detail or '未知'}")
        except subprocess.TimeoutExpired as exc:
            raise MediaDownloadError("ffmpeg 合并超时") from exc
        except MediaDownloadError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise MediaDownloadError(f"B站下载/合并异常: {exc}") from exc
        finally:
            v_tmp.unlink(missing_ok=True)
            a_tmp.unlink(missing_ok=True)
        return
    raise MediaDownloadError(f"未知视频源类型: {kind or '空'}")
