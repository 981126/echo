"""R-208：人设建议高置信自动确认 + 历史堆积批量处理。"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest
from conftest import ensure_schema, fresh_engine
from sqlalchemy.orm import sessionmaker

from app.models.notification import Notification
from app.models.persona import PersonaTag
from app.models.platform import Creator
from app.models.video import Transcript, Video
from app.services import ingest as ingest_mod
from app.services import persona_profile as pp


@pytest.fixture()
def db(tmp_path):
    eng = fresh_engine()
    ensure_schema(eng)
    session = sessionmaker(bind=eng, autoflush=False, autocommit=False)()
    yield session
    session.close()


def test_persist_auto_confirms_high_freq_only(db):
    profile = {
        "tags": [
            {"label": "高频立场", "description": "", "dimension": "价值观", "layer": "stance", "frequency": 3},
            {"label": "低频立场", "description": "", "dimension": "价值观", "layer": "stance", "frequency": 1},
        ],
        "redlines": ["不接医美广告"],
    }
    res = pp.persist_suggestions(db, None, profile)
    tags = {t.label: t for t in db.query(PersonaTag).all()}
    assert tags["高频立场"].status == "confirmed"
    assert tags["高频立场"].confirm_strength == pp.AUTO_CONFIRM_STRENGTH
    assert tags["低频立场"].status == "suggested"
    assert tags["低频立场"].confirm_strength == 2
    assert tags["不接医美广告"].status == "suggested"  # 红线永远人工
    assert res["auto_confirmed"] == 1
    assert res["auto_labels"] == ["高频立场"]


def test_auto_confirm_respects_rejected(db):
    db.add(PersonaTag(label="公开收入", category="style", layer="stance", status="rejected", version=1))
    db.commit()
    profile = {
        "tags": [{"label": "公开收入", "description": "", "dimension": "价值观", "layer": "stance", "frequency": 5}],
        "redlines": [],
    }
    res = pp.persist_suggestions(db, None, profile)
    assert res["auto_confirmed"] == 0
    tag = db.query(PersonaTag).filter(PersonaTag.status == "suggested").first()
    assert tag is not None and tag.label == "公开收入"


def test_auto_confirm_backlog_recomputes_frequency(db):
    db.add(PersonaTag(label="爱举例", description="", category="style", layer="mode", frequency=0, status="suggested", version=1))
    db.add(PersonaTag(label="低置信", description="", category="style", layer="stance", frequency=0, status="suggested", version=1))
    db.add(PersonaTag(label="禁区", description="", category="redline", layer="forbidden", frequency=0, status="suggested", version=1))
    db.commit()
    parts = [{"tags": [{"label": "爱举例"}]} for _ in range(3)]
    materials = [(None, "a"), (None, "b"), (None, "c")]
    res = pp.auto_confirm_backlog(db, None, parts, materials)
    tags = {t.label: t for t in db.query(PersonaTag).all()}
    assert tags["爱举例"].status == "confirmed"
    assert tags["爱举例"].confirm_strength == pp.AUTO_CONFIRM_STRENGTH
    assert tags["爱举例"].frequency == 3
    assert tags["低置信"].status == "suggested"
    assert tags["禁区"].status == "suggested"
    assert res["checked"] == 3 and res["confirmed"] == 1


def test_notify_auto_confirmed_writes_notification(db):
    ingest_mod._notify_auto_confirmed(db, {"auto_confirmed": 2, "auto_labels": ["甲", "乙"]})
    row = db.query(Notification).filter(Notification.kind == "persona_auto_confirm").first()
    assert row is not None
    assert "2 条" in row.title and row.target == "/persona"
    # 无自动确认不产生通知
    ingest_mod._notify_auto_confirmed(db, {"auto_confirmed": 0, "auto_labels": []})
    assert db.query(Notification).filter(Notification.kind == "persona_auto_confirm").count() == 1


def test_backlog_adopts_orphan_suggestions(db, monkeypatch):
    """R-208：M13 前 creator_id 为空的历史建议归属当前主博主并参与规则处理。"""
    owner = Creator(kind="owner", name="我", is_current=True)
    db.add(owner)
    db.commit()
    db.add(PersonaTag(label="爱举例", category="style", layer="mode", creator_id=None, status="suggested", version=1))
    db.commit()
    for i, txt in enumerate(["a", "b", "c"]):
        v = Video(creator_id=owner.id, filename=f"v{i}.mp4", title=f"v{i}", is_ad=False)
        db.add(v)
        db.flush()
        db.add(Transcript(video_id=v.id, transcript_text=txt, corrected_text=""))
        db.flush()
    db.commit()

    class _S:
        def analyze_one(self, text):
            return {"tags": [{"label": "爱举例", "description": "", "dimension": "结构"}], "redlines": []}

        def merge_full(self, parts):
            return {"tags": [{"label": "爱举例", "description": "", "dimension": "结构", "layer": "mode"}], "redlines": []}

    monkeypatch.setattr(ingest_mod, "PersonaService", lambda: _S())
    ingest_mod.persona_auto_confirm_backlog_task(db, {})
    tag = db.query(PersonaTag).filter(PersonaTag.label == "爱举例").first()
    assert tag is not None
    assert tag.creator_id == owner.id
    assert tag.status == "confirmed" and tag.confirm_strength == pp.AUTO_CONFIRM_STRENGTH
    assert tag.frequency >= 3

