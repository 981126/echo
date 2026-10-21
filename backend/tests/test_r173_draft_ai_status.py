"""R-173：草稿 AI 长任务状态（讨论/洗稿/回炉/生成）——状态存取、列表字段、结束判定、中断标记。"""

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
from app.models.kv import Kv
from app.models.platform import Creator
from app.services import draft_status, llm_router


@pytest.fixture()
def db(tmp_path):
    eng = fresh_engine()
    ensure_schema(eng)
    session = sessionmaker(bind=eng, autoflush=False, autocommit=False)()
    yield session
    session.close()


def _client(db):
    from app.api import drafts as drafts_api

    app = FastAPI()
    app.include_router(drafts_api.router, prefix="/api/drafts")

    def override_db():
        yield db

    app.dependency_overrides[get_db] = override_db
    return TestClient(app)


def _owner(db):
    c = Creator(kind="owner", name="我", is_current=True)
    db.add(c)
    db.commit()
    return c


def _draft(db, title="测试草稿", script="正文", status="draft"):
    owner = db.query(Creator).filter(Creator.kind == "owner").first()
    d = Draft(
        title=title,
        script=script,
        cover_text="",
        source="manual",
        status=status,
        creator_id=owner.id if owner else None,
    )
    db.add(d)
    db.commit()
    db.refresh(d)
    return d


def _set_kv(db, key, value):
    row = db.get(Kv, key)
    if row is None:
        db.add(Kv(key=key, value=str(value)))
    else:
        row.value = str(value)
    db.commit()


# ---------- 状态存取 ----------

def test_set_running_roundtrip(db):
    draft_status.set_running(
        db, 7, "MODEL1 正在评审第 2/3 轮…", kind="rewrite", actor="model1", phase="critique", round_no=2, rounds=3
    )
    st = draft_status.read(db, 7)
    assert st is not None
    assert st["state"] == "running"
    assert st["kind"] == "rewrite"
    assert st["actor"] == "model1"
    assert st["phase"] == "critique"
    assert st["round"] == 2 and st["rounds"] == 3
    assert st["note"] == "MODEL1 正在评审第 2/3 轮…"
    assert st["running"] is True


def test_failed_is_not_running(db):
    draft_status.set_failed(db, 8, "洗稿中断：timeout", kind="rewrite")
    st = draft_status.read(db, 8)
    assert st is not None and st["state"] == "failed"
    assert st["running"] is False  # 前端据此不画动画、只显示「上次讨论中断」


def test_clear_removes_state(db):
    draft_status.set_running(db, 9, "在跑")
    draft_status.clear(db, 9)
    assert draft_status.read(db, 9) is None


def test_read_many_prefers_new_key_and_keeps_legacy_compat(db):
    d1, d2, d3 = _draft(db, "一"), _draft(db, "二"), _draft(db, "三")
    draft_status.set_running(db, d1.id, "新键在跑")
    # R-173 之前的旧键：纯文案，应被兼容成 running
    _set_kv(db, f"debate:{d2.id}", "MODEL2 正在评审第 1/1 轮…")
    # 新旧键同时存在时，新键优先
    draft_status.set_running(db, d3.id, "新键优先")
    _set_kv(db, f"debate:{d3.id}", "旧键落后")
    states = draft_status.read_many(db, [d1.id, d2.id, d3.id])
    assert states[d1.id]["note"] == "新键在跑"
    assert states[d2.id]["state"] == "running" and states[d2.id]["note"].startswith("MODEL2")
    assert states[d3.id]["note"] == "新键优先"
    assert draft_status.read_many(db, []) == {}


def test_reset_stale_on_startup(db):
    d1, d2 = _draft(db, "一"), _draft(db, "二")
    draft_status.set_running(db, d1.id, "在跑")
    draft_status.set_failed(db, d2.id, "已失败")
    _set_kv(db, "debate:99", "旧键残留")
    n = draft_status.reset_stale_on_startup(db)
    assert n == 1
    st = draft_status.read(db, d1.id)
    assert st["state"] == "failed" and st["note"] == "服务重启，任务中断"
    assert draft_status.read(db, d2.id)["state"] == "failed"
    assert db.get(Kv, "debate:99") is None  # 旧键清理
    assert db.get(Kv, "debate_rounds") is None  # 不误伤讨论轮次键


# ---------- 接口契约 ----------

