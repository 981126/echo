"""DeepSeek 语音识别（R-264）：POST /v1/tools/asr 逐片转写 + 静音优先切点。

接口限制（官方文档）：单请求 ≤120 秒 / ≤8 MiB、仅 16-bit PCM WAV / Ogg Opus、
不支持流式。项目素材中位数 2.8 分钟，约 2/3 超过 120 秒，因此必须分片。

分片规则（详见 `development-design/R-264-deepseek-asr-default.md`）：
- 统一抽/转 16k 单声道 PCM WAV；
- 每片目标 110s、硬上限 118s、最短 60s，不重叠（按秒计费不重复）；
- 用 ffmpeg `astats` 逐 50ms 帧分析 RMS，在 [start+60s, start+118s] 窗口内优先取
  「RMS ≤ -35dB 且持续 ≥80ms」的静音段中点（最贴近 110s）；没有则取窗口内最安静帧中心；
- 分析失败才硬切 110s 并记 warning（自降级，不阻断转写）；绝不随机硬切截字。

失败口径沿用 R-108/R-200：明确中文报错、走既有失败通知/退避，**不自动切换其它服务商**。
"""

from __future__ import annotations

import re
import time
from pathlib import Path

import httpx

from ..config import get_settings
from ..core.log import get_logger
from .media_tools import audio_rms_frames, cut_wav_segments, extract_audio_to_wav, probe_duration_seconds
from .transcription import TranscriptResult, TranscriptionError

log = get_logger("deepseek_asr")

DEFAULT_URL = "https://api.deepseek.com/v1/tools/asr"
MAX_REQUEST_MB = 8  # 官方单文件上限 8 MiB
MIN_SEGMENT_SECONDS = 60.0  # 最短片长（窗口下界）
FRAME_SECONDS = 0.05  # 与 media_tools.audio_rms_frames 默认 50ms 帧一致
SILENCE_DB = -35.0  # 静音阈值（实测 90% 长素材窗口内可命中干净停顿）
SILENCE_MIN_SECONDS = 0.08  # 静音最短时长（避免切进塞音闭塞、截到辅音）
_RETRY_STATUS = {429, 503, 504}
_RETRY_BACKOFF = (2.0, 5.0, 10.0)
_ASCII_ALNUM = re.compile(r"[A-Za-z0-9]")


def _int_setting(settings: object, name: str, default: int, *, low: int, high: int) -> int:
    """读取整数配置并钳制区间；缺失/非整数（如测试里的 MagicMock）回落默认值。"""
    raw = getattr(settings, name, default)
    try:
        value = int(raw)
    except (TypeError, ValueError):
        value = default
    return max(low, min(high, value))


def _quiet_runs(window: list[tuple[float, float]]) -> list[list[tuple[float, float]]]:
    """把窗口内连续的静音帧分组（帧序列按时间排序且连续）。"""
    runs: list[list[tuple[float, float]]] = []
    current: list[tuple[float, float]] = []
    for frame in window:
        if frame[1] <= SILENCE_DB:
            current.append(frame)
        elif current:
            runs.append(current)
            current = []
    if current:
        runs.append(current)
    return runs


def _pick_cut(
    frames: list[tuple[float, float]], low: float, high: float, target: float
) -> tuple[float, str]:
    """在 [low, high] 窗口内选切点：静音段中点 → 最安静帧 → 硬切（降级）。

    返回 (切点秒, 来源)；来源用于日志与验收（silence / quietest / hard）。
    """
    window = [(t, v) for t, v in frames if low <= t <= high]
    if not window:
        return target, "hard"
    candidates: list[tuple[float, int, float]] = []
    for run in _quiet_runs(window):
        if len(run) * FRAME_SECONDS + 1e-9 < SILENCE_MIN_SECONDS:
            continue
        mid = (run[0][0] + run[-1][0] + FRAME_SECONDS) / 2.0
        candidates.append((abs(mid - target), -len(run), mid))
    if candidates:
        candidates.sort()
        return candidates[0][2], "silence"
    quietest = min(window, key=lambda item: item[1])
    return quietest[0] + FRAME_SECONDS / 2.0, "quietest"


