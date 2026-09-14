"""R-157：版本回滚（纯覆盖）+ 洗稿两版 + AI 生成自动留版 + 首版不触发差异分析。"""

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
from app.models.draft import Draft
from app.models.kv import Kv
from app.models.platform import Creator
from app.services import llm_router
from app.services.draft_versions import list_versions, snapshot_version


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


def _client(db):
    from app.api import drafts as drafts_api

    app = FastAPI()
    app.include_router(drafts_api.router, prefix="/api/drafts")

    def override_db():
        yield db

    app.dependency_overrides[get_db] = override_db
    return TestClient(app)


# ---------- 回滚：纯覆盖、不额外留痕 ----------


def test_rollback_overwrites_draft_without_new_version(db):
    d = Draft(title="旧标题", script="v1正文", tags=json.dumps(["a"], ensure_ascii=False))
    db.add(d)
    db.commit()
    v1 = snapshot_version(db, d, note="第一版")
    d.title = "新标题"
    d.script = "v2正文"
    db.commit()
    snapshot_version(db, d, note="第二版")

    r = _client(db).post(f"/api/drafts/{d.id}/versions/{v1.id}/rollback")
    assert r.status_code == 200, r.text
    assert r.json()["rolled_back_to"] == v1.id
    got = db.get(Draft, d.id)
    assert (got.title, got.script) == ("旧标题", "v1正文")
    assert json.loads(got.tags) == ["a"]
    assert len(list_versions(db, d.id)) == 2, "回滚不额外留痕"


def test_rollback_404_for_missing_or_foreign_version(db):
    d = Draft(title="t", script="s")
    other = Draft(title="o", script="s2")
    db.add_all([d, other])
    db.commit()
    foreign = snapshot_version(db, other, note="别人的版本")
    c = _client(db)
    assert c.post(f"/api/drafts/{d.id}/versions/999/rollback").status_code == 404
    assert c.post(f"/api/drafts/{d.id}/versions/{foreign.id}/rollback").status_code == 404


# ---------- 洗稿：洗稿前 ASR 第一版 + 洗稿后第二版 ----------


def test_rewrite_creates_before_and_after_versions(db, monkeypatch):
    from app.services.debate import run_rewrite_debate

    owner = _owner(db)
    _configure_models(db)
    monkeypatch.setattr("app.tasks.start_task", lambda *a, **k: 1)  # 不真的入队分析

    class _FakeClient:
        def __init__(self, slot):
            self.vendor = slot["vendor"]

        def chat_json(self, *_a, **_k):
            return {"title": "洗稿后标题", "cover_text": "封面字", "script": "洗稿后正文"}

        def chat(self, *_a, **_k):
            return "评审或修订正文"

    monkeypatch.setattr(llm_router, "build_client", lambda slot: _FakeClient(slot))

    res = run_rewrite_debate(
        db,
        {"owner_id": owner.id, "title": "素材标题", "text": "素材ASR原文内容", "benchmark_name": "对标A", "tags": ["求职"]},
    )
    vs = list_versions(db, res["draft_id"])
    assert [v.note for v in vs] == ["洗稿前（素材 ASR）", "洗稿后"]
    assert vs[0].script == "素材ASR原文内容"
    assert vs[1].script == "评审或修订正文"
    assert all(v.source == "ai_rewrite" for v in vs)


# ---------- AI 生成自动留版（snapshot 开关） ----------


def test_generate_draft_snapshots_by_default(db, monkeypatch):
    from app.services.generation import generate_draft

    _owner(db)
    monkeypatch.setattr("app.tasks.start_task", lambda *a, **k: 1)

    def fake_run(db_, draft, topic, *a, **k):
        draft.title = f"{topic}标题"
        draft.script = f"{topic}正文"
        db_.commit()
        return {"draft_id": draft.id}

    monkeypatch.setattr("app.services.debate.run_debate", fake_run)

    d1 = generate_draft(db, "话题A")
    assert [v.source for v in list_versions(db, d1.id)] == ["ai_generate"]
    d2 = generate_draft(db, "话题B", snapshot=False)  # 金样本自测/回炉中间稿
    assert list_versions(db, d2.id) == []


# ---------- 首版不触发差异分析 ----------


def test_maybe_start_diff_analysis_only_from_second_version(db, monkeypatch):
    from app.services.diff_analysis import maybe_start_diff_analysis

    kinds: list[str] = []
    monkeypatch.setattr("app.tasks.start_task", lambda kind, payload, fn: kinds.append(kind) or 1)
    d = Draft(title="t", script="v1")
    db.add(d)
    db.commit()
    snapshot_version(db, d, note="第一版")
    assert maybe_start_diff_analysis(db, d) is False
    assert kinds == []

    d.script = "v2"
    db.commit()
    snapshot_version(db, d, note="第二版")
    assert maybe_start_diff_analysis(db, d) is True
    assert kinds == ["diff_analysis"]
