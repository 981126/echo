"""R-189：发布后表现回填。"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import Base
from app.models.draft import Draft
from app.models.platform import Creator
from app.models.video import Video
from app.services.draft_performance import performance_for_video, refresh_published_performance


@pytest.fixture()
def db(tmp_path):
    eng = create_engine(f"sqlite:///{tmp_path}/t.db", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=eng)
    session = sessionmaker(bind=eng, autoflush=False, autocommit=False)()
    yield session
    session.close()
    eng.dispose()


def test_performance_for_missing_video(db):
    assert performance_for_video(db, 999) is None


def test_refresh_no_data_no_crash(db):
    owner = Creator(kind="owner", name="我", is_current=True)
    db.add(owner)
    db.commit()
    v = Video(creator_id=owner.id, filename="a.mp4", title="t")
    db.add(v)
    db.flush()
    db.add(Draft(creator_id=owner.id, video_id=v.id, status="done", title="t", script="x"))
    db.commit()
    # 素材无平台数据 → 不更新，也不报错
    assert refresh_published_performance(db) == 0