def _plan_cuts(
    duration: float,
    frames: list[tuple[float, float]],
    *,
    target_seconds: float,
    max_seconds: float,
    min_seconds: float = MIN_SEGMENT_SECONDS,
) -> list[tuple[float, float, str]]:
    """规划切片 [(start, end, cut_source)]；总长与 duration 一致、首尾相接不重叠。

    ≤ max_seconds 时单片直传（source=single）；否则贪心切：每片长度落在
    [min_seconds, max_seconds]，最后一片自然到结尾（tail）。
    """
    if duration <= 0:
        return []
    if duration <= max_seconds:
        return [(0.0, duration, "single")]
    cuts: list[tuple[float, float, str]] = []
    start = 0.0
    while duration - start > max_seconds:
        low = start + min_seconds
        high = start + max_seconds
        cut, source = _pick_cut(frames, low, high, start + target_seconds)
        if cut <= start:
            cut, source = start + target_seconds, "hard"
        cut = min(cut, duration)
        cuts.append((start, cut, source))
        start = cut
    if duration - start > 0.01:
        cuts.append((start, duration, "tail"))
    return cuts


def _join_texts(texts: list[str]) -> str:
    """按顺序拼接分片文本：中文直接相连，英文/数字相邻处补一个空格；不补标点。"""
    parts = [text.strip() for text in texts if text and text.strip()]
    if not parts:
        return ""
    merged = parts[0]
    for part in parts[1:]:
        if _ASCII_ALNUM.match(merged[-1]) and _ASCII_ALNUM.match(part[0]):
            merged = f"{merged} {part}"
        else:
            merged = merged + part
    return merged


def _short_body(text: str, limit: int = 300) -> str:
    return (text or "").strip()[:limit]


