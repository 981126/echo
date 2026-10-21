"""R-211：反馈体系重构——状态流转触发学习分析 + status 驱动的学习通道。

- 进 done（完成）= 好、进 archived（不采用）= 差，均触发后台 LLM 分析（纯手写进 archived 豁免）；
- 心得写 feedback.insight 并注入生成上下文；历史 rating/liked 不再参与任何学习查询。
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
from app.models.feedback import Feedback
from app.models.platform import Creator
from app.services import feedback_analysis as fa
from app.services import prompt_service as ps


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


def _patch_tasks(monkeypatch, captured: list):
    monkeypatch.setattr("app.tasks.find_running_task", lambda *a, **k: None)
    monkeypatch.setattr("app.tasks.start_task", lambda kind, payload, fn: captured.append((kind, payload)) or 1)
    monkeypatch.setattr("app.api.drafts.start_task", lambda kind, payload, fn: 1)


# ---------- 触发节点 ----------


def test_done_triggers_analysis(db, monkeypatch):
    _owner(db)
    d = Draft(title="t", script="正文", source="ai")
    db.add(d)
    db.commit()
    captured: list = []
    _patch_tasks(monkeypatch, captured)

    r = _client(db).patch(f"/api/drafts/{d.id}", json={"status": "done"})
    assert r.status_code == 200, r.text
    assert ("feedback_analysis", {"draft_id": d.id, "conclusion": "done"}) in captured
    # 卡片状态条：学习分析中（R-202）
    from app.services import draft_status

    state = draft_status.read(db, d.id)
    assert state and state["state"] == "running" and state["kind"] == "feedback"


def test_archived_triggers_for_ai_touched_draft(db, monkeypatch):
    _owner(db)
    d = Draft(title="t", script="正文", source="manual")
    db.add(d)
    db.commit()
    db.add(DraftDiscussion(draft_id=d.id, round=0, actor="model1", kind="draft", content="讨论过"))
    db.commit()
    captured: list = []
    _patch_tasks(monkeypatch, captured)

    r = _client(db).patch(f"/api/drafts/{d.id}", json={"status": "archived"})
    assert r.status_code == 200, r.text
    assert ("feedback_analysis", {"draft_id": d.id, "conclusion": "archived"}) in captured


def test_archived_pure_manual_exempt(db, monkeypatch):
    """纯手写稿点不采用不触发（作者放弃 ≠ 稿子差，不进负向学习）。"""
    _owner(db)
    d = Draft(title="手写", script="自己写的", source="manual")
    db.add(d)
    db.commit()
    captured: list = []
    _patch_tasks(monkeypatch, captured)

    r = _client(db).patch(f"/api/drafts/{d.id}", json={"status": "archived"})
    assert r.status_code == 200, r.text
    assert not [c for c in captured if c[0] == "feedback_analysis"]


def test_other_status_transitions_no_trigger(db, monkeypatch):
    _owner(db)
    d = Draft(title="t", script="正文", source="ai")
    db.add(d)
    db.commit()
    captured: list = []
    _patch_tasks(monkeypatch, captured)

    r = _client(db).patch(f"/api/drafts/{d.id}", json={"status": "used"})  # 采用不触发
    assert r.status_code == 200, r.text
    assert not [c for c in captured if c[0] == "feedback_analysis"]


def test_maybe_trigger_skips_when_running(db, monkeypatch):
    _owner(db)
    d = Draft(title="t", script="正文", source="ai")
    db.add(d)
    db.commit()
    monkeypatch.setattr("app.tasks.find_running_task", lambda *a, **k: 7)
    assert fa.maybe_trigger(db, d, "done") is False


# ---------- 分析任务体：心得落库 + 状态收尾 ----------


def test_analysis_task_records_insight_and_clears(db, monkeypatch):
    _owner(db)
    d = Draft(title="t", script="正文内容", source="ai")
    db.add(d)
    db.commit()
    db.add(Feedback(draft_id=d.id, comment="结尾太拖"))
    db.commit()
    monkeypatch.setattr(fa, "analyze", lambda db_, draft, conclusion, llm=None: "结尾要更快给结果，别铺垫")

    out = fa.analysis_task(db, {"draft_id": d.id, "conclusion": "archived"})
    assert out["insight"] == "结尾要更快给结果，别铺垫"
    row = db.query(Feedback).filter(Feedback.draft_id == d.id).order_by(Feedback.id.desc()).first()
    assert row.insight == "结尾要更快给结果，别铺垫"
    assert row.liked is False  # 结论快照（不参与学习查询）
    assert row.comment == "结尾太拖"  # 不覆盖作者评价


def test_analyze_builds_context_with_versions_and_comment(db, monkeypatch):
    from app.services.draft_versions import snapshot_version

    _owner(db)
    d = Draft(title="t", script="作者定稿正文", source="ai")
    db.add(d)
    db.commit()
    snapshot_version(db, d, source="ai_generate")
    d.script = "作者定稿正文"
    db.commit()
    snapshot_version(db, d, source="manual")
    db.add(Feedback(draft_id=d.id, comment="这篇钩子好"))
    db.commit()

    captured: dict = {}

    class _LLM:
        def chat(self, messages, **_k):
            captured["user"] = messages[-1]["content"]
            return "心得：钩子要保留这种问法"

    out = fa.analyze(db, d, "done", llm=_LLM())
    assert out.startswith("心得")
    user = captured["user"]
    assert "好（作者完成了这篇稿" in user
    assert "这篇钩子好" in user
    assert "【AI 稿】" in user and "【作者定稿】" in user
    assert "归因规则" in user


# ---------- 学习通道：status 驱动，rating/liked 弃用 ----------


def test_feedback_context_status_driven(db):
    owner = _owner(db)
    done = Draft(title="完成稿", script="完成的正文", source="ai", status="done", creator_id=owner.id)
    archived = Draft(title="废稿", script="废弃的正文", source="ai", status="archived", creator_id=owner.id)
    manual_archived = Draft(title="手写废稿", script="手写废弃正文", source="manual", status="archived", creator_id=owner.id)
    old_liked = Draft(title="历史好评稿", script="历史好评正文", source="ai", status="draft", creator_id=owner.id)
    db.add_all([done, archived, manual_archived, old_liked])
    db.flush()
    db.add(Feedback(draft_id=done.id, comment="结构清楚", insight="保持三段式"))
    db.add(Feedback(draft_id=old_liked.id, rating=5, liked=True))  # 历史信号，不应再生效
    db.commit()

    text = ps.feedback_context(db)
    assert "作者完成的稿子（认可）" in text and "完成的正文" in text
    assert "作者评价：结构清楚" in text and "复盘心得：保持三段式" in text
    assert "作者不采用的稿子" in text and "废弃的正文" in text
    assert "手写废弃正文" not in text, "纯手写废稿不进负向（R-210）"
    assert "历史好评正文" not in text, "历史 rating/liked 已弃用"


def test_feedback_context_empty_without_done_or_archived(db):
    owner = _owner(db)
    db.add(Draft(title="t", script="草稿正文", source="ai", status="draft", creator_id=owner.id))
    db.commit()
    assert ps.feedback_context(db) == ""
