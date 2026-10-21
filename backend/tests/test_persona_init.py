"""人设初始化防抖测试（R-125：进行中 persona_init 禁止重复入队）。"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest
from conftest import ensure_schema, fresh_engine
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from app.api import persona as persona_api
from app.db import get_db
from app.models.platform import Creator
from app.models.task import BackgroundTask


@pytest.fixture()
def client(tmp_path):
    eng = fresh_engine()
    ensure_schema(eng)
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


def _seed_owner(db) -> Creator:
    owner = Creator(kind="owner", name="我", is_current=True)
    db.add(owner)
    db.commit()
    return owner


def test_init_refuses_when_running_task_exists(client):
    c, session = client
    owner = _seed_owner(session)
    session.add(BackgroundTask(kind="persona_init", status="running", payload=json.dumps({"creator_id": owner.id})))
    session.commit()
    r = c.post("/api/persona/init", json={})
    assert r.status_code == 409, r.text
    assert "进行中" in r.json()["detail"]
    # 没有新增第二条任务
    assert session.query(BackgroundTask).filter(BackgroundTask.kind == "persona_init").count() == 1


def test_init_allows_when_idle(client, monkeypatch):
    c, session = client
    _seed_owner(session)

    def _fake_start_task(kind, payload, fn):
        return 12345

    monkeypatch.setattr(persona_api, "start_task", _fake_start_task)
    r = c.post("/api/persona/init", json={})
    assert r.status_code == 200, r.text
    assert r.json()["task_id"] == 12345
