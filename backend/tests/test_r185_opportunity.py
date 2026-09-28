"""R-185：内容机会引擎（评论聚类 + 每周灵感包 + 选题账本）。"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import Base
from app.models.hot_topic import TopicIdea
from app.models.draft import Draft
from app.models.platform import Creator
from app.services import opportunity


@pytest.fixture()
def db(tmp_path):
    opportunity._CACHE.clear()
    eng = create_engine(f"sqlite:///{tmp_path}/t.db", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=eng)
    session = sessionmaker(bind=eng, autoflush=False, autocommit=False)()
    yield session
    session.close()
    eng.dispose()


def _idea(db, title, likes=0, source="comment", used=False):
    db.add(TopicIdea(source=source, platform="douyin", title=title, detail="", snapshot_date="2026-09-28", likes=likes, used=used))
    db.commit()


def test_comment_clusters_group_similar(db):
    _idea(db, "试用期被裁怎么办？", likes=10)
    _idea(db, "试用期被裁怎么办", likes=3)  # 近义，应并入同簇
    _idea(db, "怎么谈薪资", likes=5)
    res = opportunity.comment_clusters(db)
    top = res["clusters"][0]
    assert top["count"] >= 2
    assert res["total_comments"] == 3


def test_weekly_pack_dedupes_covered(db):
    owner = Creator(kind="owner", name="我", is_current=True)
    db.add(owner)
    db.commit()
    db.add(Draft(creator_id=owner.id, title="试用期被裁怎么办", status="done"))
    db.commit()
    _idea(db, "试用期被裁怎么办", likes=20)
    _idea(db, "怎么准备面试自我介绍", likes=5)
    res = opportunity.weekly_pack(db)
    titles = [i["title"] for i in res["items"]]
    assert all("试用期被裁" not in t for t in titles)  # 已讲过 → 剔除
    assert res["covered_count"] >= 1


def test_ledger_flags_maybe_repeated(db):
    owner = Creator(kind="owner", name="我", is_current=True)
    db.add(owner)
    db.commit()
    db.add(Draft(creator_id=owner.id, title="谈薪技巧", status="used"))
    db.commit()
    _idea(db, "谈薪技巧", likes=1)
    res = opportunity.ledger(db)
    assert res["covered_count"] == 1
    assert any("谈薪" in c["title"] for c in res["maybe_repeated"])
