"""硅基流动 ASR（R-108）：POST /v1/audio/transcriptions 直传音频转写。

与阿里云 FileTrans 不同：硅基流动无需公网 URL/OSS 中转，直接把音频文件
multipart 上传即可（OpenAI 兼容接口）。沿用 media_tools 抽音轨——视频先抽
16k 单声道 wav（几 MB），纯音频文件直传原文件。
平台限制：单文件 ≤50MB、时长 ≤1 小时；超限明确报错并提示切回阿里云，
**不自动切换其它服务商**（R-108 作者确认）。
"""

from __future__ import annotations

import mimetypes
import re
from pathlib import Path

import httpx

from ..config import get_settings
from .media_tools import extract_audio_to_wav, needs_audio_extraction, probe_duration_seconds
from .transcription import TranscriptionError

MAX_FILE_MB = 50  # 硅基流动单文件上限 50MB
MAX_DURATION_SECONDS = 3600  # 硅基流动单次时长上限 1 小时
DEFAULT_MODEL = "FunAudioLLM/SenseVoiceSmall"  # 硅基流动免费 ASR（R-108 二次切换）
# SenseVoice 输出自带事件标记（音乐/情绪表情、<|...|> 标签），对纯口播转写无意义，入库前清掉
_SENSEVOICE_EVENTS = ("🎼", "🎵", "🎶", "♪", "♫", "🎙️", "🎤", "😀", "😂", "😅", "😐", "😮", "😢", "🥲")


def _clean_sensevoice_text(text: str) -> str:
    """清理 SenseVoice 事件标记/标签，返回干净的转写文本。"""
    text = re.sub(r"<\|[^|]*\|>", "", text)
    for token in _SENSEVOICE_EVENTS:
        text = text.replace(token, "")
    return re.sub(r"\s+", " ", text).strip()


class SiliconFlowASR:
    def __init__(self, settings=None):
        self.settings = settings or get_settings()

    def transcribe_file(self, video_path: Path | str) -> str:
        """抽音轨(视频) → 校验平台限制 → 直传转写 → 返回文本。

        只把音频传上云：视频先用 ffmpeg 抽成 16k 单声道 wav，用完删除临时文件。
        """
        path = Path(video_path)
        if not path.is_file():
            raise TranscriptionError(f"视频不存在: {path}")
        extracted: Path | None = None
        upload_path = path
        if needs_audio_extraction(path):
            extracted = extract_audio_to_wav(path)
            upload_path = extracted
        try:
            self._check_limits(upload_path)
            return self._transcribe_upload(upload_path)
        finally:
            if extracted is not None:
                extracted.unlink(missing_ok=True)

    def _check_limits(self, upload_path: Path) -> None:
        """超限给明确错误（会走现有「转写失败」通知），不自动切其它服务商。"""
        size_mb = upload_path.stat().st_size / (1024 * 1024)
        if size_mb > MAX_FILE_MB:
            raise TranscriptionError(
                f"音频超过硅基流动单文件 {MAX_FILE_MB}MB 限制（当前约 {size_mb:.1f}MB，视频较长？）。"
                "请将 .env 的 ECHO_ASR_MODE 改回 aliyun 用阿里云转写"
            )
        seconds: float | None = None
        try:
            seconds = probe_duration_seconds(upload_path)
        except TranscriptionError:
            seconds = None  # 探不出时长（罕见格式）不阻断，文件大小限制仍在
        if seconds is not None and seconds > MAX_DURATION_SECONDS:
            raise TranscriptionError(
                f"音频时长超过硅基流动 1 小时限制（当前约 {seconds / 60:.0f} 分钟）。"
                "请将 .env 的 ECHO_ASR_MODE 改回 aliyun 用阿里云转写"
            )

    def _transcribe_upload(self, upload_path: Path) -> str:
        settings = self.settings
        api_key = (settings.siliconflow_api_key or "").strip()
        if not api_key:
            raise TranscriptionError("未配置硅基流动 ASR（需 .env 配 ECHO_SILICONFLOW_API_KEY）")
        model = (settings.siliconflow_asr_model or DEFAULT_MODEL).strip()
        base = (settings.siliconflow_base_url or "https://api.siliconflow.cn/v1").rstrip("/")
        url = f"{base}/audio/transcriptions"
        timeout = max(60, int(getattr(settings, "asr_poll_timeout", 0) or 3600))
        mime = mimetypes.guess_type(upload_path.name)[0] or "application/octet-stream"
        headers = {"Authorization": f"Bearer {api_key}"}
        data = {"model": model}
        with upload_path.open("rb") as fh:
            files = {"file": (upload_path.name, fh, mime)}
            try:
                resp = httpx.post(
                    url,
                    headers=headers,
                    files=files,
                    data=data,
                    timeout=httpx.Timeout(connect=15, read=timeout, write=120, pool=15),
                )
            except httpx.HTTPError as exc:
                raise TranscriptionError(f"硅基流动转写调用失败: {exc}") from exc
        if resp.status_code != 200:
            body = (resp.text or "").strip()[:300]
            raise TranscriptionError(
                f"硅基流动转写失败（HTTP {resp.status_code}）：{body or resp.reason_phrase}"
            )
        try:
            payload = resp.json()
        except ValueError:
            raise TranscriptionError(
                f"硅基流动返回无法解析: {(resp.text or '')[:200]!r}"
            ) from None
        text = (payload.get("text") or "").strip()
        if not text:
            # 与 R-094 文案兼容：ingest 会对「识别结果为空」追加可读原因
            raise TranscriptionError("识别结果为空（硅基流动：未识别到有效语音）")
        return _clean_sensevoice_text(text)
