"""R-187：缺口选题（AI 补位；不可用时优雅降级）。"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest
from conftest import ensure_schema, fresh_engine
from sqlalchemy.orm import sessionmaker

from app.models.platform import Creator
from app.models.persona import PersonaTag
from app.services import opportunity


@pytest.fixture()
def db(tmp_path):
    opportunity._CACHE.clear()
    eng = fresh_engine()
    ensure_schema(eng)
    session = sessionmaker(bind=eng, autoflush=False, autocommit=False)()
    yield session
    session.close()


def test_gap_degrades_without_llm(db, monkeypatch):
    owner = Creator(kind="owner", name="我", is_current=True)
    db.add(owner)
    db.commit()
    db.add(PersonaTag(creator_id=owner.id, label="直白犀利", category="style", layer="core_dna", status="confirmed", version=1))
    db.commit()

    class _Boom:
        def call_json(self, *a, **k):
            raise RuntimeError("no llm")

    monkeypatch.setattr("app.services.persona.PersonaService", lambda *a, **k: _Boom())
    # 模型不可用：应返回空 items + note，而不是抛错
    res = opportunity.gap_suggestions(db, limit=5)
    assert res["items"] == []
    assert res["note"]
