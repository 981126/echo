"""媒体工具（R-033）：上传前用 ffmpeg 抽离音轨，只把音频送云端识别。

依赖 imageio-ffmpeg（自带静态 ffmpeg，无需系统安装）；转成 16k 单声道 wav，
体积小、兼容 FileTrans（其支持清单不含 .mov，抽成 wav 后无此问题）。
"""

from __future__ import annotations

import os
import re
import subprocess
import tempfile
from pathlib import Path

from .transcription import TranscriptionError

AUDIO_SUFFIXES = {".wav", ".mp3", ".m4a", ".aac", ".ogg", ".flac", ".amr", ".wma"}
_FFMPEG: str | None = None


def _ffmpeg_exe() -> str:
    global _FFMPEG
    if _FFMPEG is None:
        try:
            import imageio_ffmpeg

            _FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()
        except Exception as exc:  # noqa: BLE001
            raise TranscriptionError(f"未找到 ffmpeg（imageio-ffmpeg）：{exc}") from exc
    return _FFMPEG


def needs_audio_extraction(path: Path) -> bool:
    """纯音频（wav/mp3/m4a/...）无需抽离；视频（mp4/mov/...）需抽音轨。"""
    return path.suffix.lower() not in AUDIO_SUFFIXES


def extract_audio_to_wav(video_path: Path | str) -> Path:
    """抽离音轨并转 16k 单声道 wav（返回临时文件，调用方负责删除）。"""
    src = Path(video_path)
    if not src.is_file():
        raise TranscriptionError(f"视频不存在: {src}")
    fd, tmp = tempfile.mkstemp(prefix="echo_asr_", suffix=".wav")
    os.close(fd)
    tmp_path = Path(tmp)
    try:
        cmd = [
            _ffmpeg_exe(),
            "-y",
            "-i",
            str(src),
            "-vn",
            "-ac",
            "1",
            "-ar",
            "16000",
            "-c:a",
            "pcm_s16le",
            str(tmp_path),
        ]
        proc = subprocess.run(cmd, capture_output=True, timeout=3600)
        if proc.returncode != 0 or not tmp_path.is_file() or tmp_path.stat().st_size == 0:
            detail = (proc.stderr or b"").decode("utf-8", errors="ignore")[-400:]
            raise TranscriptionError(f"音频抽离失败: {detail or '视频可能没有音轨'}")
        return tmp_path
    except subprocess.TimeoutExpired:
        raise TranscriptionError("音频抽离超时（视频过长？）") from None
    except TranscriptionError:
        tmp_path.unlink(missing_ok=True)
        raise
    except Exception as exc:  # noqa: BLE001
        tmp_path.unlink(missing_ok=True)
        raise TranscriptionError(f"音频抽离异常: {exc}") from exc


MP3_MIN_KBPS = 16
MP3_MAX_KBPS = 32


def extract_audio_compact(
    media_path: Path | str,
    *,
    max_bytes: int = 5 * 1024 * 1024,
    duration_seconds: float | None = None,
) -> tuple[Path, bool]:
    """为「本地音频 base64 直传」（R-200 腾讯云）准备 ≤ max_bytes 的音频。

    - 纯音频且体积已达标 → 原样返回 `(原文件, False)`（不重编码，保真）。
    - 视频或超限音频 → ffmpeg 抽/转为 16k 单声道 mp3，码率按目标大小**自适应**
      （16–32kbps，够长则取低）；返回 `(临时文件, True)`，调用方负责删除。
    - 探测不到时长时按 32kbps 处理；转完仍超限 → 明确报错（不自动切服务商）。
    """
    src = Path(media_path)
    if not src.is_file():
        raise TranscriptionError(f"媒体文件不存在: {src}")
    size = src.stat().st_size
    if src.suffix.lower() in AUDIO_SUFFIXES and size <= max_bytes:
        return src, False

    if duration_seconds is None:
        try:
            duration_seconds = probe_duration_seconds(src)
        except TranscriptionError:
            duration_seconds = None
    if duration_seconds and duration_seconds > 0:
        kbps = int((max_bytes * 8 / 1000) / duration_seconds)
    else:
        kbps = MP3_MAX_KBPS
    kbps = max(MP3_MIN_KBPS, min(kbps, MP3_MAX_KBPS))

    fd, tmp = tempfile.mkstemp(prefix="echo_asr_", suffix=".mp3")
    os.close(fd)
    tmp_path = Path(tmp)
    try:
        cmd = [
            _ffmpeg_exe(),
            "-y",
            "-i",
            str(src),
            "-vn",
            "-ac",
            "1",
            "-ar",
            "16000",
            "-c:a",
            "libmp3lame",
            "-b:a",
            f"{kbps}k",
            str(tmp_path),
        ]
        proc = subprocess.run(cmd, capture_output=True, timeout=3600)
        if proc.returncode != 0 or not tmp_path.is_file() or tmp_path.stat().st_size == 0:
            detail = (proc.stderr or b"").decode("utf-8", errors="ignore")[-400:]
            raise TranscriptionError(f"音频压缩失败: {detail or '视频可能没有音轨'}")
        if tmp_path.stat().st_size > max_bytes:
            limit_mb = max_bytes / (1024 * 1024)
            raise TranscriptionError(
                f"音频压缩后仍超过腾讯云本地直传上限 {limit_mb:.0f}MB"
                "（视频过长？请拆短或改用阿里云/硅基流动服务商）"
            )
        return tmp_path, True
    except TranscriptionError:
        tmp_path.unlink(missing_ok=True)
        raise
    except subprocess.TimeoutExpired:
        tmp_path.unlink(missing_ok=True)
        raise TranscriptionError("音频压缩超时（视频过长？）") from None
    except Exception as exc:  # noqa: BLE001
        tmp_path.unlink(missing_ok=True)
        raise TranscriptionError(f"音频压缩异常: {exc}") from exc


_DURATION_RE = re.compile(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)")

def probe_duration_seconds(path: Path | str) -> float:
    """用 ffmpeg 探测媒体时长（秒）。R-108：硅基流动限制单文件 ≤1 小时，先探测再上传。"""
    src = Path(path)
    if not src.is_file():
        raise TranscriptionError(f"媒体文件不存在: {src}")
    proc = subprocess.run(
        [_ffmpeg_exe(), "-i", str(src)], capture_output=True, timeout=120
    )
    text = (proc.stderr or b"").decode("utf-8", errors="ignore")
    m = _DURATION_RE.search(text)
    if not m:
        raise TranscriptionError(f"无法读取媒体时长: {src.name}")
    hours, minutes, seconds = int(m.group(1)), int(m.group(2)), float(m.group(3))
    return hours * 3600 + minutes * 60 + seconds
