"""腾讯云 ASR 真实接入（R-200）：转写编排纯逻辑测试（离线 mock，不访问网络）。"""

from __future__ import annotations

import base64
import json
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import Base
from app.models.kv import Kv
from app.services import media_tools as mt_mod
from app.services import model_settings as ms
from app.services import tencent_asr as asr_mod
from app.services.tencent_asr import TencentAsr
from app.services.transcription import Transcriber, TranscriptionError

# ---------- 通用桩 ----------


def _settings(**overrides: object) -> MagicMock:
    base: dict[str, object] = dict(
        asr_mode="tencent",
        tencent_asr_secret_id="sid-test",
        tencent_asr_secret_key="skey-test",
        tencent_asr_region="ap-guangzhou",
        tencent_asr_endpoint="asr.tencentcloudapi.com",
        tencent_asr_engine_model="16k_zh_en_2.0",
        tencent_asr_max_audio_mb=5,
        asr_poll_interval=0,
        asr_poll_timeout=30,
    )
    base.update(overrides)
    return MagicMock(**base)


class _FakeResp:
    def __init__(self, payload: dict):
        self._payload = payload

    def to_json_string(self) -> str:
        return json.dumps(self._payload)


class _FakeClient:
    """记录 CreateRecTask 参数；按顺序吐出 DescribeTaskStatus 结果。"""

    def __init__(self, created: dict | None = None, statuses: list[dict] | None = None):
        self.created: dict | None = None
        self._created = created if created is not None else {"Data": {"TaskId": 1000000286}}
        self._statuses = list(statuses or [])

    def CreateRecTask(self, request):
        self.created = json.loads(request.to_json_string())
        return _FakeResp(self._created)

    def DescribeTaskStatus(self, request):
        if not self._statuses:
            raise AssertionError("DescribeTaskStatus 调用次数超出预期")
        return _FakeResp(self._statuses.pop(0))


def _success(text: str = "北京的天气。") -> dict:
    return {
        "Data": {
            "TaskId": 1000000286,
            "Status": 2,
            "StatusStr": "success",
            "Result": f"[0:0.020,0:2.380]  {text}\n",
            "ResultDetail": [{"FinalSentence": text}],
            "ErrorMsg": "",
        }
    }


# ---------- 基础校验 ----------


def test_missing_secret_raises(tmp_path, monkeypatch):
    path = tmp_path / "a.wav"
    path.write_bytes(b"RIFF-fake")
    monkeypatch.setattr(asr_mod, "extract_audio_compact", lambda p, **k: (path, False))
    client = TencentAsr(settings=_settings(tencent_asr_secret_id="", tencent_asr_secret_key=""))
    with pytest.raises(TranscriptionError, match="未配置腾讯云"):
        client.transcribe_file(path)


def test_submit_params_and_base64(tmp_path, monkeypatch):
    """本地音频直传：SourceType=1 / ChannelNum=1 / 引擎指定 / Data+DataLen 正确。"""
    audio = tmp_path / "demo.wav"
    raw = b"RIFF-fake-audio"
    audio.write_bytes(raw)
    monkeypatch.setattr(asr_mod, "extract_audio_compact", lambda p, **k: (audio, False))

    fake = _FakeClient(statuses=[_success("大家好。")])
    client = TencentAsr(settings=_settings())
    client._client = lambda: fake  # type: ignore[method-assign]

    text = client.transcribe_file(audio)

    assert text == "大家好。"
    assert fake.created is not None
    assert fake.created["SourceType"] == 1
    assert fake.created["ChannelNum"] == 1
    assert fake.created["EngineModelType"] == "16k_zh_en_2.0"
    assert fake.created["DataLen"] == len(raw)
    assert base64.b64decode(fake.created["Data"]) == raw


def test_model_override_used(tmp_path, monkeypatch):
    audio = tmp_path / "demo.wav"
    audio.write_bytes(b"x")
    monkeypatch.setattr(asr_mod, "extract_audio_compact", lambda p, **k: (audio, False))
    fake = _FakeClient(statuses=[_success()])
    client = TencentAsr(settings=_settings(), model="16k_zh")
    client._client = lambda: fake  # type: ignore[method-assign]
    client.transcribe_file(audio)
    assert fake.created["EngineModelType"] == "16k_zh"


