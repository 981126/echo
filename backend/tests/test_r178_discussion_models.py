"""R-178：讨论留痕记录并展示「实际出结果的模型 + 版本」。

覆盖：模型文案口径（厂家标签 · 模型 ID）、留痕/运行头落库、接口返回、迁移幂等。
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
from app.models.kv import Kv
from app.models.platform import Creator
from app.services import llm_router


@pytest.fixture()
def db(tmp_path):
    eng = fresh_engine()
    ensure_schema(eng)
    session = sessionmaker(bind=eng, autoflush=False, autocommit=False)()
    yield session
    session.close()


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


def _configure_models(db, *, gen="model1", critic="model2"):
    _set_kv(db, "model1_vendor", "deepseek")
    _set_kv(db, "model1_model", "deepseek-flash")
    _set_kv(db, "model2_vendor", "kimi")
    _set_kv(db, "model2_model", "kimi-k2.6")
    _set_kv(db, "gen_role", gen)
    _set_kv(db, "referee_role", critic)
    _set_kv(db, "debate_rounds", "1")


def _fake_llm(monkeypatch, *, json_payload=None, chat_text="评审/修订正文"):
    payload = json_payload or {"title": "新标题", "cover_text": "封", "script": "初稿正文", "tags": []}

    class _FakeClient:
        def __init__(self, slot):
            self.vendor = slot["vendor"]

        def chat_json(self, *_a, **_k):
            return dict(payload)

        def chat(self, *_a, **_k):
            return chat_text

    monkeypatch.setattr(llm_router, "build_client", lambda slot: _FakeClient(slot))


# ---------- 文案口径 ----------


def test_model_label_uses_vendor_label_and_model_id():
    from app.services.debate import model_label

    assert model_label("deepseek", "deepseek-flash") == "DeepSeek · deepseek-flash"
    assert model_label("kimi", "kimi-k2.6") == "Kimi（月之暗面） · kimi-k2.6"
    # 厂家未知/缺失时不编造，退化成模型 ID
    assert model_label("", "some-model") == "some-model"
    assert model_label("unknown-vendor", "m1") == "m1"
    assert model_label("deepseek", "") == "DeepSeek"
    assert model_label("", "") == ""


# ---------- 落库 ----------


def test_discussion_rows_record_actual_model_and_run_header(db, monkeypatch):
    from app.services.debate import run_debate

    _owner(db)
    _configure_models(db)
    _fake_llm(monkeypatch)
    d = Draft(title="标题", script="正文", original_script="")
    db.add(d)
    db.commit()

    run_debate(db, d, "话题")

    rows = db.query(DraftDiscussion).filter(DraftDiscussion.draft_id == d.id).order_by(DraftDiscussion.id).all()
    run_rows = [r for r in rows if r.kind == "run"]
    assert len(run_rows) == 1, "每次讨论必须有一条运行头"
    payload = json.loads(run_rows[0].content)
    assert payload["gen"]["label"] == "DeepSeek · deepseek-flash"
    assert payload["critic"]["label"] == "Kimi（月之暗面） · kimi-k2.6"
    assert payload["rounds"] == 1
    assert payload["rounds_done"] == 1  # 结束时回填
    assert payload["degraded"] is False

    talk_rows = [r for r in rows if r.kind in {"draft", "critique", "revise"}]
    assert talk_rows, "应有初稿/评审/修订留痕"
    for r in talk_rows:
        # 关键：不再是「只有 model1/model2」，而是实际出结果的厂家 + 模型版本
        assert r.vendor in {"deepseek", "kimi"}, r.actor
        assert r.model_id in {"deepseek-flash", "kimi-k2.6"}
        assert r.used_slot in {"model1", "model2"}
    # 初稿由生成方（model1=DeepSeek）产出
    draft_row = next(r for r in talk_rows if r.kind == "draft")
    assert draft_row.vendor == "deepseek"
    assert draft_row.model_id == "deepseek-flash"
    # 系统说明行（note）不带模型
    for r in rows:
        if r.kind in {"note", "run"}:
            assert (r.vendor or "") == ""


def test_run_header_kept_when_all_drafts_fail(db, monkeypatch):
    """两次初稿都失败也要留下运行头（事后能看出「那一次本来要用谁」）。"""
    from app.services.debate import run_debate
    from app.services.llm import LLMError

    _owner(db)
    _configure_models(db)

    class _Boom:
        def __init__(self, slot):
            self.vendor = slot["vendor"]

        def chat_json(self, *_a, **_k):
            raise RuntimeError("模型挂了")

        def chat(self, *_a, **_k):
            raise RuntimeError("模型挂了")

    monkeypatch.setattr(llm_router, "build_client", lambda slot: _Boom(slot))
    d = Draft(title="标题", script="正文", original_script="")
    db.add(d)
    db.commit()

    with pytest.raises(LLMError):
        run_debate(db, d, "话题")

    rows = db.query(DraftDiscussion).filter(DraftDiscussion.draft_id == d.id).all()
    run_rows = [r for r in rows if r.kind == "run"]
    assert len(run_rows) == 1
    assert json.loads(run_rows[0].content)["gen"]["label"] == "DeepSeek · deepseek-flash"


# ---------- 接口 ----------


def _client(db):
    from app.api import drafts as drafts_api

    app = FastAPI()
    app.include_router(drafts_api.router, prefix="/api/drafts")

    def override_db():
        yield db

    app.dependency_overrides[get_db] = override_db
    return TestClient(app)


def test_api_returns_model_fields_and_legacy_rows(db):
    d = Draft(title="t", script="s")
    db.add(d)
    db.commit()
    # 老留痕：只有槽位名（历史数据），不该被伪造
    db.add(DraftDiscussion(draft_id=d.id, round=1, actor="model2", kind="critique", content="旧评审"))
    # 新留痕：带实际模型
    db.add(
        DraftDiscussion(
            draft_id=d.id,
            round=2,
            actor="model1",
            kind="revise",
            content="新修订",
            used_slot="model1",
            vendor="deepseek",
            model_id="deepseek-flash",
        )
    )
    db.commit()

    items = _client(db).get(f"/api/drafts/{d.id}/discussions").json()
    legacy = next(i for i in items if i["content"] == "旧评审")
    fresh = next(i for i in items if i["content"] == "新修订")
    assert legacy["model_label"] == ""  # 前端显示「未记录模型（历史）」
    assert legacy["vendor"] == ""
    assert fresh["model_label"] == "DeepSeek · deepseek-flash"
    assert fresh["used_slot"] == "model1"
    assert fresh["model_id"] == "deepseek-flash"
