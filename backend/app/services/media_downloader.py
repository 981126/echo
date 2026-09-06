"""平台视频流下载（R-077）：把数据源解析出的 mp4/dash 流式落盘。

- mp4 直链（抖音/小红书/个别 B站 durl）：httpx 流式下载，带平台防盗链头
- B站 DASH：视频/音频两条 m4s → ffmpeg 合并成 mp4（复用 media_tools 的 ffmpeg）
"""

from __future__ import annotations

import subprocess
import tempfile
import time
from pathlib import Path

import httpx

from .media_tools import _ffmpeg_exe
from .platform_assets import _cdn_headers

try:  # yt-dlp 为 B站直连兜底通道（R-078），缺失时仅 B站回落不可用
    import yt_dlp as _yt_dlp
except Exception:  # noqa: BLE001
    _yt_dlp = None

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
    """R-094：单文件整体超时兜底，卡住不再无限等待。"""
    deadline = time.monotonic() + 480  # 8 分钟无整体进展视为卡住
    try:
        with httpx.Client(follow_redirects=True, timeout=httpx.Timeout(connect=20, read=300, write=60, pool=20)) as client:
            with client.stream("GET", url, headers=headers) as resp:
                if resp.status_code not in (200, 206):
                    raise MediaDownloadError(f"HTTP {resp.status_code} 下载失败: {url[:140]}")
                with dest.open("wb") as f:
                    for chunk in resp.iter_bytes(chunk_size=65536):
                        if time.monotonic() > deadline:
                            raise MediaDownloadError("下载超时（长时间无进展），已中断，请重试")
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


# ---------- B站 yt-dlp 直连兜底（R-078） ----------

def _ffmpeg_dir_with_binary() -> str:
    """返回内含名为 ffmpeg 可执行文件的目录（imageio-ffmpeg 二进制名带平台后缀，
    yt-dlp 只认 ffmpeg/ffprobe，故用软链目录兜底）。"""
    exe = Path(_ffmpeg_exe())
    if exe.name == "ffmpeg" and exe.is_file():
        return str(exe.parent)
    link_dir = Path(tempfile.gettempdir()) / "echo-ffmpeg"
    link_dir.mkdir(parents=True, exist_ok=True)
    link = link_dir / "ffmpeg"
    if not link.exists():
        try:
            link.symlink_to(exe)
        except OSError:
            return str(exe.parent)
    return str(link_dir)


def download_bilibili_via_ytdlp(bvid: str, dest: Path, cookie: str = "") -> None:
    """用 yt-dlp 直连 B站：下载低清完整视频+音频并合并成 mp4 到 dest。

    失败（含 B站瞬时风控 412）会重试一次；仍失败抛 MediaDownloadError。
    """
    if _yt_dlp is None:
        raise MediaDownloadError("yt-dlp 未安装（pip install yt-dlp），B站兜底通道不可用")
    if not bvid:
        raise MediaDownloadError("缺少 BV 号，无法用 yt-dlp 下载")
    url = f"https://www.bilibili.com/video/{bvid}"
    stem = dest.with_suffix("")
    headers = {"User-Agent": _UA}
    if cookie:
        headers["Cookie"] = cookie
    opts = {
        "format": "bv*[height<=480]+ba/b",  # 480P 视频 + 音频，免登录；失败退整段
        "merge_output_format": "mp4",
        "outtmpl": str(stem),
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        "ffmpeg_location": _ffmpeg_dir_with_binary(),
        "http_headers": headers,
        "socket_timeout": 30,
    }
    last: Exception | None = None
    for attempt in (1, 2):
        try:
            with _yt_dlp.YoutubeDL(opts) as ydl:
                ydl.download([url])
            last = None
            break
        except Exception as exc:  # noqa: BLE001 yt-dlp 抛错类型繁杂，统一捕获重试
            last = exc
            if attempt == 1:
                time.sleep(4)
    if last is not None:
        raise MediaDownloadError(f"yt-dlp B站下载失败: {str(last)[:300]}")
    produced: Path | None = None
    for cand in stem.parent.glob(stem.name + ".*"):
        if not cand.is_file() or cand.name.startswith("."):
            continue
        if cand.suffix.lower() in (".part", ".ytdl", ".tmp") or ".f" in cand.name:
            continue
        if produced is None or cand.stat().st_size > produced.stat().st_size:
            produced = cand
    if produced is None:
        raise MediaDownloadError("yt-dlp 未产出文件")
    if produced != dest:
        produced.rename(dest)
    if not dest.is_file() or dest.stat().st_size < 1024:
        dest.unlink(missing_ok=True)
        raise MediaDownloadError("B站下载文件为空或过小")
