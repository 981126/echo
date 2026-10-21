"""R-159：drafts.status 新增 done（完成），状态流转被接口接受。"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest
from conftest import ensure_schema, fresh_engine
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from app.db import get_db
from app.models.draft import Draft
from app.models.platform import Creator


@pytest.fixture()
def db(tmp_path):
    eng = fresh_engine()
    ensure_schema(eng)
    session = sessionmaker(bind=eng, autoflush=False, autocommit=False)()
    yield session
    session.close()


def _client(db):
    from app.api import drafts as drafts_api

    app = FastAPI()
    app.include_router(drafts_api.router, prefix="/api/drafts")

    def override_db():
        yield db

    app.dependency_overrides[get_db] = override_db
    return TestClient(app)


def _draft(db):
    db.add(Creator(kind="owner", name="我", is_current=True))
    d = Draft(title="标题", script="正文")
    db.add(d)
    db.commit()
    return d


def test_status_done_roundtrip(db):
    d = _draft(db)
    c = _client(db)
    for status in ("done", "used", "draft", "archived", "deleted"):
        r = c.patch(f"/api/drafts/{d.id}", json={"status": status})
        assert r.status_code == 200, (status, r.text)
        assert db.get(Draft, d.id).status == status


def test_status_rejects_unknown(db):
    d = _draft(db)
    r = _client(db).patch(f"/api/drafts/{d.id}", json={"status": "finished"})
    assert r.status_code == 422
    assert db.get(Draft, d.id).status == "draft"