def test_video_compacts_then_cleanup(tmp_path, monkeypatch):
    """视频：由 extract_audio_compact 产出临时 mp3，转写完删除。"""
    video = tmp_path / "demo.mp4"
    video.write_bytes(b"fake-video")
    tmp_audio = tmp_path / "echo_asr_tmp.mp3"
    tmp_audio.write_bytes(b"mp3-data")
    called: dict = {}

    def _compact(p, **kwargs):
        called["path"] = p
        called["kwargs"] = kwargs
        return tmp_audio, True

    monkeypatch.setattr(asr_mod, "extract_audio_compact", _compact)
    fake = _FakeClient(statuses=[_success()])
    client = TencentAsr(settings=_settings())
    client._client = lambda: fake  # type: ignore[method-assign]

    text = client.transcribe_file(video)

    assert text == "北京的天气。"
    assert called["path"] == video
    assert called["kwargs"]["max_bytes"] == 5 * 1024 * 1024
    assert video.exists()  # 原视频不动
    assert not tmp_audio.exists()  # 临时音频已清理


# ---------- 轮询与解析 ----------


def test_poll_waiting_doing_success_strips_timestamp(tmp_path, monkeypatch):
    audio = tmp_path / "a.wav"
    audio.write_bytes(b"x")
    monkeypatch.setattr(asr_mod, "extract_audio_compact", lambda p, **k: (audio, False))
    monkeypatch.setattr(asr_mod.time, "sleep", lambda _s: None)
    statuses = [
        {"Data": {"TaskId": 1, "Status": 0, "StatusStr": "waiting"}},
        {"Data": {"TaskId": 1, "Status": 1, "StatusStr": "doing"}},
        {"Data": {"TaskId": 1, "Status": 2, "StatusStr": "success", "Result": "[0:0,1:2]  你好\n[1:2,2:0]  世界。\n", "ResultDetail": []}},
    ]
    fake = _FakeClient(statuses=statuses)
    client = TencentAsr(settings=_settings())
    client._client = lambda: fake  # type: ignore[method-assign]

    assert client.transcribe_file(audio) == "你好\n世界。"


def test_poll_failed_status_raises_with_error(tmp_path, monkeypatch):
    audio = tmp_path / "a.wav"
    audio.write_bytes(b"x")
    monkeypatch.setattr(asr_mod, "extract_audio_compact", lambda p, **k: (audio, False))
    statuses = [{"Data": {"TaskId": 1, "Status": 3, "StatusStr": "failed", "ErrorMsg": "Failed to download audio file!"}}]
    client = TencentAsr(settings=_settings())
    client._client = lambda: _FakeClient(statuses=statuses)  # type: ignore[method-assign]

    with pytest.raises(TranscriptionError, match="Failed to download audio file!"):
        client.transcribe_file(audio)


def test_poll_timeout(tmp_path, monkeypatch):
    audio = tmp_path / "a.wav"
    audio.write_bytes(b"x")
    monkeypatch.setattr(asr_mod, "extract_audio_compact", lambda p, **k: (audio, False))

    class FakeTime:
        def __init__(self) -> None:
            self.now = 0.0

        def time(self) -> float:
            return self.now

        def sleep(self, seconds: float) -> None:
            self.now += seconds

    monkeypatch.setattr(asr_mod, "time", FakeTime())
    client = TencentAsr(settings=_settings(asr_poll_timeout=10, asr_poll_interval=5))
    always_waiting = {"Data": {"TaskId": 1, "Status": 0, "StatusStr": "waiting"}}
    client._client = lambda: _FakeClient(statuses=[always_waiting] * 100)  # type: ignore[method-assign]

    with pytest.raises(TranscriptionError, match="超时"):
        client.transcribe_file(audio)


def test_extract_text_falls_back_when_no_detail():
    data = {"Result": "[0:0.0,0:1.0]  第一句。\n[0:1.0,0:2.0]  第二句。\n", "ResultDetail": []}
    assert TencentAsr._extract_text(data) == "第一句。\n第二句。"


# ---------- 媒体压缩（media_tools） ----------


