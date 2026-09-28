"""R-184：发布回填字段与表现查询。"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import Base
from app.models.draft import Draft
from app.api.drafts import draft_performance
from app.schemas.draft import DraftUpdate


@pytest.fixture()
def db(tmp_path):
    eng = create_engine(f"sqlite:///{tmp_path}/t.db", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=eng)
    session = sessionmaker(bind=eng, autoflush=False, autocommit=False)()
    yield session
    session.close()
    eng.dispose()


def test_draft_update_accepts_publish_fields():
    upd = DraftUpdate(publish_platform="douyin", publish_url="https://x/1", published_at="2026-09-28T10:00:00")
    assert upd.publish_platform == "douyin"
    assert upd.publish_url == "https://x/1"
    assert upd.published_at is not None


def test_performance_without_video_returns_empty(db):
    d = Draft(title="t", script="x", publish_url="https://x/1", publish_platform="douyin")
    db.add(d)
    db.commit()
    res = draft_performance(d.id, db)
    assert res["platforms"] == []
    assert res["totals"] is None
