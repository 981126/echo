"""腾讯云录音文件识别（R-200）：CreateRecTask + DescribeTaskStatus 轮询。

音频走**本地音频 base64 直传**（`SourceType=1`），腾讯限制单文件 ≤5MB：
视频先用 ffmpeg 抽/压成 16k 单声道 mp3（`media_tools.extract_audio_compact`，
码率按目标大小自适应），用完删除临时文件。
超限明确报错并走现有失败通知，**不自动切换其它服务商**（与 R-108 同口径）。

引擎类型（`EngineModelType`）由「AI 设置」运行时配置，默认大模型2.0 `16k_zh_en_2.0`。
"""

from __future__ import annotations

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
from .transcription import TranscriptionError

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


class TencentAsr:
    def __init__(self, settings=None, model: str | None = None):
        self.settings = settings or get_settings()
        # 引擎类型可由「AI 设置」运行时指定，保存即生效
        self.model = (model or "").strip()

    def transcribe_file(self, video_path: Path | str) -> str:
        """抽/压音频 → 本地 base64 直传 → 轮询结果 → 返回文本。"""
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

    def _transcribe_local(self, audio_path: Path) -> str:
        data = audio_path.read_bytes()
        if not data:
            raise TranscriptionError(f"音频为空文件: {audio_path}")
        client = self._client()
        params = {
            "EngineModelType": self._engine_model(),
            "ChannelNum": 1,  # 16k 引擎仅支持单声道
            "ResTextFormat": 0,  # 基础识别结果（含整段文本与分段句）
            "SourceType": 1,  # 音频数据（base64 post body）
            "Data": base64.b64encode(data).decode("ascii"),
            "DataLen": len(data),  # 未编码时的原始字节长度
        }
        task_id = self._create_task(client, params)
        return self._poll(client, task_id)

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
                text = self._extract_text(data)
                if not text:
                    raise TranscriptionError("识别成功但结果为空")
                return text
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
    def _sdk_error(prefix: str, exc: TencentCloudSDKException) -> str:
        code = exc.get_code() if hasattr(exc, "get_code") else ""
        message = exc.get_message() if hasattr(exc, "get_message") else str(exc)
        hint = _ERROR_HINTS.get(code or "", "")
        if hint:
            detail = f"{hint}（{message}）" if message else hint
        else:
            detail = message or code or "未知错误"
        return f"{prefix}: {detail}"
