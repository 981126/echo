"""R-156：草稿定稿与版本留痕——快照/版本链/定稿接口/讨论自动定稿/版本链接入 AI 学习。"""

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
from app.models.draft import Draft
from app.models.persona import PersonaTag
from app.models.platform import Creator
from app.services.draft_versions import (
    chains_for_drafts,
    list_versions,
    snapshot_version,
    version_stages,
)


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


# ---------- 快照与版本链 ----------


def test_snapshot_stores_full_content(db):
    d = Draft(title="标题", cover_text="封面", script="正文", tags=json.dumps(["求职"], ensure_ascii=False))
    db.add(d)
    db.commit()
    v = snapshot_version(db, d, source="manual")
    assert (v.title, v.cover_text, v.script, v.tags, v.source) == ("标题", "封面", "正文", '["求职"]', "manual")
    assert len(list_versions(db, d.id)) == 1


def test_version_stages_prefers_versions(db):
    d = Draft(title="t", script="正文v1", original_script="原始素材")
    db.add(d)
    db.commit()
    snapshot_version(db, d)
    d.script = "正文v2"
    db.commit()
    snapshot_version(db, d)
    assert version_stages(db, d) == ["正文v1", "正文v2"]


def test_version_stages_fallback_to_original_vs_script(db):
    d = Draft(title="t", script="我的正文", original_script="素材原文")
    db.add(d)
    db.commit()
    snapshot_version(db, d)  # 只有 1 条版本 → 退回原文→当前稿
    assert version_stages(db, d) == ["素材原文", "我的正文"]


def test_version_stages_empty_without_any(db):
    d = Draft(title="t", script="", original_script="")
    db.add(d)
    db.commit()
    assert version_stages(db, d) == []


def test_chains_for_drafts_batch(db):
    a = Draft(title="a", script="va1")
    b = Draft(title="b", script="", original_script="")
    db.add_all([a, b])
    db.commit()
    snapshot_version(db, a)
    a.script = "va2"
    db.commit()
    snapshot_version(db, a)
    out = chains_for_drafts(db, [a, b])
    assert out[a.id] == ["va1", "va2"]
    assert out[b.id] == []


# ---------- 版本链 → AI 学习 ----------


def test_analyze_diff_multistage_prompt(db, monkeypatch):
    from app.services import diff_analysis

    captured: dict = {}

    class _LLM:
        def chat_json(self, messages, **_k):
            captured["user"] = messages[-1]["content"]
            return {"suggestions": [{"label": "更口语", "description": "d", "reason": "r"}]}

    monkeypatch.setattr(diff_analysis, "get_prompt", lambda key, db=None: "系统提示")
    out = diff_analysis.analyze_diff(["第一版内容在这里", "第二版内容更长一些", "第三版最终定稿"], llm=_LLM())
    assert out and out[0]["label"] == "更口语"
    assert "初稿" in captured["user"] and "定稿" in captured["user"] and "第 2 稿" in captured["user"]


def test_analyze_diff_ignores_adjacent_duplicates(db, monkeypatch):
    from app.services import diff_analysis

    monkeypatch.setattr(diff_analysis, "get_prompt", lambda key, db=None: "sys")
    assert diff_analysis.analyze_diff(["同一版", "同一版"], llm=object()) == []


def test_apply_diff_suggestions_uses_version_chain(db, monkeypatch):
    from app.services import diff_analysis

    d = Draft(title="t", script="v2", source="ai")
    db.add(d)
    db.commit()
    snapshot_version(db, d, source="ai_generate")
    d.script = "v3"
    db.commit()
    snapshot_version(db, d, source="manual")  # R-209：AI 版 → 作者定稿 才是可归因的作者修改

    seen: dict = {}

    def fake_analyze(stages, db=None):
        seen["stages"] = stages
        return [{"label": "更短", "description": "少废话", "reason": "第三版删了套话"}]

    monkeypatch.setattr(diff_analysis, "analyze_sourced_diff", fake_analyze)
    added = diff_analysis.apply_diff_suggestions(db, d)
    assert seen["stages"] == [("ai_generate", "v2"), ("manual", "v3")]
    assert added == 1
    tag = db.query(PersonaTag).filter(PersonaTag.label == "更短").first()
    assert tag is not None and tag.status == "suggested" and "依据" in tag.description


