"""R-265：为「已有转写正文」的视频补句子时间轴。

只写 `transcripts.sentences` / `timeline_source` / `timeline_precision`，
**不覆盖** `transcript_text`、`corrected_text`、`asr_*`。失败只返回原因，不抛异常。
"""

from __future__ import annotations

import json

from sqlalchemy.orm import Session

from ..config import get_settings
from ..models.video import Transcript, Video
from .transcription import Transcriber, TranscriptionError


def ensure_sentences(db: Session, video: Video, *, mode: str | None = None) -> tuple[bool, str]:
    """补齐分句时间轴；返回 (是否已有句子级时间轴, 失败原因)。"""
    transcript: Transcript | None = video.transcript
    if transcript is None:
        return False, "视频没有转写记录"
    if transcript.timeline_precision == "sentence" and transcript.sentences not in ("", "[]", None):
        return True, ""

    settings = get_settings()
    path = settings.videos_dir / video.filename if video.filename else None
    if not video.filename or path is None or not path.is_file():
        return False, "本地视频文件缺失"

    wants = (mode or settings.timeline_asr_mode or "tencent").strip().lower()
    try:
        result = Transcriber(settings, mode=wants).transcribe_detailed(path)
    except TranscriptionError as exc:
        return False, str(exc)
    except Exception as exc:  # noqa: BLE001 时间轴补齐失败不能拖垮复盘
        return False, f"{type(exc).__name__}: {exc}"

    if result.precision != "sentence" or not result.sentences:
        return False, f"{wants} 未返回分句时间轴"
    transcript.sentences = json.dumps(result.sentences, ensure_ascii=False)
    transcript.timeline_source = result.source or wants
    transcript.timeline_precision = "sentence"
    db.commit()
    return True, ""
