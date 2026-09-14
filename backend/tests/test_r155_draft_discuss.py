"""R-155：草稿「基于原文讨论」——原文解析、写回标题/封面字/正文/标签、留痕追加、接口三态。"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import Base, get_db
from app.models.discussion import DraftDiscussion
from app.models.draft import Draft
from app.models.kv import Kv
from app.models.platform import Creator
from app.services import llm_router
from app.services.draft_flow import resolve_discussion_source


@pytest.fixture()
def db(tmp_path):
    eng = create_engine(f"sqlite:///{tmp_path}/t.db", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=eng)
    session = sessionmaker(bind=eng, autoflush=False, autocommit=False)()
    yield session
    session.close()
    eng.dispose()


def _set_kv(db, key, value):
    row = db.get(Kv, key)
    if row is None:
        db.add(Kv(key=key, value=str(value)))
    else:
        row.value = str(value)
    db.commit()


def _owner(db):
    c = Creator(kind="owner", name="我", is_current=True)
    db.add(c)
    db.commit()
    return c


def _configure_models(db):
    _set_kv(db, "model1_vendor", "deepseek")
    _set_kv(db, "model1_model", "deepseek-flash")
    _set_kv(db, "model2_vendor", "kimi")
    _set_kv(db, "model2_model", "kimi-k2.6")
    _set_kv(db, "gen_role", "model1")
    _set_kv(db, "referee_role", "model2")
    _set_kv(db, "debate_rounds", "1")


def _fake_llm(monkeypatch, *, json_payload, chat_text="评审/修订正文"):
    class _FakeClient:
        def __init__(self, slot):
            self.vendor = slot["vendor"]

        def chat_json(self, *_a, **_k):
            return dict(json_payload)

        def chat(self, *_a, **_k):
            return chat_text

    monkeypatch.setattr(llm_router, "build_client", lambda slot: _FakeClient(slot))


# ---------- 原文解析 ----------


def test_resolve_prefers_original_script(db):
    d = Draft(title="稿标题", script="洗稿后正文", original_script="素材 ASR 原文",
              source_ref=json.dumps({"source_title": "素材标题"}))
    db.add(d)
    db.commit()
    text, title = resolve_discussion_source(db, d)
    assert text == "素材 ASR 原文"
    assert title == "素材标题"


def test_resolve_falls_back_to_script(db):
    d = Draft(title="我的标题", script="我的正文", original_script="")
    db.add(d)
    db.commit()
    text, title = resolve_discussion_source(db, d)
    assert text == "我的正文"
    assert title == "我的标题"


def test_resolve_empty(db):
    d = Draft(title="", script="", original_script="")
    db.add(d)
    db.commit()
    text, _ = resolve_discussion_source(db, d)
    assert text == ""


# ---------- 基于原文讨论写回 ----------


def test_discuss_updates_fields_merges_tags_and_sets_original(db, monkeypatch):
    from app.services.debate import run_debate

    _owner(db)
    _configure_models(db)
    _fake_llm(
        monkeypatch,
        json_payload={"title": "新标题", "cover_text": "新封面字", "script": "初稿正文", "tags": ["新标签", "旧标签"]},
        chat_text="讨论后的正文",
    )
    d = Draft(title="旧标题", cover_text="旧封面", script="我的正文", original_script="", tags=json.dumps(["旧标签"], ensure_ascii=False))
    db.add(d)
    db.commit()

    run_debate(db, d, "话题", source_text="我的正文", source_title="我的标题")

    assert d.title == "新标题"
    assert d.cover_text == "新封面字"
    assert d.script == "讨论后的正文"  # 经过一轮修订
    assert json.loads(d.tags) == ["旧标签", "新标签"]  # 合并去重、保留原有顺序
    assert d.original_script == "我的正文"  # 写回供【原文对照】
    assert json.loads(d.quality)["rounds"] == 1


def test_discuss_appends_history_with_delimiter(db, monkeypatch):
    from app.services.debate import run_debate

    _owner(db)
    _configure_models(db)
    _fake_llm(monkeypatch, json_payload={"title": "t", "cover_text": "c", "script": "s", "tags": []})
    d = Draft(title="标题", script="正文", original_script="原文")
    db.add(d)
    db.commit()
    db.add(DraftDiscussion(draft_id=d.id, round=0, actor="deepseek", kind="draft", content="旧记录"))
    db.commit()

    run_debate(db, d, "标题", source_text="原文", source_title="素材")
    rows = db.query(DraftDiscussion).filter(DraftDiscussion.draft_id == d.id).order_by(DraftDiscussion.id).all()
    assert rows[0].content == "旧记录", "旧留痕保留"
    assert any("重新讨论" in r.content for r in rows), "重新讨论应写分隔说明"
    assert len(rows) > 2


# ---------- 接口 ----------


def _client(db):
    from app.api import drafts as drafts_api

    app = FastAPI()
    app.include_router(drafts_api.router, prefix="/api/drafts")

    def override_db():
        yield db

    app.dependency_overrides[get_db] = override_db
    return TestClient(app)


def test_discuss_endpoint_404(db):
    _owner(db)
    r = _client(db).post("/api/drafts/999/discuss")
    assert r.status_code == 404


def test_discuss_endpoint_400_when_no_source(db):
    _owner(db)
    d = Draft(title="", script="", original_script="")
    db.add(d)
    db.commit()
    r = _client(db).post(f"/api/drafts/{d.id}/discuss")
    assert r.status_code == 400
    assert "原文" in r.json()["detail"]


def test_discuss_endpoint_starts_task(db, monkeypatch):
    _owner(db)
    d = Draft(title="标题", script="正文", original_script="素材 ASR 原文")
    db.add(d)
    db.commit()
    captured: dict = {}

    def fake_start(kind, payload, fn):
        captured["kind"] = kind
        captured["payload"] = payload
        return 321

    monkeypatch.setattr("app.services.draft_flow.start_task", fake_start)
    r = _client(db).post(f"/api/drafts/{d.id}/discuss")
    assert r.status_code == 200, r.text
    assert r.json()["task_id"] == 321
    assert captured["kind"] == "draft_discuss"
    assert captured["payload"]["source_text"] == "素材 ASR 原文"


def test_discuss_endpoint_uses_script_for_manual_draft(db, monkeypatch):
    _owner(db)
    d = Draft(title="我的标题", script="我的正文", original_script="")
    db.add(d)
    db.commit()
    captured: dict = {}
    monkeypatch.setattr("app.services.draft_flow.start_task", lambda kind, payload, fn: captured.update(payload) or 9)
    r = _client(db).post(f"/api/drafts/{d.id}/discuss")
    assert r.status_code == 200, r.text
    assert captured["source_text"] == "我的正文"
    assert captured["source_title"] == "我的标题"
