"""R-182：人设四层推倒重建（清空 → 四层重建为待确认 + 差异单）。"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import Base
from app.models.persona import PersonaCheck, PersonaTag
from app.models.platform import Creator
from app.models.video import Transcript, Video
from app.services import ingest as ingest_mod


@pytest.fixture()
def db(tmp_path):
    eng = create_engine(f"sqlite:///{tmp_path}/t.db", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=eng)
    session = sessionmaker(bind=eng, autoflush=False, autocommit=False)()
    yield session
    session.close()
    eng.dispose()


def _video(db, owner, filename, text):
    v = Video(creator_id=owner.id, filename=filename, title=filename, is_ad=False)
    db.add(v)
    db.flush()
    db.add(Transcript(video_id=v.id, transcript_text=text, corrected_text=""))
    db.commit()
    db.refresh(v)
    return v


class _FakePersonaService:
    def analyze_one(self, text: str) -> dict:
        return {"tags": [{"label": "直白犀利", "description": "说话不绕弯", "dimension": "语气", "evidence": "别废话"}], "redlines": []}

    def merge_full(self, parts):
        return {
            "tags": [
                {"label": "直白犀利", "description": "说话不绕弯", "dimension": "语气", "evidence": "别废话", "layer": "core_dna"},
                {"label": "反学历决定论", "description": "学历不等于能力", "dimension": "价值观", "evidence": "我中专", "layer": "stance"},
            ],
            "redlines": ["不展开会被封号的操作"],
        }

    def merge_incremental(self, current, new_part):
        return current


def test_persona_rebuild_wipes_and_layers(db, monkeypatch):
    owner = Creator(kind="owner", name="我", is_current=True)
    db.add(owner)
    db.commit()
    # 旧档案（应被清空）
    db.add(PersonaTag(creator_id=owner.id, label="旧标签", category="style", status="confirmed", version=1))
    db.add(PersonaTag(creator_id=owner.id, label="旧红线", category="redline", status="confirmed", version=1))
    _video(db, owner, "a.mp4", "这篇讲求职")
    _video(db, owner, "b.mp4", "再讲求职")
    db.commit()

    monkeypatch.setattr(ingest_mod, "PersonaService", lambda: _FakePersonaService())

    result = ingest_mod.persona_rebuild_task(db, {"creator_id": owner.id})

    rows = db.query(PersonaTag).all()
    assert all(r.status == "suggested" for r in rows)
    labels = {r.label for r in rows}
    assert labels == {"直白犀利", "反学历决定论", "不展开会被封号的操作"}
    layers = {r.label: r.layer for r in rows}
    assert layers["直白犀利"] == "core_dna"
    assert layers["反学历决定论"] == "stance"
    assert layers["不展开会被封号的操作"] == "forbidden"
    # 频次：两篇都命中「直白犀利」
    freq = {r.label: r.frequency for r in rows}
    assert freq["直白犀利"] == 2

    check = db.query(PersonaCheck).filter(PersonaCheck.mode == "rebuild").one()
    detail = json.loads(check.detail)
    assert set(detail["expired"]) == {"旧标签", "旧红线"}
    assert "直白犀利" in detail["added"]
    assert detail["previous_count"] == 2
    assert "推倒重建" in result["message"]
