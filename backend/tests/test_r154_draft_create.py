"""R-154：POST /api/drafts 空白草稿不落库 + 新建可带 tags（JSON 落库）。"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import Base, get_db
from app.models.draft import Draft
from app.models.platform import Creator
from app.models.video import Video


@pytest.fixture()
def db(tmp_path):
    eng = create_engine(f"sqlite:///{tmp_path}/t.db", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=eng)
    session = sessionmaker(bind=eng, autoflush=False, autocommit=False)()
    yield session
    session.close()
    eng.dispose()


def _client(db):
    from app.api import drafts as drafts_api

    app = FastAPI()
    app.include_router(drafts_api.router, prefix="/api/drafts")

    def override_db():
        yield db

    app.dependency_overrides[get_db] = override_db
    return TestClient(app)


def _owner(db):
    c = Creator(kind="owner", name="我", is_current=True)
    db.add(c)
    db.commit()
    return c


def test_create_draft_with_tags_roundtrip(db):
    _owner(db)
    r = _client(db).post("/api/drafts", json={"title": "标题", "script": "正文", "tags": ["求职", "面试"]})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["tags"] == ["求职", "面试"]
    row = db.get(Draft, body["id"])
    assert row is not None
    assert row.tags == '["求职", "面试"]'  # 落库为 JSON 文本


def test_create_draft_without_tags_defaults_empty(db):
    _owner(db)
    r = _client(db).post("/api/drafts", json={"script": "只有正文"})
    assert r.status_code == 200, r.text
    assert r.json()["tags"] == []
    assert db.get(Draft, r.json()["id"]).tags == "[]"


def test_create_blank_draft_rejected(db):
    _owner(db)
    r = _client(db).post("/api/drafts", json={"title": "", "cover_text": "", "script": "", "tags": []})
    assert r.status_code == 400
    assert "内容为空" in r.json()["detail"]
    assert db.query(Draft).count() == 0  # 库里不留空稿


def test_create_blank_whitespace_rejected(db):
    _owner(db)
    r = _client(db).post("/api/drafts", json={"title": "   ", "script": "\n  "})
    assert r.status_code == 400
    assert db.query(Draft).count() == 0


def test_create_with_only_tags_or_video_is_allowed(db):
    _owner(db)
    v = Video(filename="x.mp4")
    db.add(v)
    db.commit()
    c = _client(db)
    r1 = c.post("/api/drafts", json={"tags": ["赚钱"]})
    assert r1.status_code == 200, r1.text
    r2 = c.post("/api/drafts", json={"video_id": v.id})
    assert r2.status_code == 200, r2.text
    assert db.query(Draft).count() == 2
