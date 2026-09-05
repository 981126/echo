"""阿里云录音文件识别（FileTrans）RPC POP 客户端（R-032 真实接入）。

采用官方推荐方式：aliyun-python-sdk-core 的 CommonRequest 泛化调用
（SubmitTask / GetTaskResult，见阿里云《Python Demo》帮助文档）。
待识别文件要求公网 URL：视频先上传 OSS（services/aliyun_oss.py）拿到
预签名 URL 再提交，识别完成后删除 OSS 临时对象。
"""

from __future__ import annotations

import json
import time
from pathlib import Path

from aliyunsdkcore.client import AcsClient
from aliyunsdkcore.request import CommonRequest

from ..config import get_settings
from .aliyun_oss import AliyunOss
from .transcription import TranscriptionError

PRODUCT = "nls-filetrans"
API_VERSION = "2018-08-17"
DEFAULT_REGION = "cn-shanghai"
_RUNNING = {"RUNNING", "QUEUEING"}
_DONE_OK = {"SUCCESS"}
_DONE_EMPTY = {"SUCCESS_WITH_NO_VALID_FRAGMENT"}
POLL_MIN_INTERVAL = 5  # 服务端建议查询间隔适当延长，勿过短


class AliyunFileTrans:
    def __init__(self, settings=None):
        self.settings = settings or get_settings()

    def _call(
        self,
        action: str,
        method: str,
        body_params: dict | None = None,
        query_params: dict | None = None,
    ) -> dict:
        """单次 RPC 调用（RPC 风格 POP，SDK 自动签名）。"""
        settings = self.settings
        ak = (settings.aliyun_asr_access_key_id or "").strip()
        sk = (settings.aliyun_asr_access_key_secret or "").strip()
        app_key = (settings.aliyun_asr_app_key or "").strip()
        if not (ak and sk and app_key):
            raise TranscriptionError(
                "未配置阿里云 ASR（需 ECHO_ALIYUN_ASR_ACCESS_KEY_ID/SECRET/APP_KEY）"
            )
        region = (settings.aliyun_asr_region or DEFAULT_REGION).strip()
        client = AcsClient(ak, sk, region)
        request = CommonRequest()
        request.set_domain(f"filetrans.{region}.aliyuncs.com")
        request.set_version(API_VERSION)
        request.set_product(PRODUCT)
        request.set_action_name(action)
        request.set_method(method)
        for key, value in (body_params or {}).items():
            request.add_body_params(key, value)
        for key, value in (query_params or {}).items():
            request.add_query_param(key, value)
        try:
            raw = client.do_action_with_exception(request)
        except Exception as exc:  # ClientException / ServerException / 网络错误
            raise TranscriptionError(f"阿里云 FileTrans 调用失败: {exc}") from exc
        try:
            data = json.loads(raw)
        except (TypeError, ValueError):
            raise TranscriptionError(f"阿里云 FileTrans 返回无法解析: {raw!r}") from None
        status = str(data.get("StatusText") or "")
        if status and status not in (_RUNNING | _DONE_OK | _DONE_EMPTY):
            raise TranscriptionError(f"阿里云 FileTrans 任务异常: {status}（{data}）")
        return data

    def submit_task(self, file_url: str) -> str:
        body = json.dumps(
            {
                "appkey": (self.settings.aliyun_asr_app_key or "").strip(),
                "file_link": file_url,
                "version": "4.0",
                "enable_words": False,
                "enable_sample_rate_adaptive": True,  # 高采样率自动降采样到 16k
            },
            ensure_ascii=False,
        )
        data = self._call("SubmitTask", "POST", body_params={"Task": body})
        task_id = data.get("TaskId") or data.get("task_id")
        if not task_id:
            raise TranscriptionError(f"提交转写任务失败: {data}")
        return task_id

    def get_result(self, task_id: str) -> dict:
        return self._call("GetTaskResult", "GET", query_params={"TaskId": task_id})

    def transcribe_file(self, video_path: Path | str) -> str:
        """上传 OSS → 提交任务 → 轮询结果 → 返回文本（临时对象最终删除）。"""
        path = Path(video_path)
        if not path.is_file():
            raise TranscriptionError(f"视频不存在: {path}")
        oss = AliyunOss(settings=self.settings)
        key = oss.upload_file(path)
        try:
            file_url = oss.sign_url(key)
            task_id = self.submit_task(file_url)
            return self._poll(task_id)
        finally:
            oss.delete_object(key)

    def _poll(self, task_id: str) -> str:
        settings = self.settings
        interval = max(POLL_MIN_INTERVAL, int(getattr(settings, "asr_poll_interval", 0) or POLL_MIN_INTERVAL))
        timeout = max(60, int(getattr(settings, "asr_poll_timeout", 0) or 3600))
        deadline = time.time() + timeout
        while True:
            data = self.get_result(task_id)
            status = str(data.get("StatusText") or "")
            if status in _DONE_OK:
                text = self._extract_text(data)
                if not text:
                    raise TranscriptionError("识别成功但结果为空")
                return text
            if status in _DONE_EMPTY:
                raise TranscriptionError("识别结果为空（SUCCESS_WITH_NO_VALID_FRAGMENT）")
            if status not in _RUNNING:
                raise TranscriptionError(f"转写任务异常: {status}（{data}）")
            if time.time() >= deadline:
                raise TranscriptionError(
                    "阿里云转写等待超时，可在素材详情稍后重试（任务可能仍在服务端处理）"
                )
            time.sleep(interval)

    @staticmethod
    def _extract_text(result: dict) -> str:
        sentences = ((result.get("Result") or {}).get("Sentences")) or []
        return "\n".join(s.get("Text", "") for s in sentences if s.get("Text")).strip()
