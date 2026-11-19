"""DeepSeek ASR 接入（R-264）：切点规划 / 分片转写编排 / 设置校验（离线 mock，不访问网络）。"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest
from conftest import ensure_schema, fresh_engine
from sqlalchemy.orm import sessionmaker

from app.api import settings as api_settings
from app.config import _MODE_CHOICES, normalize_mode
from app.models.kv import Kv
from app.services import deepseek_asr as ds_mod
from app.services import model_settings as ms
from app.services.deepseek_asr import DeepSeekAsr, _join_texts, _plan_cuts
from app.services.transcription import Transcriber, TranscriptionError


def _settings(**overrides: object) -> MagicMock:
    base: dict[str, object] = dict(
        asr_mode="deepseek",
        deepseek_api_key="ds-test-key",
        deepseek_asr_url="https://api.deepseek.com/v1/tools/asr",
        deepseek_asr_chunk_seconds=110,
        deepseek_asr_chunk_max_seconds=118,
        deepseek_asr_max_request_mb=8,
        deepseek_asr_max_total_seconds=7200,
        deepseek_asr_retries=1,
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
    """按顺序返回响应，并记录每次调用的参数（url/headers/files/timeout）。"""

    def __init__(self, responses: list[_FakeResp]):
        self.responses = list(responses)
        self.calls: list[dict] = []

    def __call__(self, url: str, **kwargs: object) -> _FakeResp:
        self.calls.append({"url": url, **kwargs})
        return self.responses[min(len(self.calls) - 1, len(self.responses) - 1)]


def _patch_audio(
    monkeypatch, tmp_path: Path, *, duration: float, frames: list[tuple[float, float]] | None = None
) -> tuple[Path, dict]:
    """桩掉 ffmpeg：抽出 wav、探测时长、音量帧、切片（切片生成真实小文件供上传）。"""
    wav = tmp_path / "audio.wav"
    wav.write_bytes(b"RIFF-fake")
    monkeypatch.setattr(ds_mod, "extract_audio_to_wav", lambda _p: wav)
    monkeypatch.setattr(ds_mod, "probe_duration_seconds", lambda _p: duration)
    monkeypatch.setattr(ds_mod, "audio_rms_frames", lambda _p, *a, **k: list(frames or []))
    recorded: dict = {}

    def _cut(_src, cuts):
        recorded["cuts"] = list(cuts)
        outputs = []
        for index, _cut_item in enumerate(cuts, start=1):
            path = tmp_path / f"seg{index}.wav"
            path.write_bytes(f"segment-{index}".encode())
            outputs.append(path)
        return outputs

    monkeypatch.setattr(ds_mod, "cut_wav_segments", _cut)
    recorded["wav"] = wav
    return wav, recorded


def _patch_sleep(monkeypatch) -> list[float]:
    slept: list[float] = []
    monkeypatch.setattr(ds_mod.time, "sleep", lambda seconds: slept.append(seconds))
    return slept


# ---------- 切点规划 ----------


def _frames(duration: float, *, quiet: list[tuple[float, float]]) -> list[tuple[float, float]]:
    """构造 -20dB 连续语音帧，并在指定区间覆盖为 -45dB 静音帧。"""
    frames: list[tuple[float, float]] = []
    t = 0.0
    while t < duration:
        level = -20.0
        for start, end in quiet:
            if start <= t < end:
                level = -45.0
        frames.append((t, level))
        t += 0.05
    return frames


def test_plan_cuts_short_audio_single_request():
    assert _plan_cuts(60.0, [], target_seconds=110, max_seconds=118) == [(0.0, 60.0, "single")]
    assert _plan_cuts(118.0, [], target_seconds=110, max_seconds=118) == [(0.0, 118.0, "single")]


def test_plan_cuts_prefers_silence_midpoint_near_target():
    frames = _frames(300.0, quiet=[(108.0, 112.0), (218.0, 222.0)])
    cuts = _plan_cuts(300.0, frames, target_seconds=110, max_seconds=118)
    assert len(cuts) == 3
    first, second, third = cuts
    assert first[2] == "silence" and abs(first[1] - 110.0) <= 1.0
    assert second[2] == "silence" and abs(second[1] - 220.0) <= 2.0
    assert third[2] == "tail" and third[1] == pytest.approx(300.0)
    for start, end, _source in cuts:
        assert 0 < end - start <= 118.0
    assert cuts[1][0] == pytest.approx(cuts[0][1])  # 首尾相接不重叠


def test_plan_cuts_falls_back_to_quietest_frame():
    frames = _frames(300.0, quiet=[])
    frames[2300] = (115.0, -60.0)  # 窗口 90~118s 内唯一低能量帧
    cuts = _plan_cuts(300.0, frames, target_seconds=110, max_seconds=118)
    assert cuts[0][2] == "quietest"
    assert cuts[0][1] == pytest.approx(115.025)


def test_plan_cuts_hard_cut_when_analysis_failed():
    cuts = _plan_cuts(300.0, [], target_seconds=110, max_seconds=118)
    assert [cut[2] for cut in cuts] == ["hard", "hard", "tail"]
    assert cuts[0][1] == pytest.approx(110.0)
    assert cuts[1][1] == pytest.approx(220.0)


def test_plan_cuts_never_exceeds_max_segment():
    cuts = _plan_cuts(600.0, [], target_seconds=110, max_seconds=118)
    assert all(0 < end - start <= 118.0 for start, end, _ in cuts)
    assert cuts[-1][1] == pytest.approx(600.0)


# ---------- 文本拼接 ----------


def test_join_texts_keeps_chinese_joined_and_spaces_english():
    assert _join_texts(["第一段。", "第二段。"]) == "第一段。第二段。"
    assert _join_texts(["Hello", "World 你好", "世界"]) == "Hello World 你好世界"
    assert _join_texts(["  ", ""]) == ""


# ---------- 转写编排 ----------


def test_missing_key_raises(tmp_path, monkeypatch):
    path = tmp_path / "demo.mp4"
    path.write_bytes(b"fake")
    post = _FakePost([_FakeResp(200, {"text": "x"})])
    monkeypatch.setattr(ds_mod.httpx, "post", post)
    with pytest.raises(TranscriptionError, match="ECHO_DEEPSEEK_API_KEY"):
        DeepSeekAsr(settings=_settings(deepseek_api_key="")).transcribe_file(path)
    assert post.calls == []


def test_short_audio_single_request(tmp_path, monkeypatch):
    path = tmp_path / "demo.mp4"
    path.write_bytes(b"fake")
    _patch_audio(monkeypatch, tmp_path, duration=30.0)
    post = _FakePost([_FakeResp(200, {"text": "只有一个小时。"})])
    monkeypatch.setattr(ds_mod.httpx, "post", post)

    text = DeepSeekAsr(settings=_settings()).transcribe_file(path)

    assert text == "只有一个小时。"
    assert len(post.calls) == 1
    call = post.calls[0]
    assert call["url"] == "https://api.deepseek.com/v1/tools/asr"
    assert call["headers"]["Authorization"] == "Bearer ds-test-key"
    assert call["files"]["file"][0].endswith(".wav")
    assert "data" not in call  # DeepSeek 无 model 参数


def test_long_audio_splits_in_order_and_joins(tmp_path, monkeypatch):
    path = tmp_path / "demo.mp4"
    path.write_bytes(b"fake")
    frames = _frames(300.0, quiet=[(108.0, 112.0), (218.0, 222.0)])
    _wav, recorded = _patch_audio(monkeypatch, tmp_path, duration=300.0, frames=frames)
    post = _FakePost(
        [
            _FakeResp(200, {"text": "第一段。"}),
            _FakeResp(200, {"text": "第二段。"}),
            _FakeResp(200, {"text": "第三段。"}),
        ]
    )
    monkeypatch.setattr(ds_mod.httpx, "post", post)

    text = DeepSeekAsr(settings=_settings()).transcribe_file(path)

    assert text == "第一段。第二段。第三段。"
    assert len(post.calls) == 3
    assert len(recorded["cuts"]) == 3
    assert recorded["cuts"][0][0] == 0.0  # 第一片从 0 开始


def test_429_retries_then_succeeds(tmp_path, monkeypatch):
    path = tmp_path / "demo.mp4"
    path.write_bytes(b"fake")
    _patch_audio(monkeypatch, tmp_path, duration=30.0)
    slept = _patch_sleep(monkeypatch)
    post = _FakePost([_FakeResp(429, text="rate"), _FakeResp(200, {"text": "重试成功。"})])
    monkeypatch.setattr(ds_mod.httpx, "post", post)

    text = DeepSeekAsr(settings=_settings(deepseek_asr_retries=2)).transcribe_file(path)

    assert text == "重试成功。"
    assert len(post.calls) == 2
    assert slept  # 真的退避了


def test_429_retry_exhausted_message(tmp_path, monkeypatch):
    path = tmp_path / "demo.mp4"
    path.write_bytes(b"fake")
    _patch_audio(monkeypatch, tmp_path, duration=30.0)
    _patch_sleep(monkeypatch)
    post = _FakePost([_FakeResp(429, text="rate")])
    monkeypatch.setattr(ds_mod.httpx, "post", post)

    with pytest.raises(TranscriptionError, match="限流（第 1/1 片），已重试 2 次"):
        DeepSeekAsr(settings=_settings(deepseek_asr_retries=2)).transcribe_file(path)
    assert len(post.calls) == 3


def test_401_reports_auth_failure(tmp_path, monkeypatch):
    path = tmp_path / "demo.mp4"
    path.write_bytes(b"fake")
    _patch_audio(monkeypatch, tmp_path, duration=30.0)
    post = _FakePost([_FakeResp(401, text="unauthorized")])
    monkeypatch.setattr(ds_mod.httpx, "post", post)

    with pytest.raises(TranscriptionError, match="鉴权失败"):
        DeepSeekAsr(settings=_settings()).transcribe_file(path)


def test_400_includes_segment_index(tmp_path, monkeypatch):
    path = tmp_path / "demo.mp4"
    path.write_bytes(b"fake")
    _patch_audio(monkeypatch, tmp_path, duration=300.0)
    post = _FakePost([_FakeResp(400, text="bad audio")])
    monkeypatch.setattr(ds_mod.httpx, "post", post)

    with pytest.raises(TranscriptionError, match="第 1/3 片"):
        DeepSeekAsr(settings=_settings()).transcribe_file(path)


def test_all_segments_empty_raises(tmp_path, monkeypatch):
    path = tmp_path / "demo.mp4"
    path.write_bytes(b"fake")
    _patch_audio(monkeypatch, tmp_path, duration=30.0)
    post = _FakePost([_FakeResp(200, {"text": "  "})])
    monkeypatch.setattr(ds_mod.httpx, "post", post)

    with pytest.raises(TranscriptionError, match="识别结果为空（DeepSeek"):
        DeepSeekAsr(settings=_settings()).transcribe_file(path)


def test_oversize_segment_rejected_before_upload(tmp_path, monkeypatch):
    path = tmp_path / "demo.mp4"
    path.write_bytes(b"fake")
    _patch_audio(monkeypatch, tmp_path, duration=30.0)
    monkeypatch.setattr(
        ds_mod,
        "cut_wav_segments",
        lambda _src, cuts: [_write_big(tmp_path / "big.wav")],
    )
    post = _FakePost([_FakeResp(200, {"text": "x"})])
    monkeypatch.setattr(ds_mod.httpx, "post", post)

    with pytest.raises(TranscriptionError, match="超过 DeepSeek 1MiB 限制"):
        DeepSeekAsr(settings=_settings(deepseek_asr_max_request_mb=1)).transcribe_file(path)
    assert post.calls == []


def _write_big(path: Path) -> Path:
    path.write_bytes(b"x" * (1024 * 1024 + 128))
    return path


def test_total_duration_limit(tmp_path, monkeypatch):
    path = tmp_path / "demo.mp4"
    path.write_bytes(b"fake")
    _patch_audio(monkeypatch, tmp_path, duration=7201.0)
    post = _FakePost([_FakeResp(200, {"text": "x"})])
    monkeypatch.setattr(ds_mod.httpx, "post", post)

    with pytest.raises(TranscriptionError, match="超过 DeepSeek 转写上限"):
        DeepSeekAsr(settings=_settings()).transcribe_file(path)
    assert post.calls == []


def test_temp_files_cleaned_after_success_and_failure(tmp_path, monkeypatch):
    path = tmp_path / "demo.mp4"
    path.write_bytes(b"fake")
    _patch_audio(monkeypatch, tmp_path, duration=30.0)
    monkeypatch.setattr(
        ds_mod.httpx, "post", _FakePost([_FakeResp(200, {"text": "成功。"})])
    )
    DeepSeekAsr(settings=_settings()).transcribe_file(path)
    assert not (tmp_path / "audio.wav").exists()

    _patch_audio(monkeypatch, tmp_path, duration=30.0)
    monkeypatch.setattr(ds_mod.httpx, "post", _FakePost([_FakeResp(401, text="no")]))
    with pytest.raises(TranscriptionError):
        DeepSeekAsr(settings=_settings()).transcribe_file(path)
    assert not (tmp_path / "audio.wav").exists()
    assert not (tmp_path / "seg1.wav").exists()


def test_transcriber_routes_deepseek(tmp_path, monkeypatch):
    class _Fake:
        def __init__(self, settings=None):
            self.settings = settings

        def transcribe_file(self, _path):
            return "DeepSeek 转写结果"

    monkeypatch.setattr(ds_mod, "DeepSeekAsr", _Fake)
    path = tmp_path / "demo.wav"
    path.write_bytes(b"RIFF-fake")
    assert Transcriber(settings=_settings()).transcribe(path) == "DeepSeek 转写结果"


def test_config_mode_whitelist_accepts_deepseek():
    assert "deepseek" in _MODE_CHOICES["asr_mode"]
    assert normalize_mode("deepseek", _MODE_CHOICES["asr_mode"], "mock") == "deepseek"


# ---------- 模型设置校验 ----------


@pytest.fixture()
def db(tmp_path):
    eng = fresh_engine()
    ensure_schema(eng)
    session = sessionmaker(bind=eng, autoflush=False, autocommit=False)()
    yield session
    session.close()


def _valid_payload(**over):
    payload = {
        "model1": {"vendor": "deepseek", "model": "deepseek-flash", "key": "sk-test-1"},
        "model2": {"vendor": "kimi", "model": "kimi-k2.6", "key": "sk-test-2"},
        "gen_role": "model1",
        "referee_role": "model2",
        "asr_mode": "deepseek",
        "asr_model": "",
    }
    payload.update(over)
    return payload


def _patch_settings(monkeypatch, **over):
    base = dict(
        deepseek_api_key="ds-key",
        siliconflow_api_key="sf",
        tencent_asr_secret_id="",
        tencent_asr_secret_key="",
        asr_mode="mock",
        kimi_api_key="",
    )
    base.update(over)
    monkeypatch.setattr(ms, "get_settings", lambda: MagicMock(**base))


def test_save_deepseek_requires_env_key(db, monkeypatch):
    _patch_settings(monkeypatch, deepseek_api_key="")
    with pytest.raises(ms.ModelConfigError, match="ECHO_DEEPSEEK_API_KEY"):
        ms.save_model_config(db, _valid_payload())


def test_save_deepseek_and_runtime_config(db, monkeypatch):
    _patch_settings(monkeypatch)
    saved = ms.save_model_config(db, _valid_payload(asr_model="任意值"))
    assert saved["asr_mode"] == "deepseek"
    assert saved["asr_model"] == "deepseek-asr"  # 接口无模型参数，固定占位名
    assert ms.asr_config(db) == {"mode": "deepseek", "model": "deepseek-asr"}


def test_coerce_deepseek_model_is_fixed(db, monkeypatch):
    _patch_settings(monkeypatch)
    ms.save_model_config(db, _valid_payload())
    row = db.get(Kv, "asr_model")
    assert row is not None
    row.value = "Qwen/Qwen3-ASR-1.7B"
    db.commit()
    assert ms.asr_config(db)["model"] == "deepseek-asr"


def test_settings_payload_exposes_deepseek(db, monkeypatch):
    _patch_settings(monkeypatch)
    payload = api_settings._models_payload(db)
    assert payload["asr"]["options"]["deepseek"] == "DeepSeek 语音识别"
    assert payload["asr"]["deepseek_models"] == ["deepseek-asr"]
