"""R-194~R-197：洗稿契约 / 来源分层的聚类 / 立场提词 / 历史发布回填。"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest
from conftest import ensure_schema, fresh_engine
from sqlalchemy.orm import sessionmaker

from app.models.draft import Draft
from app.models.hot_topic import TopicIdea
from app.models.persona import PersonaTag
from app.models.platform import Creator
from app.models.work import Work
from app.services import opportunity, publish_backfill
from app.services.benchmark import REWRITE_SYSTEM


@pytest.fixture()
def db(tmp_path):
    opportunity._CACHE.clear()
    eng = fresh_engine()
    ensure_schema(eng)
    session = sessionmaker(bind=eng, autoflush=False, autocommit=False)()
    yield session
    session.close()
    opportunity._CACHE.clear()


def _idea(db, creator_id, title, likes=0):
    db.add(TopicIdea(source="comment", platform="douyin", title=title, detail="", snapshot_date="2026-09-28", likes=likes, creator_id=creator_id))
    db.commit()


def test_rewrite_contract_is_reference_rewrite():
    assert "保留核心信息与结构" not in REWRITE_SYSTEM
    assert "不借" in REWRITE_SYSTEM or "不复用" in REWRITE_SYSTEM


def test_comment_clusters_tier_by_source(db):
    owner = Creator(kind="owner", name="我", is_current=True)
    db.add(owner)
    db.commit()
    bm1 = Creator(kind="benchmark", name="对标A", parent_id=owner.id, is_current=False)
    bm2 = Creator(kind="benchmark", name="对标B", parent_id=owner.id, is_current=False)
    db.add_all([bm1, bm2])
    db.commit()
    # 我的观众问题（2 条相似）
    _idea(db, owner.id, "试用期被裁怎么办", 5)
    _idea(db, owner.id, "试用期被裁了怎么办", 3)
    # 两个对标都在问（赛道共性）
    _idea(db, bm1.id, "怎么谈薪资才不吃亏", 4)
    _idea(db, bm2.id, "谈薪资怎么谈不吃亏", 6)
    res = opportunity.comment_clusters(db, limit=10, use_llm=False)
    assert any(c["tier"] == "mine" for c in res["clusters"])
    assert any(c["tier"] == "industry" for c in res["clusters"])
    assert any("对标" in s for c in res["clusters"] for s in c["sources"])


def test_persona_profile_uses_stance_and_forbidden(db):
    owner = Creator(kind="owner", name="我", is_current=True)
    db.add(owner)
    db.commit()
    db.add(PersonaTag(creator_id=owner.id, label="反学历决定论", description="学历不等于收入", category="style", layer="stance", status="confirmed", version=1))
    db.add(PersonaTag(creator_id=owner.id, label="不卖课不收费", category="redline", layer="forbidden", status="confirmed", version=1))
    db.commit()
    from app.services.ideas_service import persona_profile

    prof = persona_profile(db)
    assert any("学历" in k for k in prof["keywords"])
    assert any("卖课" in a or "收费" in a for a in prof["avoid"])


def test_publish_backfill_apply_and_revert(db):
    owner = Creator(kind="owner", name="我", is_current=True)
    db.add(owner)
    db.commit()
    db.add(Work(creator_id=owner.id, title="面试被问离职原因怎么说"))
    db.commit()
    w = db.query(Work).first()
    db.add(Draft(creator_id=owner.id, title="面试被问离职原因怎么说", status="done", script="x"))
    db.commit()

    pv = publish_backfill.preview(db)
    assert pv["total"] == 1 and pv["pairs"][0]["work_id"] == w.id

    res = publish_backfill.apply_links(db)
    assert res["linked"] == 1
    d = db.query(Draft).first()
    assert d.work_id == w.id

    publish_backfill.revert(db)
    d = db.query(Draft).first()
    assert d.work_id is None