def test_diff_task_returns_added(db, monkeypatch):
    from app.services import diff_analysis

    d = Draft(title="t", script="v2", source="ai")
    db.add(d)
    db.commit()
    snapshot_version(db, d, source="ai_generate")
    d.script = "v3"
    db.commit()
    snapshot_version(db, d, source="manual")  # R-209：AI 版 → 作者定稿 才可分析
    monkeypatch.setattr(
        diff_analysis, "analyze_sourced_diff", lambda stages, db=None: [{"label": "L", "description": "", "reason": ""}]
    )
    assert diff_analysis.diff_task(db, {"draft_id": d.id}) == 1
    assert diff_analysis.diff_task(db, {"draft_id": 999}) == 0


def test_rewrite_examples_uses_version_chain(db):
    from app.services import generation as gen

    _owner(db)
    d = Draft(title="t", script="终版正文", source="ai", creator_id=1)
    db.add(d)
    db.commit()
    snapshot_version(db, d)
    d.script = "终版正文更口语"
    db.commit()
    snapshot_version(db, d)
    text = gen._rewrite_examples(db, limit=1)
    assert "终版正文" in text and "更口语" in text


# ---------- 接口 ----------


def test_finalize_updates_and_snapshots(db, monkeypatch):
    _owner(db)
    d = Draft(title="旧", script="旧正文", source="ai")
    db.add(d)
    db.commit()
    snapshot_version(db, d, source="ai_generate")  # AI 生成的第一版（如 AI 生成草稿落库时留的）
    kinds: list[str] = []
    monkeypatch.setattr("app.tasks.start_task", lambda kind, payload, fn: kinds.append(kind) or 5)

    r = _client(db).post(f"/api/drafts/{d.id}/finalize", json={"title": "新", "cover_text": "封面", "script": "定稿正文", "tags": ["求职"]})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["version"]["script"] == "定稿正文"
    assert body["version"]["source"] == "manual"
    assert db.get(Draft, d.id).title == "新"
    assert db.get(Draft, d.id).tags == '["求职"]'
    # R-209：AI 版 → 作者定稿，链可归因，触发版本链分析
    assert kinds == ["diff_analysis"]

    r2 = _client(db).get(f"/api/drafts/{d.id}/versions")
    assert r2.status_code == 200
    assert len(r2.json()) == 2


def test_finalize_pure_manual_never_triggers_diff(db, monkeypatch):
    """R-210：纯手写稿（链中无 AI 侧版本）多次定稿也不触发差异分析——手写稿只学正文。"""
    _owner(db)
    d = Draft(title="手写", script="旧正文")
    db.add(d)
    db.commit()
    kinds: list[str] = []
    monkeypatch.setattr("app.tasks.start_task", lambda kind, payload, fn: kinds.append(kind) or 5)

    r = _client(db).post(f"/api/drafts/{d.id}/finalize", json={"title": "手写", "script": "第一版正文", "tags": []})
    assert r.status_code == 200, r.text
    assert kinds == [], "首版不触发差异分析（R-157）"
    _client(db).post(f"/api/drafts/{d.id}/finalize", json={"title": "手写", "script": "第二版正文", "tags": []})
    assert kinds == [], "纯手写链不触发差异分析（R-210）"


def test_finalize_rejects_blank(db):
    _owner(db)
    d = Draft(title="x", script="x")
    db.add(d)
    db.commit()
    r = _client(db).post(f"/api/drafts/{d.id}/finalize", json={"title": " ", "script": ""})
    assert r.status_code == 400
    assert _client(db).get(f"/api/drafts/{d.id}/versions").json() == []


def test_versions_404_for_missing_draft(db):
    _owner(db)
    assert _client(db).get("/api/drafts/999/versions").status_code == 404


# ---------- AI 讨论自动定稿 ----------


def test_discussion_task_auto_snapshots_ai_version(db, monkeypatch):
    from app.services import draft_flow

    _owner(db)
    d = Draft(title="标题", script="讨论后正文", creator_id=1)
    db.add(d)
    db.commit()
    monkeypatch.setattr(draft_flow, "run_debate", lambda db_, draft, topic, **kw: {"draft_id": draft.id})
    kinds: list[str] = []
    monkeypatch.setattr("app.tasks.start_task", lambda kind, payload, fn: kinds.append(kind) or 1)

    draft_flow.discussion_task(db, {"draft_id": d.id, "source_text": "原文", "source_title": "素材"})
    rows = list_versions(db, d.id)
    # R-157：无版本时先留「讨论前」，跑完再留「讨论后」
    assert [r.note for r in rows] == ["讨论前", "讨论后"]
    assert all(r.source == "ai_discuss" for r in rows)
    # R-209：讨论跑完时终版是 AI 侧（作者还没定稿/回退），不触发差异分析——
    # 否则会把 AI 自己的讨论改动错当「作者偏好」学进人设（本需求的根因）
    assert kinds == []
