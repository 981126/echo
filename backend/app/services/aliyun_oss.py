"""阿里云 OSS 临时文件中转（R-032）：转写前上传、生成签名 URL、完成后删除。

FileTrans 要求待识别文件是公网可访问的 URL（不支持本地文件），
因此本地视频先上传到 OSS，用预签名 URL 提交任务，识别完成后删除临时对象。
"""

from __future__ import annotations

import uuid
from pathlib import Path

import oss2

from ..config import get_settings
from .transcription import TranscriptionError

_CONTENT_TYPES = {
    ".mp4": "video/mp4",
    ".mov": "video/quicktime",
    ".m4a": "audio/mp4",
    ".mp3": "audio/mpeg",
    ".wav": "audio/wav",
    ".aac": "audio/aac",
    ".ogg": "audio/ogg",
    ".flac": "audio/flac",
    ".amr": "audio/amr",
}
MAX_FILE_BYTES = 2 * 1024**3  # FileTrans 视频文件上限 2GB
_DEFAULT_REGION = "oss-cn-shanghai"


class AliyunOss:
    """OSS 上传/签名/删除；AccessKey 与 FileTrans 共用 ECHO_ALIYUN_ASR_*。"""

    def __init__(self, settings=None):
        self.settings = settings or get_settings()
        ak = (self.settings.aliyun_asr_access_key_id or "").strip()
        sk = (self.settings.aliyun_asr_access_key_secret or "").strip()
        bucket = (self.settings.aliyun_oss_bucket or "").strip()
        if not (ak and sk and bucket):
            raise TranscriptionError(
                "未配置阿里云 OSS（需 ECHO_ALIYUN_ASR_ACCESS_KEY_ID/SECRET 与 ECHO_ALIYUN_OSS_BUCKET）"
            )
        region = (self.settings.aliyun_oss_region or _DEFAULT_REGION).strip().lstrip("https://")
        self.bucket_name = bucket
        self._bucket = oss2.Bucket(oss2.Auth(ak, sk), f"https://{region}.aliyuncs.com", bucket)

    def upload_file(self, local_path: Path | str) -> str:
        """上传本地文件，返回 OSS 对象 key（随机前缀，避免撞名）。"""
        path = Path(local_path)
        if not path.is_file():
            raise TranscriptionError(f"视频不存在: {path}")
        size = path.stat().st_size
        if size <= 0:
            raise TranscriptionError(f"视频为空文件: {path}")
        if size > MAX_FILE_BYTES:
            raise TranscriptionError("视频超过 2GB，超出录音文件识别上限")
        key = self._new_key(path)
        content_type = _CONTENT_TYPES.get(path.suffix.lower(), "application/octet-stream")
        self._bucket.put_object_from_file(
            key, str(path), headers={"Content-Type": content_type}
        )
        return key

    def sign_url(self, key: str, expires_in: int | None = None) -> str:
        """生成 GET 预签名 URL（供 FileTrans 拉取）。"""
        expires = int(expires_in or self.settings.aliyun_oss_url_expire or 7 * 24 * 3600)
        return self._bucket.sign_url("GET", key, expires)

    def delete_object(self, key: str) -> None:
        """删除临时对象（best-effort：清理失败不影响转写结果）。"""
        try:
            self._bucket.delete_object(key)
        except Exception:  # noqa: BLE001
            pass

    @staticmethod
    def _new_key(path: Path) -> str:
        safe_name = "".join(ch for ch in path.name if ch.isalnum() or ch in "._-")
        return f"asr/{uuid.uuid4().hex[:20]}_{safe_name[:80]}"
