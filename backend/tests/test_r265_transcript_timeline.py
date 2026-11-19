"""R-265：ASR 分句时间轴解析、转写落库与复盘补时间轴。"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest
from conftest import ensure_schema, fresh_engine
from sqlalchemy.orm import sessionmaker

from app.config import get_settings
from app.models.video import Transcript, Video
from app.services import ingest
from app.services import transcript_timeline
from app.services.aliyun_filetrans import AliyunFileTrans
from app.services.tencent_asr import TencentAsr
from app.services.transcription import Transcriber, TranscriptResult


@pytest.fixture()
def db(tmp_path):
    eng = fresh_engine()
    ensure_schema(eng)
    session = sessionmaker(bind=eng, autoflush=False, autocommit=False)()
    yield session
    session.close()


def test_tencent_extract_sentences_skips_bad_items():
    payload = {
        "ResultDetail": [
            {"FinalSentence": "第一句。", "BeginTime": 0, "EndTime": 2480},
            {"FinalSentence": "", "BeginTime": 3000, "EndTime": 4000},
            {"FinalSentence": "时间戳非法", "BeginTime": "x", "EndTime": 5000},
            {"FinalSentence": "倒序", "BeginTime": 8000, "EndTime": 7000},
            {"FinalSentence": "第二句。", "BeginTime": 5000, "EndTime": 6900},
        ]
    }
    assert TencentAsr._extract_sentences(payload) == [
        {"start_ms": 0, "end_ms": 2480, "text": "第一句。"},
        {"start_ms": 5000, "end_ms": 6900, "text": "第二句。"},
    ]


def test_aliyun_extract_sentences():
    payload = {
        "Result": {
            "Sentences": [
                {"Text": "第一句。", "BeginTime": 100, "EndTime": 1900},
                {"Text": "", "BeginTime": 2000, "EndTime": 3000},
                {"Text": "第二句。", "BeginTime": 3000, "EndTime": 5200},
            ]
        }
    }
    assert AliyunFileTrans._extract_sentences(payload) == [
        {"start_ms": 100, "end_ms": 1900, "text": "第一句。"},
        {"start_ms": 3000, "end_ms": 5200, "text": "第二句。"},
    ]


def test_transcriber_falls_back_when_provider_has_no_timeline(tmp_path, monkeypatch):
    class _Fake:
        def __init__(self, settings=None, model=None):
            pass

        def transcribe_file(self, _path):
            return "只有正文"

    import app.services.tencent_asr as tencent_mod

    monkeypatch.setattr(tencent_mod, "TencentAsr", _Fake)
    path = tmp_path / "demo.wav"
    path.write_bytes(b"RIFF")
    result = Transcriber(settings=get_settings(), mode="tencent").transcribe_detailed(path)
    assert result.text == "只有正文"
    assert result.precision == "none"
    assert result.sentences == []


def test_import_video_persists_sentences(db, monkeypatch):
    video = Video(filename="r265.mp4", title="测试素材")
    db.add(video)
    db.commit()

    class _FakeTranscriber:
        def __init__(self, settings=None, mode=None, model=None):
            pass

        def transcribe_detailed(self, _path):
            return TranscriptResult(
                "第一句。第二句。",
                [{"start_ms": 0, "end_ms": 1200, "text": "第一句。"},
                 {"start_ms": 1200, "end_ms": 3000, "text": "第二句。"}],
                "tencent",
                "sentence",
            )

    monkeypatch.setattr(ingest, "Transcriber", _FakeTranscriber)
    monkeypatch.setattr(ingest, "correct_transcript", lambda text, **kwargs: text)
    monkeypatch.setattr(ingest, "enqueue_persona_incremental", lambda *args, **kwargs: None)
    monkeypatch.setattr(ingest.PersonaService, "suggest_video_tags", lambda self, text: {})

    ingest.import_video_task(db, {"video_id": video.id})
    db.expire_all()
    transcript = db.query(Transcript).filter_by(video_id=video.id).one()
    assert transcript.timeline_precision == "sentence"
    assert transcript.timeline_source == "tencent"
    assert "第一句。" in transcript.sentences


def test_ensure_sentences_only_touches_timeline(db, monkeypatch, tmp_path):
    media = get_settings().videos_dir / "r265-timeline.mp4"
    media.parent.mkdir(parents=True, exist_ok=True)
    media.write_bytes(b"fake")
    video = Video(filename=media.name, title="补时间轴")
    db.add(video)
    db.flush()
    db.add(
        Transcript(
            video_id=video.id,
            transcript_text="原始正文",
            corrected_text="校对正文",
            asr_status="done",
            asr_provider="deepseek",
        )
    )
    db.commit()

    class _FakeTranscriber:
        def __init__(self, settings=None, mode=None):
            self.mode = mode

        def transcribe_detailed(self, _path):
            return TranscriptResult("另一段文本", [{"start_ms": 0, "end_ms": 900, "text": "原始正文"}], "tencent", "sentence")

    monkeypatch.setattr(transcript_timeline, "Transcriber", _FakeTranscriber)
    ok, reason = transcript_timeline.ensure_sentences(db, video)
    assert ok, reason
    db.refresh(video)
    transcript = video.transcript
    assert transcript.timeline_precision == "sentence"
    assert transcript.timeline_source == "tencent"
    assert transcript.transcript_text == "原始正文"
    assert transcript.corrected_text == "校对正文"

    # 已有句子级时间轴 → 直接复用，不再调用服务商
    ok_again, _ = transcript_timeline.ensure_sentences(db, video)
    assert ok_again


def test_ensure_sentences_reports_missing_file(db):
    video = Video(filename="not-exist.mp4", title="缺文件")
    db.add(video)
    db.flush()
    db.add(Transcript(video_id=video.id, transcript_text="正文", asr_status="done"))
    db.commit()
    ok, reason = transcript_timeline.ensure_sentences(db, video)
    assert not ok
    assert "本地视频文件缺失" in reason
