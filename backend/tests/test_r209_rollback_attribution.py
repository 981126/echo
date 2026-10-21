"""R-209：回退留痕 + 版本链按 source 归因 + 讨论结果被回退的负反馈。

场景还原（作者原话）：手动建稿 → 定稿 → 讨论 → 回退原稿 → 采用/好评，
系统不得把「AI 讨论结果」当成作者认可的方向。
"""

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

from app.db import get_db
from app.models.discussion import DraftDiscussion
from app.models.draft import Draft
from app.models.platform import Creator
from app.services import diff_analysis
from app.services import generation as gen
from app.services.debate import mark_latest_run_reverted
from app.services.draft_versions import chains_with_sources, snapshot_version


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


def _reverted_chain_draft(db, creator_id=None) -> Draft:
    """手写稿：定稿（原稿）→ 讨论（讨论后）→ 回退（rollback=原稿）。"""
    d = Draft(title="手写稿", script="作者原稿正文", source="manual", creator_id=creator_id)
    db.add(d)
    db.commit()
    snapshot_version(db, d, source="manual", note="定稿")
    d.script = "AI 讨论后的正文"
    db.commit()
    snapshot_version(db, d, source="ai_discuss", note="讨论后")
    d.script = "作者原稿正文"
    db.commit()
    snapshot_version(db, d, source="rollback", note="回退到版本 #1")
    return d


# ---------- 回退跨过 AI 版 → 运行头回填 reverted ----------


def test_rollback_crossing_ai_version_marks_run_reverted(db, monkeypatch):
    d = Draft(title="t", script="原稿")
    db.add(d)
    db.commit()
    v1 = snapshot_version(db, d, source="manual")
    d.script = "讨论后"
    db.commit()
    snapshot_version(db, d, source="ai_discuss")
    run = DraftDiscussion(
        draft_id=d.id, round=0, actor="system", kind="run",
        content=json.dumps({"gen": {"model": "m1"}, "critic": {"model": "m2"}, "rounds": 5}, ensure_ascii=False),
    )
    db.add(run)
    db.commit()
    monkeypatch.setattr("app.tasks.start_task", lambda *a, **k: 1)  # 不真入队差异分析

    r = _client(db).post(f"/api/drafts/{d.id}/versions/{v1.id}/rollback")
    assert r.status_code == 200, r.text
    payload = json.loads(db.get(DraftDiscussion, run.id).content)
    assert payload["reverted"] is True
    # 重复回退不重复打标（幂等）
    assert mark_latest_run_reverted(db, d.id) is False


def test_rollback_not_crossing_ai_version_no_mark(db, monkeypatch):
    d = Draft(title="t", script="v1")
    db.add(d)
    db.commit()
    v1 = snapshot_version(db, d, source="manual")
    d.script = "v2"
    db.commit()
    snapshot_version(db, d, source="manual")
    monkeypatch.setattr("app.tasks.start_task", lambda *a, **k: 1)

    r = _client(db).post(f"/api/drafts/{d.id}/versions/{v1.id}/rollback")
    assert r.status_code == 200, r.text
    assert db.query(DraftDiscussion).filter(DraftDiscussion.draft_id == d.id).count() == 0


# ---------- 改稿样本：配对 = 最后作者侧版本 ← 前一版 ----------


def test_rewrite_examples_pair_is_discussed_to_reverted(db):
    """AI 稿被讨论又被回退：改稿样本必须是【AI 稿 讨论后 → 作者改后 原稿】，不能反过来。"""
    _owner(db)
    d = Draft(title="t", script="作者原稿正文", source="ai", creator_id=1)
    db.add(d)
    db.commit()
    snapshot_version(db, d, source="ai_generate")
    d.script = "AI 讨论后的正文"
    db.commit()
    snapshot_version(db, d, source="ai_discuss")
    d.script = "作者原稿正文"
    db.commit()
    snapshot_version(db, d, source="rollback")

    text = gen._rewrite_examples(db, limit=1)
    assert "【AI 稿】" in text and "AI 讨论后的正文" in text
    assert "【作者改后】作者原稿正文" in text


def test_reverted_lessons_injected(db):
    """生成上下文注入「作者改回了自己的原稿」反面信号。"""
    owner = _owner(db)
    _reverted_chain_draft(db, creator_id=owner.id)
    text = gen._reverted_lessons(db)
    assert "改回了自己原来的稿子" in text
    assert "AI 讨论后的正文" in text and "作者原稿正文" in text


def test_reverted_lessons_empty_without_revert(db):
    owner = _owner(db)
    d = Draft(title="t", script="终版", source="ai", creator_id=owner.id)
    db.add(d)
    db.commit()
    snapshot_version(db, d, source="ai_generate")
    d.script = "作者改后的终版"
    db.commit()
    snapshot_version(db, d, source="manual")  # 正常改稿，不是回退
    assert gen._reverted_lessons(db) == ""


# ---------- 差异分析：source 归因 ----------


def test_analyzable_rules():
    A = diff_analysis.analyzable
    assert A([("manual", "原稿"), ("ai_discuss", "讨论后")]) is False  # 终版是 AI 侧
    assert A([("manual", "原稿"), ("ai_discuss", "讨论后"), ("rollback", "原稿")]) is True
    assert A([("ai_generate", "AI稿"), ("manual", "作者定稿")]) is True
    assert A([("manual", "v1"), ("manual", "v2")]) is False  # 纯手写链（R-210）
    assert A([("ai_generate", "只有一版")]) is False


def test_analyze_sourced_diff_labels_versions(db, monkeypatch):
    captured: dict = {}

    class _LLM:
        def chat_json(self, messages, **_k):
            captured["user"] = messages[-1]["content"]
            return {"suggestions": [{"label": "L", "description": "d", "reason": "r"}]}

    monkeypatch.setattr(diff_analysis.llm_router, "primary_llm", lambda db_, feature: _LLM())
    monkeypatch.setattr(diff_analysis, "get_prompt", lambda key, db=None: "系统提示")
    out = diff_analysis.analyze_sourced_diff(
        [("manual", "原稿内容"), ("ai_discuss", "讨论后内容"), ("rollback", "原稿内容")], db=db
    )
    assert out and out[0]["label"] == "L"
    user = captured["user"]
    assert "【AI 稿" in user and "【作者回退" in user and "【作者定稿" in user
    assert "归因规则" in user and "不是作者改的" in user


def test_chains_with_sources(db):
    d = Draft(title="t", script="s")
    db.add(d)
    db.commit()
    snapshot_version(db, d, source="manual")
    d.script = "s2"
    db.commit()
    snapshot_version(db, d, source="ai_discuss")
    assert chains_with_sources(db, [d])[d.id] == [("manual", "s"), ("ai_discuss", "s2")]
    # 不足 2 版不返回
    d2 = Draft(title="t2", script="x")
    db.add(d2)
    db.commit()
    snapshot_version(db, d2)
    assert d2.id not in chains_with_sources(db, [d2])
