"""阿里云 ASR 真实接入（R-032）：转写编排纯逻辑测试（离线 mock，不访问网络）。"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

from app.services import aliyun_filetrans as ft_mod
from app.services.aliyun_filetrans import AliyunFileTrans
from app.services.aliyun_oss import AliyunOss
from app.services.transcription import TranscriptionError


def _settings(**overrides: object) -> MagicMock:
    base: dict[str, object] = dict(
        asr_mode="aliyun",
        aliyun_asr_access_key_id="ak-test",
        aliyun_asr_access_key_secret="sk-test",
        aliyun_asr_app_key="appkey-test",
        aliyun_oss_bucket="bucket-test",
        aliyun_oss_region="oss-cn-shanghai",
        aliyun_oss_url_expire=3600,
        aliyun_asr_region="cn-shanghai",
        asr_poll_interval=0,
        asr_poll_timeout=30,
    )
    base.update(overrides)
    return MagicMock(**base)


class _FakeOss:
    def __init__(self, settings=None):
        self.settings = settings

    def upload_file(self, path: Path | str) -> str:
        return "asr/fake.mp4"

    def sign_url(self, key: str, expires_in: int | None = None) -> str:
        return f"https://signed/{key}"

    def delete_object(self, key: str) -> None:
        self.deleted = key


def test_aliyun_oss_requires_config():
    with pytest.raises(TranscriptionError):
        AliyunOss(settings=_settings(aliyun_oss_bucket="", aliyun_asr_access_key_id=""))


def test_transcribe_file_upload_submit_poll_cleanup(tmp_path, monkeypatch):
    monkeypatch.setattr(ft_mod, "AliyunOss", _FakeOss)
    monkeypatch.setattr(ft_mod.time, "sleep", lambda _seconds: None)
    path = tmp_path / "demo.mp4"
    path.write_bytes(b"fake")
    client = AliyunFileTrans(settings=_settings())
    fake_oss = _FakeOss()
    monkeypatch.setattr(ft_mod, "AliyunOss", lambda settings=None: fake_oss)
    client.submit_task = MagicMock(return_value="task-1")
    client.get_result = MagicMock(
        side_effect=[
            {"StatusText": "RUNNING", "TaskId": "task-1"},
            {
                "StatusText": "SUCCESS",
                "TaskId": "task-1",
                "Result": {"Sentences": [{"Text": "大家好。"}, {"Text": "今天聊聊求职。"}]},
            },
        ]
    )
    text = client.transcribe_file(path)
    assert text == "大家好。\n今天聊聊求职。"
    assert client.submit_task.call_args[0][0].startswith("https://signed/")
    assert client.get_result.call_count == 2
    assert fake_oss.deleted == "asr/fake.mp4"


def test_poll_timeout(monkeypatch):
    class FakeTime:
        def __init__(self) -> None:
            self.now = 0.0

        def time(self) -> float:
            return self.now

        def sleep(self, seconds: float) -> None:
            self.now += seconds

    monkeypatch.setattr(ft_mod, "time", FakeTime())
    client = AliyunFileTrans(settings=_settings(asr_poll_timeout=20))
    client.get_result = MagicMock(return_value={"StatusText": "RUNNING", "TaskId": "task-1"})
    with pytest.raises(TranscriptionError, match="超时"):
        client._poll("task-1")


def test_poll_raises_on_error_status():
    client = AliyunFileTrans(settings=_settings())
    client.get_result = MagicMock(
        return_value={"StatusText": "FILE_DOWNLOAD_FAILED", "TaskId": "task-1"}
    )
    with pytest.raises(TranscriptionError, match="FILE_DOWNLOAD_FAILED"):
        client._poll("task-1")


def test_extract_text_joins_sentences():
    result = {
        "Result": {"Sentences": [{"Text": "A。"}, {"Text": ""}, {"Text": "B。"}]}
    }
    assert AliyunFileTrans._extract_text(result) == "A。\nB。"
