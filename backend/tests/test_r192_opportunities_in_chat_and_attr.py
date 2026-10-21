"""R-192：内容机会三路进 AI 对话 + 选题归因 + 评论聚类模型1 语义聚类（降级）。"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest
from conftest import ensure_schema, fresh_engine
from sqlalchemy.orm import sessionmaker

from app.models.draft import Draft
from app.models.platform import Creator
from app.services import opportunity
from app.services.chat_service import _get_content_opportunities


@pytest.fixture()
def db(tmp_path):
    opportunity._CACHE.clear()
    eng = fresh_engine()
    ensure_schema(eng)
    session = sessionmaker(bind=eng, autoflush=False, autocommit=False)()
    yield session
    session.close()
    opportunity._CACHE.clear()


def test_attribution_empty(db):
    res = opportunity.topic_attribution(db)
    assert res["by_tag"] == [] and res["draft_count"] == 0


def test_attribution_groups_by_tag(db):
    owner = Creator(kind="owner", name="我", is_current=True)
    db.add(owner)
    db.commit()
    db.add(Draft(creator_id=owner.id, title="A", status="done", tags='["求职","面试"]', performance='{"totals":{"plays":1000,"likes":50,"favorites":5,"comments":2}}'))
    db.add(Draft(creator_id=owner.id, title="B", status="done", tags='["求职"]', performance='{"totals":{"plays":100,"likes":1,"favorites":0,"comments":0}}'))
    db.commit()
    res = opportunity.topic_attribution(db)
    tags = {t["tag"] for t in res["by_tag"]}
    assert {"求职", "面试"} <= tags
    assert res["draft_count"] == 2


def test_chat_tool_content_opportunities(db, monkeypatch):
    db.add(Creator(kind="owner", name="我", is_current=True))
    db.commit()
    monkeypatch.setattr(opportunity, "gap_suggestions", lambda db, limit=6: {"items": [], "note": ""})
    out = _get_content_opportunities(db, {"want": "all"})
    assert "comment_clusters" in out and "weekly_pack" in out and "gap" in out


def test_comment_clusters_llm_falls_back_without_llm(db, monkeypatch):
    # 模拟模型不可用（返回空）时 use_llm=True 不应抛错（回退本地聚类）
    monkeypatch.setattr(opportunity, "_ask_groups", lambda listing, deadline: [])
    res = opportunity.comment_clusters(db, limit=5, use_llm=True)
    assert "clusters" in res
