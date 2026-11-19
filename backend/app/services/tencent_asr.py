"""腾讯云录音文件识别（R-200）：CreateRecTask + DescribeTaskStatus 轮询。

音频走**本地音频 base64 直传**（`SourceType=1`），腾讯限制单文件 ≤5MB：
视频先用 ffmpeg 抽/压成 16k 单声道 mp3（`media_tools.extract_audio_compact`，
码率按目标大小自适应），用完删除临时文件。
超限明确报错并走现有失败通知，**不自动切换其它服务商**（与 R-108 同口径）。

引擎类型（`EngineModelType`）由「AI 设置」运行时配置，默认大模型2.0 `16k_zh_en_2.0`。
"""

from __future__ import annotations

import ast
import base64
import json
import re
import time
from pathlib import Path

from tencentcloud.asr.v20190614 import asr_client, models
from tencentcloud.common import credential
from tencentcloud.common.exception.tencent_cloud_sdk_exception import (
    TencentCloudSDKException,
)
from tencentcloud.common.profile.client_profile import ClientProfile
from tencentcloud.common.profile.http_profile import HttpProfile

from ..config import get_settings
from .media_tools import extract_audio_compact
from .transcription import TranscriptResult, TranscriptionError

DEFAULT_ENGINE_MODEL = "16k_zh_en_2.0"
DEFAULT_ENDPOINT = "asr.tencentcloudapi.com"
DEFAULT_REGION = "ap-guangzhou"
_RUNNING = {"waiting", "doing"}
_DONE_OK = {"success"}
_DONE_FAIL = {"failed"}
_STATUS_BY_CODE = {0: "waiting", 1: "doing", 2: "success", 3: "failed"}
_TIMESTAMP_RE = re.compile(r"^\s*\[[^\]]*\]\s*")
# 已知业务错误码 → 可读中文（未命中原样带出 Message）
_ERROR_HINTS = {
    "FailedOperation.UserNotRegistered": "腾讯云语音识别服务未开通，请先在腾讯云控制台开通",
    "FailedOperation.ServiceIsolate": "腾讯云账号欠费停服，请充值后重试",
    "FailedOperation.UserHasNoAmount": "腾讯云资源包已耗尽，请购买资源包或开通后付费",
    "FailedOperation.UserHasNoFreeAmount": "腾讯云资源包已耗尽，请购买资源包或开通后付费",
    "AuthFailure.InvalidAuthorization": "腾讯云鉴权失败，请检查 SecretId/SecretKey",
    "FailedOperation.CheckAuthInfoFailed": "腾讯云鉴权失败，请检查 SecretId/SecretKey",
}


_SENTENCE_SPLIT = re.compile(r"(?<=[。！？!?；;…])")
_PUNCT = re.compile(r"[\s。！？!?；;，,、…—“”\"'（）()：:]+")


def _num(value: object) -> float | None:
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def _words(item: dict) -> list[dict]:
    raw = item.get("Words")
    if isinstance(raw, str):
        try:
            raw = ast.literal_eval(raw)
        except (ValueError, SyntaxError):
            return []
    return [word for word in raw if isinstance(word, dict)] if isinstance(raw, list) else []


def _time_at(spans: list[tuple[int, int, float, float]], index: int, *, at_end: bool) -> float | None:
    for start, end, begin_ms, end_ms in spans:
        if start <= index < end:
            return end_ms if at_end else begin_ms
    return None


