"""博主账号启用/禁用接口回归测试（R-101 后端漏实现 /enabled，M84 补上）。"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.api import creators
from app.db import Base, get_db
from app.models.platform import Creator, CreatorAccount


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
    app.include_router(creators.router, prefix="/api/creators")
    app.dependency_overrides[get_db] = override_db
    with TestClient(app) as c:
        yield c, session
    session.close()
    eng.dispose()


def _seed(session) -> CreatorAccount:
    owner = Creator(kind="owner", name="我", is_current=True)
    session.add(owner)
    session.commit()
    acc = CreatorAccount(creator_id=owner.id, platform="douyin", nickname="测试号", enabled=True)
    session.add(acc)
    session.commit()
    return acc


def test_toggle_enabled(client):
    c, session = client
    acc = _seed(session)
    # 禁用
    r = c.post(f"/api/creators/accounts/{acc.id}/enabled", json={"enabled": False})
    assert r.status_code == 200, r.text
    assert r.json()["enabled"] is False
    session.refresh(acc)
    assert acc.enabled is False
    # 重新启用
    r = c.post(f"/api/creators/accounts/{acc.id}/enabled", json={"enabled": True})
    assert r.status_code == 200, r.text
    assert r.json()["enabled"] is True
    session.refresh(acc)
    assert acc.enabled is True


def test_toggle_enabled_missing_account(client):
    c, _ = client
    r = c.post("/api/creators/accounts/999/enabled", json={"enabled": False})
    assert r.status_code == 404
