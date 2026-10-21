"""R-210：纯手写判定（AI 从未参与）+ 列表接口带 pure_manual。

边界（作者拍板）：手写稿讨论过、即使内容已全部回退成自己写的，也不算纯手写。
"""

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
from app.models.discussion import DraftDiscussion
from app.models.draft import Draft
from app.models.platform import Creator
from app.services.draft_versions import is_pure_manual, pure_manual_map, snapshot_version


@pytest.fixture()
def db(tmp_path):
    eng = fresh_engine()
    ensure_schema(eng)
    session = sessionmaker(bind=eng, autoflush=False, autocommit=False)()
    yield session
    session.close()


def _owner(db):
    c = Creator(kind="owner", name="我", is_current=True)
    db.add(c)
    db.commit()
    return c


def _client(db):
    from app.api import drafts as drafts_api

    app = FastAPI()
    app.include_router(drafts_api.router, prefix="/api/drafts")

    def override_db():
        yield db

    app.dependency_overrides[get_db] = override_db
    return TestClient(app)


def test_pure_manual_true_when_ai_never_touched(db):
    d = Draft(title="手写", script="自己写的", source="manual")
    db.add(d)
    db.commit()
    snapshot_version(db, d, source="manual")  # 手动定稿不算 AI 参与
    assert is_pure_manual(db, d) is True


def test_pure_manual_false_after_discussion_even_reverted(db):
    """讨论过即使回退也不算（回退本身已是学习信号，R-209）。"""
    d = Draft(title="手写", script="原稿", source="manual")
    db.add(d)
    db.commit()
    db.add(DraftDiscussion(draft_id=d.id, round=0, actor="model1", kind="draft", content="讨论留痕"))
    db.commit()
    assert is_pure_manual(db, d) is False


def test_pure_manual_false_with_ai_version_or_ai_source(db):
    d1 = Draft(title="a", script="s", source="manual")
    d2 = Draft(title="b", script="s", source="ai")
    db.add_all([d1, d2])
    db.commit()
    snapshot_version(db, d1, source="ai_generate")  # 有 AI 侧版本
    assert is_pure_manual(db, d1) is False
    assert is_pure_manual(db, d2) is False


def test_pure_manual_map_batch(db):
    ds = [Draft(title=f"t{i}", script="s", source="manual") for i in range(3)]
    db.add_all(ds)
    db.commit()
    db.add(DraftDiscussion(draft_id=ds[1].id, round=0, actor="model1", kind="draft", content="x"))
    db.commit()
    pm = pure_manual_map(db, ds)
    assert pm == {ds[0].id: True, ds[1].id: False, ds[2].id: True}


def test_list_drafts_returns_pure_manual_and_comment(db):
    owner = _owner(db)
    from app.models.feedback import Feedback

    d = Draft(title="手写稿", script="正文", source="manual", creator_id=owner.id)
    db.add(d)
    db.commit()
    db.add(Feedback(draft_id=d.id, comment="结尾太拖"))
    db.commit()

    r = _client(db).get("/api/drafts")
    assert r.status_code == 200, r.text
    item = next(x for x in r.json() if x["id"] == d.id)
    assert item["pure_manual"] is True
    assert item["feedback_comment"] == "结尾太拖"
