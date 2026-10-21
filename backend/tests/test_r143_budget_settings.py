"""R-143：各功能 LLM 预算可配置（AI 设置内，保存即生效）。

覆盖：默认值 / 保存回读 / 生效值不低于厂家下限 / 非法输入拒绝 / 恢复默认 /
调用点确实用了配置（不是只改了个数字没人读）。
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest
from conftest import ensure_schema, fresh_engine
from sqlalchemy.orm import sessionmaker

from app.models.kv import Kv
from app.models.prompt import AiPrompt
from app.services import budget_settings
from app.services import debate as debate_mod
from app.services import llm_router, model_settings
from app.services import prompt_service as ps


@pytest.fixture()
def db(tmp_path):
    eng = fresh_engine()
    ensure_schema(eng)
    session = sessionmaker(bind=eng, autoflush=False, autocommit=False)()
    for key in ps.PROMPT_META:
        session.add(AiPrompt(key=key, version=1, content=ps.default_content(key), status="enabled", note="t"))
    session.commit()
    yield session
    session.close()


# ---------- 默认值 / 读写 ----------


def test_defaults_when_nothing_configured(db):
    m = budget_settings.budget_map(db)
    assert set(m) == set(budget_settings.SLOTS)
    for key, slot in budget_settings.SLOTS.items():
        assert m[key]["requested"] == slot["default"]
        assert m[key]["value"] == max(int(slot["default"]), budget_settings.floor())
        assert m[key]["custom"] is False


def test_save_and_read_back(db):
    out = budget_settings.save_budgets(db, {"debate_critique": 20000, "chat": 9000})
    assert out["debate_critique"]["requested"] == 20000
    assert out["debate_critique"]["value"] == 20000
    assert out["debate_critique"]["custom"] is True
    assert budget_settings.budget_for(db, "debate_critique") == 20000
    assert budget_settings.budget_for(db, "chat") == 9000
    # 未改的项保持默认
    assert budget_settings.budget_for(db, "debate_revise") == int(
        budget_settings.SLOTS["debate_revise"]["default"]
    )


def test_effective_value_never_below_vendor_floor(db):
    """设到下限以下会被抬到下限（下限是防「思考吃光正文」的护栏），界面显示真实生效值。"""
    out = budget_settings.save_budgets(db, {"debate_critique": 500})
    assert out["debate_critique"]["requested"] == 500
    assert out["debate_critique"]["value"] == budget_settings.floor()
    assert budget_settings.budget_for(db, "debate_critique") == budget_settings.floor()
    assert budget_settings.floor() == min(
        meta["min_max_tokens"] for meta in model_settings.VENDORS.values()
    )


def test_reset_budgets(db):
    budget_settings.save_budgets(db, {"chat": 9000})
    assert budget_settings.budget_for(db, "chat") == 9000
    out = budget_settings.reset_budgets(db)
    assert all(not v["custom"] for v in out.values())
    assert budget_settings.budget_for(db, "chat") == int(budget_settings.SLOTS["chat"]["default"])


def test_without_session_opens_its_own(db):
    """线程池/无 db 的调用点（人设提炼）也能读到配置，不炸。"""
    assert budget_settings.budget_for(None, "persona_merge") >= budget_settings.floor()


# ---------- 非法输入 ----------


def test_unknown_key_rejected(db):
    with pytest.raises(budget_settings.BudgetConfigError, match="未知的预算项"):
        budget_settings.save_budgets(db, {"not_a_slot": 9000})


def test_non_integer_rejected(db):
    with pytest.raises(budget_settings.BudgetConfigError, match="必须是整数"):
        budget_settings.save_budgets(db, {"chat": "很多"})


def test_out_of_range_rejected(db):
    with pytest.raises(budget_settings.BudgetConfigError, match="需在"):
        budget_settings.save_budgets(db, {"chat": 10})
    with pytest.raises(budget_settings.BudgetConfigError, match="需在"):
        budget_settings.save_budgets(db, {"chat": budget_settings.ceiling() + 1})


def test_corrupt_kv_falls_back_to_defaults(db):
    db.add(Kv(key=budget_settings.KV_KEY, value="{不是 JSON"))
    db.commit()
    assert budget_settings.budget_for(db, "chat") == int(budget_settings.SLOTS["chat"]["default"])


# ---------- 调用点确实读配置 ----------


class _RecordingClient:
    def __init__(self, slot, seen):
        self.slot = slot
        self._seen = seen

    def chat(self, *_a, **kw):
        self._seen.append(kw.get("max_tokens"))
        return "评审或修订正文"

    def chat_json(self, *_a, **kw):
        self._seen.append(kw.get("max_tokens"))
        return {"title": "t", "cover_text": "c", "script": "正文够长了吧", "shells": {}}


def test_run_debate_uses_configured_budgets(db, monkeypatch):
    """脚本生成各步都读「AI 设置」里的预算（改配置 → 调用参数跟着变）。"""
    from app.models.draft import Draft
    from app.models.platform import Creator

    db.add(Creator(kind="owner", name="我", is_current=True))
    db.add(Kv(key="debate_rounds", value="1"))
    db.commit()
    budget_settings.save_budgets(db, {"debate_initial": 13000, "debate_critique": 15000, "debate_revise": 17000})

    seen: list[int] = []
    monkeypatch.setattr(llm_router, "build_client", lambda slot: _RecordingClient(slot["slot"], seen))

    draft = Draft(title="选题", script="（占位）", source="ai")
    db.add(draft)
    db.commit()
    debate_mod.run_debate(db, draft, "选题")

    # 1 次初稿(13000) + 1 轮评审(15000) + 1 次修订(17000)，若自检触发收口再加一次 17000
    assert seen[0] == 13000
    assert 15000 in seen
    assert seen.count(17000) >= 1
    assert set(seen) <= {13000, 15000, 17000}

# 校准护栏（长输出功能的默认预算必须覆盖实测最坏值）在 tests/test_r142_thinking_budget.py，避免两处维护
