"""人设档案批量操作接口测试（R-123：一键拒绝建议 + 已确认档案多选删除）。"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.api import persona as persona_api
from app.db import Base, get_db
from app.models.platform import Creator
from app.models.persona import PersonaTag


@pytest.fixture()
def client(tmp_path):
    eng = create_engine(f"sqlite:///{tmp_path}/t.db", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=eng)
    session = sessionmaker(bind=eng, autoflush=False, autocommit=False)()

    def override_db():
        try:
            yield session
        finally:
            pass

    app = FastAPI()
    app.include_router(persona_api.router, prefix="/api/persona")
    app.dependency_overrides[get_db] = override_db
    with TestClient(app) as c:
        yield c, session
    session.close()
    eng.dispose()


def _seed(db):
    """当前主博主 + 另一个博主，各自带 suggested/confirmed 标签。"""
    owner = Creator(kind="owner", name="我", is_current=True)
    db.add(owner)
    db.commit()
    other = Creator(kind="owner", name="别人", is_current=False)
    db.add(other)
    db.commit()
    sug1 = PersonaTag(creator_id=owner.id, label="建议1", category="style", status="suggested")
    sug2 = PersonaTag(creator_id=owner.id, label="建议2", category="topic", status="suggested")
    conf1 = PersonaTag(creator_id=owner.id, label="确认1", category="style", status="confirmed")
    conf2 = PersonaTag(creator_id=owner.id, label="确认2", category="redline", status="confirmed")
    other_tag = PersonaTag(creator_id=other.id, label="别人标签", category="style", status="confirmed")
    db.add_all([sug1, sug2, conf1, conf2, other_tag])
    db.commit()
    return sug1, sug2, conf1, conf2, other_tag


def test_reject_all_marks_suggested_rejected(client):
    c, session = client
    sug1, sug2, _, _, _ = _seed(session)
    r = c.post("/api/persona/reject-all", json={})
    assert r.status_code == 200, r.text
    assert r.json()["count"] == 2
    session.refresh(sug1)
    session.refresh(sug2)
    assert sug1.status == "rejected"
    assert sug2.status == "rejected"


def test_reject_all_idempotent_when_empty(client):
    c, session = client
    _seed(session)
    c.post("/api/persona/reject-all", json={})
    r = c.post("/api/persona/reject-all", json={})
    assert r.status_code == 200
    assert r.json()["count"] == 0


def test_batch_delete_only_removes_current_creator(client):
    c, session = client
    _, _, conf1, conf2, other_tag = _seed(session)
    r = c.post("/api/persona/tags/batch-delete", json={"ids": [conf1.id, conf2.id, other_tag.id]})
    assert r.status_code == 200, r.text
    assert r.json()["deleted"] == 2
    assert session.get(PersonaTag, conf1.id) is None
    assert session.get(PersonaTag, conf2.id) is None
    assert session.get(PersonaTag, other_tag.id) is not None  # 别人博主的标签不受影响


def test_batch_delete_empty_ids(client):
    c, _ = client
    r = c.post("/api/persona/tags/batch-delete", json={"ids": []})
    assert r.status_code == 200
    assert r.json()["deleted"] == 0
