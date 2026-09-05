"""媒体工具（R-033）：上传前用 ffmpeg 抽离音轨，只把音频送云端识别。

依赖 imageio-ffmpeg（自带静态 ffmpeg，无需系统安装）；转成 16k 单声道 wav，
体积小、兼容 FileTrans（其支持清单不含 .mov，抽成 wav 后无此问题）。
"""

from __future__ import annotations

import os
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
