"""R-228：双模型讨论禁止替作者编造经历（**R-254 已放开该规则，本文件只保留证据可见性回归**）。

留痕根因（draft 128）：评审方在"修改建议"里发明第一人称素材（公司倒闭欠薪、投递转化
数字、简历造假操作），生成方照填——终稿全是作者没说过的话。R-228 当时加了两条：
1. 评审/修订 system prompt 都带事实硬规则（NO_FABRICATION_RULE）；
2. 联网证据 + 站内素材从"仅初稿注入"改为每轮 critique/revise 都可见。

R-254 按作者确认放开了第 1 条（反编造硬规则，见 `test_r254_reference_as_own.py`），
但第 2 条仍然保留：本文件只回归「证据块每轮评审/修订都可见」。
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest
from conftest import ensure_schema, fresh_engine
from sqlalchemy.orm import sessionmaker

from app.models.draft import Draft
from app.models.kv import Kv
from app.services import evidence, llm_router, station_evidence
from app.services.debate import run_debate


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


def _configure_models(db):
    _set_kv(db, "model1_vendor", "deepseek")
    _set_kv(db, "model1_model", "deepseek-flash")
    _set_kv(db, "model2_vendor", "kimi")
    _set_kv(db, "model2_model", "kimi-k2.6")
    _set_kv(db, "gen_role", "model1")
    _set_kv(db, "referee_role", "model2")
    _set_kv(db, "debate_rounds", "2")


EVIDENCE_BLOCK = "【联网事实素材】\n[1] 某大厂 2025 年裁员 15%（R-228 测试标记 EVIDENCE_MARK）"
STATION = {"author": [], "benchmark": [], "block": ""}


def _fake_env(monkeypatch, calls: list):
    """假 LLM（记录每次调用的 messages）+ 假证据/站内检索。"""

    class _FakeClient:
        def __init__(self, slot):
            self.vendor = slot["vendor"]

        def chat_json(self, messages, **_k):
            calls.append(("chat_json", messages))
            return {
                "title": "标题",
                "cover_text": "封面",
                "script": "初稿正文。",
                "outlines": [{"claim": "论点一", "support": "支撑"}],
                "sources": [1],
                "shells": {},
            }

        def chat(self, messages, **_k):
            calls.append(("chat", messages))
            return "修订后的正文。"

    monkeypatch.setattr(llm_router, "build_client", lambda slot: _FakeClient(slot))
    monkeypatch.setattr(
        evidence,
        "gather_online",
        lambda *a, **k: {
            "block": EVIDENCE_BLOCK,
            "queries": ["q"],
            "sources": [{"title": "t", "url": "u", "summary": "s", "site": "x"}],
        },
    )
    monkeypatch.setattr(station_evidence, "retrieve_station", lambda *a, **k: dict(STATION))


def _round_calls(calls: list) -> list:
    kind, messages = calls[0]
    assert kind == "chat_json"  # 首次调用一定是初稿
    return [messages for kind, messages in calls[1:] if kind == "chat"]


def test_normal_debate_evidence_in_every_round(db, monkeypatch):
    _configure_models(db)
    draft = Draft(title="选题", script="（双模型讨论生成中…）", source="ai")
    db.add(draft)
    db.commit()
    calls: list = []
    _fake_env(monkeypatch, calls)

    run_debate(db, draft, "选题")

    rounds = _round_calls(calls)
    assert len(rounds) == 4  # 2 轮 ×（评审 + 修订）
    for messages in rounds:
        system = messages[0]["content"]
        assert "EVIDENCE_MARK" in system  # 证据块每轮可见（此前仅初稿注入）
        assert "参考/扩写的素材" in system  # R-254：证据块标签改为可参考/可扩写


def test_source_debate_evidence_in_every_round(db, monkeypatch):
    """基于原文讨论：评审/修订同样每轮都能看到证据块。"""
    _configure_models(db)
    draft = Draft(title="选题", script="（双模型讨论生成中…）", source="ai")
    db.add(draft)
    db.commit()
    calls: list = []
    _fake_env(monkeypatch, calls)

    run_debate(db, draft, "选题", source_text="素材原文正文，其中的经历可以写成作者本人的。")

    rounds = _round_calls(calls)
    assert len(rounds) == 4
    for messages in rounds:
        system = messages[0]["content"]
        assert "EVIDENCE_MARK" in system
        assert "参考/扩写的素材" in system