def test_extract_audio_compact_direct_small_audio(tmp_path):
    path = tmp_path / "a.mp3"
    path.write_bytes(b"x" * 10)
    out, is_temp = mt_mod.extract_audio_compact(path, max_bytes=1000)
    assert out == path and is_temp is False


def test_extract_audio_compact_rejects_oversize(tmp_path, monkeypatch):
    src = tmp_path / "a.wav"
    src.write_bytes(b"x" * 500)  # 超过 max_bytes → 走压缩

    def _fake_run(cmd, capture_output=True, timeout=0):
        Path(cmd[-1]).write_bytes(b"y" * 5000)
        return types.SimpleNamespace(returncode=0, stderr=b"")

    monkeypatch.setattr(mt_mod.subprocess, "run", _fake_run)
    monkeypatch.setattr(mt_mod, "probe_duration_seconds", lambda _p: 1.0)
    with pytest.raises(TranscriptionError, match="仍超过腾讯云"):
        mt_mod.extract_audio_compact(src, max_bytes=100)


# ---------- 路由 ----------


def test_transcriber_routes_tencent(tmp_path, monkeypatch):
    class _Fake:
        def __init__(self, settings=None, model=None):
            self.settings = settings
            self.model = model

        def transcribe_file(self, path):
            return "腾讯云转写结果"

    monkeypatch.setattr(asr_mod, "TencentAsr", _Fake)
    path = tmp_path / "demo.wav"
    path.write_bytes(b"RIFF-fake")
    assert Transcriber(settings=_settings()).transcribe(path) == "腾讯云转写结果"


# ---------- 模型设置校验 ----------


@pytest.fixture()
def db(tmp_path):
    eng = create_engine(f"sqlite:///{tmp_path}/t.db", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=eng)
    session = sessionmaker(bind=eng, autoflush=False, autocommit=False)()
    yield session
    session.close()
    eng.dispose()


def _valid_payload(**over):
    payload = {
        "model1": {"vendor": "deepseek", "model": "deepseek-flash", "key": "sk-test-1"},
        "model2": {"vendor": "kimi", "model": "kimi-k2.6", "key": "sk-test-2"},
        "gen_role": "model1",
        "referee_role": "model2",
        "asr_mode": "tencent",
        "asr_model": "16k_zh_en_2.0",
    }
    payload.update(over)
    return payload


def _patch_settings(monkeypatch, **over):
    base = dict(
        tencent_asr_secret_id="sid",
        tencent_asr_secret_key="skey",
        tencent_asr_engine_model="16k_zh_en_2.0",
        siliconflow_api_key="sf",
        asr_mode="mock",
        deepseek_api_key="",
        kimi_api_key="",
    )
    base.update(over)
    monkeypatch.setattr(ms, "get_settings", lambda: MagicMock(**base))


def test_save_tencent_requires_secret(db, monkeypatch):
    _patch_settings(monkeypatch, tencent_asr_secret_id="", tencent_asr_secret_key="")
    with pytest.raises(ms.ModelConfigError, match="腾讯云 ASR"):
        ms.save_model_config(db, _valid_payload())


def test_save_tencent_rejects_unknown_engine(db, monkeypatch):
    _patch_settings(monkeypatch)
    with pytest.raises(ms.ModelConfigError, match="引擎不受支持"):
        ms.save_model_config(db, _valid_payload(asr_model="16k_xx"))


def test_save_tencent_and_runtime_config(db, monkeypatch):
    _patch_settings(monkeypatch)
    saved = ms.save_model_config(db, _valid_payload(asr_model="16k_zh"))
    assert saved["asr_mode"] == "tencent" and saved["asr_model"] == "16k_zh"
    assert ms.asr_config(db) == {"mode": "tencent", "model": "16k_zh"}


def test_coerce_asr_model_mode_aware(db, monkeypatch):
    _patch_settings(monkeypatch)
    # 切到腾讯但沿用上一家模型名 → 回退腾讯默认
    ms.save_model_config(db, _valid_payload(asr_mode="tencent", asr_model="16k_zh_en_2.0"))
    row = db.get(Kv, "asr_model")
    row.value = "Qwen/Qwen3-ASR-1.7B"
    db.commit()
    assert ms.asr_config(db)["model"] == ms.ASR_TENCENT_DEFAULT