def _item_sentences(item: dict) -> list[tuple[str, int, int]]:
    """把一个 ResultDetail 段落拆成带毫秒区间的句子。"""
    text = str(item.get("FinalSentence") or "").strip()
    if not text:
        return []
    begin = _num(item.get("BeginTime") if item.get("BeginTime") is not None else item.get("StartMs"))
    end = _num(item.get("EndTime") if item.get("EndTime") is not None else item.get("EndMs"))
    if begin is None or end is None or end <= begin:
        return []
    parts = [part.strip() for part in _SENTENCE_SPLIT.split(text) if part.strip()]
    if not parts:
        return []

    spans: list[tuple[int, int, float, float]] = []
    word_text = ""
    for word in _words(item):
        token = str(word.get("Word") or "")
        if not token:
            continue
        start = len(word_text)
        word_text += token
        offset_start, offset_end = _num(word.get("OffsetStartMs")), _num(word.get("OffsetEndMs"))
        if offset_start is None or offset_end is None:
            continue
        spans.append((start, start + len(token), offset_start, offset_end))

    total_chars = sum(len(_PUNCT.sub("", part)) for part in parts) or 1
    cursor = begin
    out: list[tuple[str, int, int]] = []
    for part in parts:
        clean = _PUNCT.sub("", part)
        share = (end - begin) * len(clean) / total_chars if clean else 0.0
        start_ms = cursor
        finish_ms = cursor + share
        position = word_text.find(clean) if spans and clean else -1
        if position >= 0:
            mapped_start = _time_at(spans, position, at_end=False)
            mapped_end = _time_at(spans, position + len(clean) - 1, at_end=True)
            if mapped_start is not None:
                start_ms = begin + mapped_start
            if mapped_end is not None:
                finish_ms = begin + mapped_end
        start_ms = max(begin, min(start_ms, end))
        finish_ms = max(start_ms, min(finish_ms, end))
        out.append((part, int(round(start_ms)), int(round(finish_ms))))
        cursor = finish_ms
    return out


