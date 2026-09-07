"""素材库云端作品深链接口测试（R-122：来源素材/通知跨博主点对标作品可直接打开）。"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.api import works as works_api
from app.db import Base, get_db
from app.models.platform import Creator, CreatorAccount, PlatformPost
from app.models.work import Work


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
    app.include_router(works_api.router, prefix="/api/works")
    app.dependency_overrides[get_db] = override_db
    with TestClient(app) as c:
        yield c, session
    session.close()
    eng.dispose()


def _seed(db, merged=False):
    """当前主博主 + 一个对标博主（含一条作品），返回 (post, benchmark_creator)。"""
    owner = Creator(kind="owner", name="我", is_current=True)
    db.add(owner)
    db.commit()
    bm = Creator(kind="benchmark", parent_id=owner.id, name="对标A")
    db.add(bm)
    db.commit()
    acc = CreatorAccount(creator_id=bm.id, platform="douyin", nickname="对标号", enabled=True)
    db.add(acc)
    db.commit()
    post = PlatformPost(account_id=acc.id, platform="douyin", platform_post_id="x1", title="对标作品")
    db.add(post)
    db.flush()
    if merged:
        work = Work(creator_id=bm.id, title="合并对标作品")
        db.add(work)
        db.flush()
        post.work_id = work.id
    db.commit()
    return post, bm


def test_by_post_returns_benchmark_item(client):
    c, session = client
    post, bm = _seed(session)
    r = c.get(f"/api/works/by-post/{post.id}")
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["type"] == "post"
    assert data["creator_id"] == bm.id
    assert data["posts"][0]["id"] == post.id
    assert data["title"] == "对标作品"


def test_by_post_returns_merged_work(client):
    c, session = client
    post, bm = _seed(session, merged=True)
    r = c.get(f"/api/works/by-post/{post.id}")
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["type"] == "work"
    assert data["id"] == post.work_id
    assert data["creator_id"] == bm.id
    assert any(x["id"] == post.id for x in data["posts"])


def test_by_post_missing_returns_404(client):
    c, _ = client
    r = c.get("/api/works/by-post/999999")
    assert r.status_code == 404
