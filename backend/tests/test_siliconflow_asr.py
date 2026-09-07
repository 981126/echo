"""硅基流动 ASR 真实接入（R-108）：直传转写编排纯逻辑测试（离线 mock，不访问网络）。"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import httpx
import pytest

from app.services import siliconflow_asr as sf_mod
from app.services.media_tools import needs_audio_extraction
from app.services.siliconflow_asr import SiliconFlowASR
from app.services.transcription import Transcriber, TranscriptionError


def _settings(**overrides: object) -> MagicMock:
    base: dict[str, object] = dict(
        asr_mode="siliconflow",
        siliconflow_api_key="sf-test-key",
        siliconflow_base_url="https://api.siliconflow.cn/v1",
        siliconflow_asr_model="FunAudioLLM/SenseVoiceSmall",
        asr_poll_timeout=30,
    )
    base.update(overrides)
    return MagicMock(**base)


class _FakeResp:
    def __init__(self, status_code: int = 200, payload: dict | None = None, text: str = ""):
        self.status_code = status_code
        self._payload = payload or {}
        self.text = text

    def json(self) -> dict:
        return self._payload


class _FakePost:
    """记录最近一次 httpx.post 调用的参数，返回可配置响应。"""

    def __init__(self, status_code: int = 200, payload: dict | None = None, text: str = ""):
        self.status_code = status_code
        self.payload = payload
        self.text = text
        self.last_kwargs: dict | None = None

    def __call__(self, url: str, **kwargs):
        self.last_kwargs = kwargs
        return _FakeResp(self.status_code, self.payload, self.text)


def _patch_probe(monkeypatch, seconds: float | None = 12.0):
    def _probe(_path):
        if seconds is None:
            raise TranscriptionError("无法读取媒体时长")
        return seconds

    monkeypatch.setattr(sf_mod, "probe_duration_seconds", _probe)


def test_missing_key_raises(tmp_path):
    path = tmp_path / "a.wav"
    path.write_bytes(b"RIFF-fake")
    client = SiliconFlowASR(settings=_settings(siliconflow_api_key=""))
    with pytest.raises(TranscriptionError, match="未配置硅基流动"):
        client._transcribe_upload(path)


def test_transcribe_audio_skips_extraction(tmp_path, monkeypatch):
    """纯音频（wav）直传原文件，不做 ffmpeg 抽离，也不删除原文件。"""
    _patch_probe(monkeypatch)
    post = _FakePost(payload={"text": "北京的天气。"})
    monkeypatch.setattr(sf_mod.httpx, "post", post)
    path = tmp_path / "demo.wav"
    path.write_bytes(b"RIFF-fake")

    text = SiliconFlowASR(settings=_settings()).transcribe_file(path)

    assert text == "北京的天气。"
    assert post.last_kwargs is not None
    files = post.last_kwargs["files"]
    assert files["file"][0] == "demo.wav"  # 传的是原文件
    assert post.last_kwargs["data"] == {"model": "FunAudioLLM/SenseVoiceSmall"}
    assert post.last_kwargs["headers"]["Authorization"] == "Bearer sf-test-key"
    assert path.exists()  # 原文件未被删除


def test_transcribe_video_extracts_then_cleanup(tmp_path, monkeypatch):
    """视频（mp4）先抽音轨：上传的是抽出的 wav，且临时 wav 用完即删。"""
    _patch_probe(monkeypatch)
    video = tmp_path / "demo.mp4"
    video.write_bytes(b"fake-video")
    extracted = tmp_path / "extracted.wav"
    extracted.write_bytes(b"RIFF-fake")
    monkeypatch.setattr(sf_mod, "extract_audio_to_wav", lambda p: extracted)
    post = _FakePost(payload={"text": "大家好。"})
    monkeypatch.setattr(sf_mod.httpx, "post", post)

    text = SiliconFlowASR(settings=_settings()).transcribe_file(video)

    assert text == "大家好。"
    files = post.last_kwargs["files"]
    assert files["file"][0] == "extracted.wav"  # 上传的是抽出的音频
    assert video.exists()  # 原视频不动
    assert not extracted.exists()  # 临时音频已清理


def test_needs_audio_extraction_rule():
    assert needs_audio_extraction(Path("a.mp4")) is True
    assert needs_audio_extraction(Path("a.mov")) is True
    assert needs_audio_extraction(Path("a.wav")) is False
    assert needs_audio_extraction(Path("a.mp3")) is False


def test_empty_text_raises(tmp_path, monkeypatch):
    """返回成功但 text 为空 → 视为失败（R-094 口径，消息含「识别结果为空」）。"""
    _patch_probe(monkeypatch)
    post = _FakePost(payload={"text": ""})
    monkeypatch.setattr(sf_mod.httpx, "post", post)
    path = tmp_path / "demo.wav"
    path.write_bytes(b"RIFF-fake")
    with pytest.raises(TranscriptionError, match="识别结果为空"):
        SiliconFlowASR(settings=_settings()).transcribe_file(path)


def test_http_error_raises(tmp_path, monkeypatch):
    _patch_probe(monkeypatch)
    post = _FakePost(status_code=422, text='{"error": "invalid model"}')
    monkeypatch.setattr(sf_mod.httpx, "post", post)
    path = tmp_path / "demo.wav"
    path.write_bytes(b"RIFF-fake")
    with pytest.raises(TranscriptionError, match="HTTP 422"):
        SiliconFlowASR(settings=_settings()).transcribe_file(path)


def test_network_error_raises(tmp_path, monkeypatch):
    _patch_probe(monkeypatch)
    def _boom(*_a, **_k):
        raise httpx.HTTPError("network down")

    monkeypatch.setattr(sf_mod.httpx, "post", _boom)
    path = tmp_path / "demo.wav"
    path.write_bytes(b"RIFF-fake")
    with pytest.raises(TranscriptionError, match="调用失败"):
        SiliconFlowASR(settings=_settings()).transcribe_file(path)


def test_oversize_raises_and_no_upload(tmp_path, monkeypatch):
    """超过 50MB：明确报错提示切阿里云，且不发请求（不自动切换）。"""
    monkeypatch.setattr(sf_mod, "MAX_FILE_MB", 0)  # 任何文件都视为超限
    post = _FakePost()
    monkeypatch.setattr(sf_mod.httpx, "post", post)
    path = tmp_path / "demo.wav"
    path.write_bytes(b"RIFF-fake")
    with pytest.raises(TranscriptionError, match="超过硅基流动单文件"):
        SiliconFlowASR(settings=_settings()).transcribe_file(path)
    assert post.last_kwargs is None  # 未发出请求


def test_duration_over_limit_raises(tmp_path, monkeypatch):
    _patch_probe(monkeypatch, seconds=7200)
    post = _FakePost()
    monkeypatch.setattr(sf_mod.httpx, "post", post)
    path = tmp_path / "demo.wav"
    path.write_bytes(b"RIFF-fake")
    with pytest.raises(TranscriptionError, match="1 小时限制"):
        SiliconFlowASR(settings=_settings()).transcribe_file(path)
    assert post.last_kwargs is None


def test_transcriber_routes_siliconflow(tmp_path, monkeypatch):
    """Transcriber 按 asr_mode=siliconflow 路由到硅基流动实现。"""
    class _FakeClient:
        def __init__(self, settings=None):
            self.settings = settings

        def transcribe_file(self, path):
            return "硅基流动转写结果"

    monkeypatch.setattr(sf_mod, "SiliconFlowASR", _FakeClient)
    path = tmp_path / "demo.wav"
    path.write_bytes(b"RIFF-fake")
    text = Transcriber(settings=_settings()).transcribe(path)
    assert text == "硅基流动转写结果"


def test_transcriber_unknown_mode_raises(tmp_path):
    path = tmp_path / "demo.wav"
    path.write_bytes(b"RIFF-fake")
    with pytest.raises(TranscriptionError, match="未知 asr_mode"):
        Transcriber(settings=_settings(asr_mode="nonsense")).transcribe(path)


def test_sensevoice_event_markup_cleaned(tmp_path, monkeypatch):
    """R-108 二次：免费模型 SenseVoiceSmall 输出的事件标记（🎼/<|...|>）入库前清理。"""
    from app.services.siliconflow_asr import _clean_sensevoice_text

    assert _clean_sensevoice_text("🎼我找工作，线上面试成功率更高。") == "我找工作，线上面试成功率更高。"
    assert _clean_sensevoice_text("<|zh|>大家好<|NEUTRAL|>") == "大家好"