class TencentAsr:
    def __init__(self, settings=None, model: str | None = None):
        self.settings = settings or get_settings()
        # 引擎类型可由「AI 设置」运行时指定，保存即生效
        self.model = (model or "").strip()

    def transcribe_file(self, video_path: Path | str) -> str:
        """抽/压音频 → 本地 base64 直传 → 轮询结果 → 返回文本。"""
        return self.transcribe_detailed(video_path).text

    def transcribe_detailed(self, video_path: Path | str) -> TranscriptResult:
        """R-265：额外返回 `ResultDetail` 的分句时间轴（毫秒）。"""
        path = Path(video_path)
        if not path.is_file():
            raise TranscriptionError(f"视频不存在: {path}")
        limit_mb = int(getattr(self.settings, "tencent_asr_max_audio_mb", 0) or 5) or 5
        prepared, is_temp = extract_audio_compact(path, max_bytes=limit_mb * 1024 * 1024)
        try:
            return self._transcribe_local(prepared)
        finally:
            if is_temp:
                prepared.unlink(missing_ok=True)

    def _transcribe_local(self, audio_path: Path) -> TranscriptResult:
        data = audio_path.read_bytes()
        if not data:
            raise TranscriptionError(f"音频为空文件: {audio_path}")
        client = self._client()
        params = {
            "EngineModelType": self._engine_model(),
            "ChannelNum": 1,  # 16k 引擎仅支持单声道
            # R-265：1=基础识别结果（含 ResultDetail 分句+毫秒时间戳）；0 只有带 [起,止] 标记的整段文本
            "ResTextFormat": 1,
            "SourceType": 1,  # 音频数据（base64 post body）
            "Data": base64.b64encode(data).decode("ascii"),
            "DataLen": len(data),  # 未编码时的原始字节长度
        }
        task_id = self._create_task(client, params)
        payload = self._poll_payload(client, task_id)
        sentences = self._extract_sentences(payload)
        return TranscriptResult(
            text=self._extract_text(payload),
            sentences=sentences,
            source="tencent",
            precision="sentence" if sentences else "none",
        )

    def _client(self):
        settings = self.settings
        secret_id = (settings.tencent_asr_secret_id or "").strip()
        secret_key = (settings.tencent_asr_secret_key or "").strip()
        if not (secret_id and secret_key):
            raise TranscriptionError(
                "未配置腾讯云 ASR（需 .env 配 ECHO_TENCENT_ASR_SECRET_ID / ECHO_TENCENT_ASR_SECRET_KEY）"
            )
        region = (settings.tencent_asr_region or DEFAULT_REGION).strip()
        http_profile = HttpProfile()
        http_profile.endpoint = (settings.tencent_asr_endpoint or DEFAULT_ENDPOINT).strip()
        http_profile.reqTimeout = 60
        client_profile = ClientProfile()
        client_profile.httpProfile = http_profile
        return asr_client.AsrClient(credential.Credential(secret_id, secret_key), region, client_profile)

    def _engine_model(self) -> str:
        return (
            self.model
            or getattr(self.settings, "tencent_asr_engine_model", "")
            or DEFAULT_ENGINE_MODEL
        ).strip()

    def _create_task(self, client, params: dict) -> int:
        request = models.CreateRecTaskRequest()
        request.from_json_string(json.dumps(params, ensure_ascii=False))
        try:
            response = client.CreateRecTask(request)
        except TencentCloudSDKException as exc:
            raise TranscriptionError(self._sdk_error("提交转写任务失败", exc)) from exc
        payload = json.loads(response.to_json_string())
        task_id = (payload.get("Data") or {}).get("TaskId")
        if task_id in (None, ""):
            raise TranscriptionError(f"提交转写任务失败: {payload}")
        return int(task_id)

    def _describe(self, client, task_id: int) -> dict:
        request = models.DescribeTaskStatusRequest()
        request.from_json_string(json.dumps({"TaskId": task_id}))
        try:
            response = client.DescribeTaskStatus(request)
        except TencentCloudSDKException as exc:
            raise TranscriptionError(self._sdk_error("查询转写结果失败", exc)) from exc
        payload = json.loads(response.to_json_string())
        return payload.get("Data") or {}

    def _poll(self, client, task_id: int) -> str:
        return self._extract_text(self._poll_payload(client, task_id))

    def _poll_payload(self, client, task_id: int) -> dict:
        interval = max(5, int(getattr(self.settings, "asr_poll_interval", 0) or 15))
        timeout = max(60, int(getattr(self.settings, "asr_poll_timeout", 0) or 3600))
        deadline = time.time() + timeout
        while True:
            data = self._describe(client, task_id)
            status = str(data.get("StatusStr") or "").strip().lower()
            if not status:
                code = data.get("Status")
                status = _STATUS_BY_CODE.get(code if isinstance(code, int) else -1, "")
            if status in _DONE_OK:
                if not self._extract_text(data):
                    raise TranscriptionError("识别成功但结果为空")
                return data
            if status in _DONE_FAIL:
                msg = str(data.get("ErrorMsg") or "").strip() or "任务失败"
                raise TranscriptionError(f"腾讯云转写失败: {msg}")
            if status not in _RUNNING:
                raise TranscriptionError(f"腾讯云转写任务异常: {data}")
            if time.time() >= deadline:
                raise TranscriptionError(
                    "腾讯云转写等待超时，可在素材详情稍后重试（任务可能仍在服务端处理）"
                )
            time.sleep(interval)

    @staticmethod
    def _extract_text(data: dict) -> str:
        """优先分段句（干净）；无分段则取整段 Result 并剥离 `[起,止]` 时间戳。"""
        details = data.get("ResultDetail") or []
        sentences = [
            str(item.get("FinalSentence") or "").strip()
            for item in details
            if isinstance(item, dict)
        ]
        text = "".join(s for s in sentences if s).strip()
        if text:
            return text
        lines: list[str] = []
        for raw in str(data.get("Result") or "").splitlines():
            line = _TIMESTAMP_RE.sub("", raw.strip()).strip()
            if line:
                lines.append(line)
        return "\n".join(lines)

    @staticmethod
    def _extract_sentences(data: dict) -> list[dict]:
        """ResultDetail → [{start_ms,end_ms,text}]（毫秒）。

        大模型引擎的 `FinalSentence` 是整段（一段可含几十秒），`Words` 才带逐词相对偏移，
        所以按中文标点分句后，用词级偏移把每句映射回真实时间；词对不上时按字数比例分摊。
        兼容老引擎的 `BeginTime/EndTime`（毫秒）。
        """
        sentences: list[dict] = []
        for item in data.get("ResultDetail") or []:
            if not isinstance(item, dict):
                continue
            for text, start_ms, end_ms in _item_sentences(item):
                if end_ms > start_ms:
                    sentences.append({"start_ms": start_ms, "end_ms": end_ms, "text": text})
        return sentences

    @staticmethod
    def _sdk_error(prefix: str, exc: TencentCloudSDKException) -> str:
        code = exc.get_code() if hasattr(exc, "get_code") else ""
        message = exc.get_message() if hasattr(exc, "get_message") else str(exc)
        hint = _ERROR_HINTS.get(code or "", "")
        if hint:
            detail = f"{hint}（{message}）" if message else hint
        else:
            detail = message or code or "未知错误"
        return f"{prefix}: {detail}"
