"""阿里云录音文件识别（FileTrans）REST 客户端。

说明：本实现基于阿里云公开的 FileTrans API（SubmitTask + GetResult），
签名算法见 app/core/signature.py。首次接入真实密钥时需在 NAS 上联调验证
（mock 模式已覆盖开发与测试，不影响日常流程）。

提交任务：POST https://filetrans.cn-shanghai.aliyuncs.com/api/v2/batch_submit_task
查询结果：POST https://filetrans.cn-shanghai.aliyuncs.com/api/v2/batch_get_task_result
"""

from __future__ import annotations

import json
from pathlib import Path

import httpx

from ..config import get_settings
from ..core.signature import (
    build_canonicalized_query,
    build_string_to_sign,
    hmac_sha1_sign,
    utcnow_rfc1123,
)
from .transcription import TranscriptionError

HOST = "https://filetrans.cn-shanghai.aliyuncs.com"
SUBMIT_PATH = "/api/v2/batch_submit_task"
RESULT_PATH = "/api/v2/batch_get_task_result"
ACCEPT = "application/json"
CONTENT_TYPE = "application/json"


class AliyunFileTrans:
    def __init__(self, settings=None):
        self.settings = settings or get_settings()

    def _headers(self, date: str, body: bytes) -> dict:
        settings = self.settings
        params = {
            "appkey": settings.aliyun_asr_app_key,
            "version": "2.0",
        }
        canonicalized_resource = f"{SUBMIT_PATH}?{build_canonicalized_query(params)}"
        string_to_sign = build_string_to_sign(
            method="POST",
            accept=ACCEPT,
            body=body,
            content_type=CONTENT_TYPE,
            date=date,
            canonicalized_headers="",
            canonicalized_resource=canonicalized_resource,
        )
        signature = hmac_sha1_sign(settings.aliyun_asr_access_key_secret, string_to_sign)
        return {
            "Accept": ACCEPT,
            "Content-Type": CONTENT_TYPE,
            "Date": date,
            "Authorization": f"acs {settings.aliyun_asr_access_key_id}:{signature}",
        }

    def _post(self, path: str, body: dict) -> dict:
        payload = self.settings
        if not (payload.aliyun_asr_access_key_id and payload.aliyun_asr_access_key_secret):
            raise TranscriptionError("未配置阿里云 ASR 密钥")
        body_bytes = json.dumps(body).encode("utf-8")
        date = utcnow_rfc1123()
        url = f"{HOST}{path}"
        with httpx.Client(timeout=60) as client:
            resp = client.post(url, content=body_bytes, headers=self._headers(date, body_bytes))
            resp.raise_for_status()
            return resp.json()

    def submit_task(self, file_url: str) -> str:
        result = self._post(SUBMIT_PATH, {"file_link": file_url})
        task_id = result.get("TaskId") or result.get("task_id")
        if not task_id:
            raise TranscriptionError(f"提交任务失败: {result}")
        return task_id

    def get_result(self, task_id: str) -> dict:
        return self._post(RESULT_PATH, {"task_id": task_id})

    def transcribe_file(self, video_path: Path | str) -> str:
        """真实接入时需先把视频传到 OSS 或公网可访问地址，再提交 file_link。
        当前实现直接使用 file:// 会失败，因此这里抛错提示接入方式。"""
        raise TranscriptionError(
            "aliyun 模式联调占位：请先上传视频到 OSS，将 file_url 传入 submit_task 后轮询 get_result"
        )