class DeepSeekAsr:
    """DeepSeek ASR 实现：抽轨 → 时长/音量分析 → 静音优先切片 → 逐片转写 → 顺序拼接。"""

    def __init__(self, settings=None):
        self.settings = settings or get_settings()

    def transcribe_file(self, video_path: Path | str) -> str:
        return self.transcribe_detailed(video_path).text

    def transcribe_detailed(self, video_path: Path | str) -> TranscriptResult:
        """R-265：额外返回分片窗口（DeepSeek 无分句，precision=chunk）。"""
        path = Path(video_path)
        if not path.is_file():
            raise TranscriptionError(f"视频不存在: {path}")
        api_key = str(getattr(self.settings, "deepseek_api_key", "") or "").strip()
        if not api_key:
            raise TranscriptionError("未配置 DeepSeek ASR（需 .env 配 ECHO_DEEPSEEK_API_KEY）")
        url = self._url()
        wav: Path | None = None
        segments: list[Path] = []
        try:
            wav = extract_audio_to_wav(path)
            duration = probe_duration_seconds(wav)
            max_total = _int_setting(
                self.settings, "deepseek_asr_max_total_seconds", 7200, low=1, high=24 * 3600
            )
            if duration > max_total:
                raise TranscriptionError(
                    f"素材时长约 {duration / 60:.0f} 分钟，超过 DeepSeek 转写上限 "
                    f"{max_total / 3600:.0f} 小时（请拆分素材或改用其它服务商）"
                )
            target, hard = self._chunk_params()
            frames = audio_rms_frames(wav)
            cuts = _plan_cuts(
                duration, frames, target_seconds=target, max_seconds=hard
            )
            if not cuts:
                raise TranscriptionError("音频为空（时长 0 秒）")
            log.info(
                "deepseek_asr plan: duration=%.1fs segments=%d sources=%s",
                duration,
                len(cuts),
                ",".join(cut[2] for cut in cuts),
            )
            segments = cut_wav_segments(wav, [(start, end) for start, end, _ in cuts])
            texts: list[str] = []
            for index, ((start, end, source), segment) in enumerate(
                zip(cuts, segments, strict=True), start=1
            ):
                log.info(
                    "deepseek_asr segment %d/%d %.2f-%.2fs source=%s",
                    index,
                    len(cuts),
                    start,
                    end,
                    source,
                )
                texts.append(self._post_segment(url, api_key, segment, index, len(cuts)))
            text = _join_texts(texts)
            if not text:
                raise TranscriptionError("识别结果为空（DeepSeek：未识别到有效语音）")
            sentences = [
                {"start_ms": int(round(start * 1000)), "end_ms": int(round(end * 1000)), "text": piece}
                for (start, end, _source), piece in zip(cuts, texts, strict=True)
                if piece.strip()
            ]
            return TranscriptResult(
                text=text, sentences=sentences, source="deepseek", precision="chunk"
            )
        finally:
            for segment in segments:
                segment.unlink(missing_ok=True)
            if wav is not None:
                wav.unlink(missing_ok=True)

    def _url(self) -> str:
        raw = str(getattr(self.settings, "deepseek_asr_url", "") or "").strip()
        return raw or DEFAULT_URL

    def _chunk_params(self) -> tuple[float, float]:
        hard = _int_setting(
            self.settings, "deepseek_asr_chunk_max_seconds", 118, low=60, high=120
        )
        target = _int_setting(
            self.settings, "deepseek_asr_chunk_seconds", 110, low=int(MIN_SEGMENT_SECONDS), high=hard
        )
        return float(target), float(hard)

    def _max_bytes(self) -> int:
        mb = _int_setting(self.settings, "deepseek_asr_max_request_mb", MAX_REQUEST_MB, low=1, high=64)
        return mb * 1024 * 1024

    def _retries(self) -> int:
        return _int_setting(self.settings, "deepseek_asr_retries", 3, low=0, high=10)

    def _post_segment(self, url: str, api_key: str, audio: Path, index: int, total: int) -> str:
        """上传单片并返回文本；429/503/504 与网络异常退避重试，其它错误立即可读报错。"""
        limit = self._max_bytes()
        size = audio.stat().st_size
        if size > limit:
            raise TranscriptionError(
                f"第 {index}/{total} 片音频 {size / 1048576:.1f}MB 超过 DeepSeek "
                f"{limit // 1048576}MiB 限制"
            )
        headers = {"Authorization": f"Bearer {api_key}"}
        attempts = self._retries() + 1
        timeout = httpx.Timeout(connect=15, read=180, write=120, pool=15)
        for attempt in range(1, attempts + 1):
            try:
                with audio.open("rb") as fh:
                    resp = httpx.post(
                        url,
                        headers=headers,
                        files={"file": (audio.name, fh, "audio/wav")},
                        timeout=timeout,
                    )
            except httpx.HTTPError as exc:
                if attempt < attempts:
                    self._sleep(attempt)
                    continue
                raise TranscriptionError(
                    f"DeepSeek 转写调用失败（第 {index}/{total} 片）：{exc}"
                ) from exc
            if resp.status_code == 200:
                return self._parse_text(resp, index, total)
            if resp.status_code in _RETRY_STATUS:
                if attempt < attempts:
                    log.warning(
                        "deepseek_asr retry %d/%d status=%d segment=%d/%d",
                        attempt,
                        attempts - 1,
                        resp.status_code,
                        index,
                        total,
                    )
                    self._sleep(attempt)
                    continue
                raise TranscriptionError(
                    self._retry_exhausted(resp.status_code, resp.text, index, total, attempts - 1)
                )
            raise TranscriptionError(self._error_message(resp.status_code, resp.text, index, total))
        raise TranscriptionError(f"DeepSeek 转写失败（第 {index}/{total} 片）")

    @staticmethod
    def _sleep(attempt: int) -> None:
        time.sleep(_RETRY_BACKOFF[min(attempt - 1, len(_RETRY_BACKOFF) - 1)])

    @staticmethod
    def _parse_text(resp: httpx.Response, index: int, total: int) -> str:
        try:
            payload = resp.json()
        except ValueError:
            raise TranscriptionError(
                f"DeepSeek 返回无法解析（第 {index}/{total} 片）：{_short_body(resp.text, 200)}"
            ) from None
        text = str((payload or {}).get("text") or "").strip()
        duration_ms = (payload or {}).get("duration_ms")
        if isinstance(duration_ms, (int, float)):
            log.info(
                "deepseek_asr segment %d/%d ok duration_ms=%d chars=%d",
                index,
                total,
                int(duration_ms),
                len(text),
            )
        return text

    @staticmethod
    def _error_message(status: int, body: str, index: int, total: int) -> str:
        detail = _short_body(body, 120)
        if status in (401, 403):
            return "DeepSeek 鉴权失败，请检查 .env 的 ECHO_DEEPSEEK_API_KEY"
        if status == 400:
            return (
                f"DeepSeek 转写失败（第 {index}/{total} 片）：音频格式或请求字段不合法"
                + (f"（{detail}）" if detail else "")
            )
        if status == 408:
            return f"音频上传超时（第 {index}/{total} 片），请重试"
        if status == 413:
            return f"第 {index}/{total} 片音频超过 DeepSeek 8MiB 限制"
        return f"DeepSeek 转写失败（HTTP {status}，第 {index}/{total} 片）：{_short_body(body)}"

    @staticmethod
    def _retry_exhausted(status: int, body: str, index: int, total: int, retries: int) -> str:
        if status == 429:
            return f"DeepSeek 限流（第 {index}/{total} 片），已重试 {retries} 次"
        if status == 503:
            return f"DeepSeek 服务繁忙（第 {index}/{total} 片），已重试 {retries} 次"
        if status == 504:
            return f"DeepSeek 识别超时（第 {index}/{total} 片），已重试 {retries} 次"
        return (
            f"DeepSeek 转写失败（HTTP {status}，第 {index}/{total} 片），"
            f"已重试 {retries} 次：{_short_body(body)}"
        )