def test_list_drafts_carries_debate_state(db):
    _owner(db)
    d1, d2 = _draft(db, "在跑"), _draft(db, "空闲")
    draft_status.set_running(db, d1.id, "MODEL1 正在修订第 1/3 轮…", kind="rewrite", round_no=1, rounds=3)
    rows = _client(db).get("/api/drafts?limit=500").json()
    by_id = {r["id"]: r for r in rows}
    assert by_id[d1.id]["debate"]["state"] == "running"
    assert by_id[d1.id]["debate"]["round"] == 1
    assert by_id[d2.id]["debate"] is None


def test_debate_status_endpoint_shape(db):
    draft = _draft(db)
    client = _client(db)
    idle = client.get(f"/api/drafts/{draft.id}/debate-status").json()
    assert idle == {
        "status": None,
        "state": None,
        "kind": "",
        "note": "",
        "actor": "",
        "phase": "",
        "round": None,
        "rounds": None,
    }
    draft_status.set_running(db, draft.id, "MODEL2 正在评审第 2/3 轮…", kind="debate", actor="model2", phase="critique", round_no=2, rounds=3)
    row = client.get(f"/api/drafts/{draft.id}/debate-status").json()
    assert row["state"] == "running"
    assert row["status"] == "MODEL2 正在评审第 2/3 轮…"  # 老前端只读 status（语义不变）
    assert row["actor"] == "model2" and row["round"] == 2 and row["rounds"] == 3
    draft_status.set_failed(db, draft.id, "讨论中断：boom", kind="debate")
    failed = client.get(f"/api/drafts/{draft.id}/debate-status").json()
    assert failed["state"] == "failed" and "boom" in failed["note"]


# ---------- 讨论中途失败要留标记（不是静默「只讨论了一轮」） ----------

class _FakeLLM:
    def __init__(self, slot, fail_chat_on=()):
        self.slot = slot
        self.degraded = False
        self.fail_chat_on = set(fail_chat_on)
        self.chat_calls = 0

    def routing(self):
        return {"used": self.slot}

    def chat_json(self, messages, **kwargs):  # noqa: ANN001
        return {"title": "新标题", "cover_text": "封面字", "script": f"{self.slot} 的初稿", "tags": ["求职"]}

    def chat(self, messages, **kwargs):  # noqa: ANN001
        self.chat_calls += 1
        if self.chat_calls in self.fail_chat_on:
            from app.services.llm import LLMError

            raise LLMError("boom")
        return f"{self.slot} 第 {self.chat_calls} 次输出"


class _FakeRoute:
    def generation_pair(self):
        return (
            {"slot": "model1", "vendor": "deepseek", "model": "deepseek-flash"},
            {"slot": "model2", "vendor": "kimi", "model": "kimi-k2.6"},
        )


def _run_debate(db, draft, critic_fail_on=()):
    from app.services import debate

    gen = _FakeLLM("model1")
    critic = _FakeLLM("model2", fail_chat_on=critic_fail_on)
    original = debate._side_llm
    debate._side_llm = lambda route, slot, feature="generation": gen if slot == "model1" else critic  # type: ignore[assignment]
    original_snapshot = llm_router.snapshot
    llm_router.snapshot = lambda _db: _FakeRoute()  # type: ignore[assignment]
    try:
        return debate.run_debate(db, draft, "测试选题")
    finally:
        debate._side_llm = original  # type: ignore[assignment]
        llm_router.snapshot = original_snapshot  # type: ignore[assignment]


def test_debate_success_clears_status(db):
    draft = _draft(db)
    _set_kv(db, "debate_rounds", 2)
    res = _run_debate(db, draft)
    assert res["rounds"] == 2
    assert draft_status.read(db, draft.id) is None  # 跑满 → 状态清空（前端判定「讨论完成」）


def test_debate_midway_failure_marks_interrupted(db):
    draft = _draft(db)
    _set_kv(db, "debate_rounds", 2)
    # 评审方每次 chat = 一轮评审：让它第 2 轮评审失败（第 1 轮应已完成）
    _run_debate(db, draft, critic_fail_on=(2,))
    st = draft_status.read(db, draft.id)
    assert st is not None and st["state"] == "failed"
    assert "第 2/2 轮评审失败" in st["note"]
    quality = json.loads(draft.quality)
    assert quality["rounds"] == 2 and quality["rounds_done"] == 1
    # 留痕里有说明，作者能看到「为什么只有 1 轮」
    from app.models.discussion import DraftDiscussion

    notes = [r.content for r in db.query(DraftDiscussion).filter(DraftDiscussion.draft_id == draft.id)]
    assert any("以当前稿定稿" in n for n in notes)
