"""R-180：人设只学当前主博主（对标博主素材不进人设）。"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest
from conftest import ensure_schema, fresh_engine
from sqlalchemy.orm import sessionmaker

from app.models.platform import Creator
from app.models.task import BackgroundTask
from app.models.video import Transcript, Video
from app.services import ingest as ingest_mod


@pytest.fixture()
def db(tmp_path):
    eng = fresh_engine()
    ensure_schema(eng)
    session = sessionmaker(bind=eng, autoflush=False, autocommit=False)()
    yield session
    session.close()


def _creator(db, name, kind="owner", parent=None, current=False):
    c = Creator(kind=kind, parent_id=parent, name=name, is_current=current)
    db.add(c)
    db.commit()
    db.refresh(c)
    return c


def _video(db, owner, filename, text):
    v = Video(creator_id=owner.id, filename=filename, title=filename, is_ad=False)
    db.add(v)
    db.flush()
    db.add(Transcript(video_id=v.id, transcript_text=text, corrected_text=""))
    db.commit()
    db.refresh(v)
    return v


class _FakePersonaService:
    def __init__(self):
        self.calls: list[str] = []

    def analyze_one(self, text: str) -> dict:
        self.calls.append(text)
        return {"tags": [{"label": "x", "description": "", "dimension": "语气"}], "redlines": []}

    def merge_full(self, parts):
        return {"tags": [{"label": "x", "description": "", "dimension": "语气"}], "redlines": []}

    def merge_incremental(self, current, new_part):
        return current

    def compare_profiles(self, a, b):
        return {"score": 100.0, "reason": "ok"}


def test_enqueue_skips_benchmark_material(db, monkeypatch):
    owner = _creator(db, "我", kind="owner", current=True)
    bm = _creator(db, "对标", kind="benchmark", parent=owner.id)
    calls: list[dict] = []

    def fake_start(kind, payload, fn):
        calls.append(payload)
        return 999

    monkeypatch.setattr("app.tasks.start_task", fake_start)

    bm_video = _video(db, bm, "bm.mp4", "对标博主的话")
    assert ingest_mod.enqueue_persona_incremental(db, video=bm_video) is None
    assert calls == []
    assert db.query(BackgroundTask).count() == 0

    owner_video = _video(db, owner, "me.mp4", "我的话")
    assert ingest_mod.enqueue_persona_incremental(db, video=owner_video) == 999
    assert calls and calls[0]["creator_id"] == owner.id


def test_incremental_task_forced_to_owner(db, monkeypatch):
    owner = _creator(db, "我", kind="owner", current=True)
    bm = _creator(db, "对标", kind="benchmark", parent=owner.id)
    _video(db, owner, "me.mp4", "这是主博主的稿子")
    _video(db, bm, "bm.mp4", "这是对标博主的稿子")

    fake = _FakePersonaService()
    monkeypatch.setattr(ingest_mod, "PersonaService", lambda: fake)

    # 即使 payload 传了对标博主 id，也应被纠正回当前主博主
    ingest_mod.persona_incremental_task(db, {"creator_id": bm.id, "video_id": 0})

    assert fake.calls == ["这是主博主的稿子"]
