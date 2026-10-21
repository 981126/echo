"""R-232：功能级模型路由——AI 设置里每个非生成功能选主用槽位（模型1/模型2）。

- 分组见 model_settings.FEATURE_GROUPS（人设 4 引擎合一、提示词优化+评测合一）；
- 默认全 model1（= 放开前现状），prompt_opt 组默认 gen=跟随生成方（R-229 语义）；
- 选中槽位失败自动兜底另一槽位（RoutedLLM 既有降级机制）；
- 脚本生成的生成方/评审方不走这里（debate.py 独立逻辑）。
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

from app.api import settings as settings_api
from app.db import get_db
from app.models.kv import Kv
from app.services import llm_router
from app.services import model_settings as ms


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


def _configure_models(db, *, gen_role: str = "model2", referee_role: str = "model1"):
    _set_kv(db, "model1_vendor", "deepseek")
    _set_kv(db, "model1_model", "deepseek-flash")
    _set_kv(db, "model2_vendor", "kimi")
    _set_kv(db, "model2_model", "kimi-k2.6")
    _set_kv(db, "gen_role", gen_role)
    _set_kv(db, "referee_role", referee_role)


# ---------- 默认值（= 放开前现状） ----------


def test_defaults_all_model1_except_prompt_opt_follows_gen(db):
    _configure_models(db, gen_role="model2")
    assert ms.feature_route(db, "chat") == "model1"
    assert ms.feature_route(db, "video_tags") == "model1"
    assert ms.feature_route(db, "correct") == "model1"
    assert ms.feature_route(db, "diff") == "model1"
    assert ms.feature_route(db, "benchmark") == "model1"
    assert ms.feature_route(db, "feedback_analysis") == "model1"
    assert ms.feature_route(db, "draft_meta") == "model1"
    assert ms.feature_route(db, "misc") == "model1"
    # 人设 4 引擎同组：默认都 model1
    for f in ("persona_init", "persona_merge", "persona_updates", "persona_compare"):
        assert ms.feature_route(db, f) == "model1"
    # 提示词优化/评测默认跟随生成方（R-229 语义）
    assert ms.feature_route(db, "prompt_optimize") == "model2"
    assert ms.feature_route(db, "prompt_eval") == "model2"


def test_prompt_opt_follows_gen_role_changes(db):
    """跟随生成方：对调生成方后优化路由自动跟着换（无需再改路由配置）。"""
    _configure_models(db, gen_role="model1", referee_role="model2")
    assert ms.feature_route(db, "prompt_optimize") == "model1"


def test_unknown_feature_falls_to_misc_group(db):
    assert ms.feature_route(db, "whatever_unknown") == "model1"


# ---------- 保存与校验 ----------


def test_save_and_read_back(db):
    _configure_models(db)
    ms.save_feature_routes(db, {"chat": "model2", "persona": "model2", "prompt_opt": "model1"})
    assert ms.feature_route(db, "chat") == "model2"
    assert ms.feature_route(db, "persona_merge") == "model2"  # 人设组一处改，4 引擎全生效
    assert ms.feature_route(db, "prompt_optimize") == "model1"
    assert ms.feature_route(db, "prompt_eval") == "model1"


def test_save_rejects_unknown_group_and_bad_value(db):
    with pytest.raises(ms.ModelConfigError):
        ms.save_feature_routes(db, {"nope": "model1"})
    with pytest.raises(ms.ModelConfigError):
        ms.save_feature_routes(db, {"chat": "model3"})
    # gen 只允许提示词优化组
    with pytest.raises(ms.ModelConfigError):
        ms.save_feature_routes(db, {"chat": "gen"})


# ---------- 路由真正进入调用链 ----------


def test_primary_llm_resolves_feature_route(db):
    _configure_models(db)
    assert llm_router.primary_llm(db, "chat").primary_slot_name == "model1"
    _set_kv(db, "feature_route_chat", "model2")
    client = llm_router.primary_llm(db, "chat")
    assert client.primary_slot_name == "model2"
    assert client.fallback_slot_name == "model1"  # 失败兜底另一槽位


def test_primary_llm_explicit_primary_overrides_route(db):
    """显式 primary（如生成方）优先于功能路由——R-229 行为不回归。"""
    _configure_models(db)
    client = llm_router.primary_llm(db, "prompt_optimize", primary="model1")
    assert client.primary_slot_name == "model1"


# ---------- API ----------


@pytest.fixture()
def client(tmp_path):
    eng = fresh_engine()
    ensure_schema(eng)
    session = sessionmaker(bind=eng, autoflush=False, autocommit=False)()

    def override_db():
        try:
            yield session
        finally:
            pass

    app = FastAPI()
    app.include_router(settings_api.router, prefix="/api/settings")
    app.dependency_overrides[get_db] = override_db
    with TestClient(app) as c:
        yield c, session
    session.close()


def _valid_payload(**over):
    payload = {
        "model1": {"vendor": "deepseek", "model": "deepseek-flash", "key": "sk-test-1"},
        "model2": {"vendor": "kimi", "model": "kimi-k2.6", "key": "sk-test-2"},
        "gen_role": "model2",
        "referee_role": "model1",
        "asr_mode": "mock",
        "debate_rounds": 3,
        "topics_count": 2,
    }
    payload.update(over)
    return payload


def test_api_feature_routes_get_put_round_trip(client):
    c, session = client
    c.put("/api/settings/models", json=_valid_payload())

    got = c.get("/api/settings/models")
    routes = got.json()["feature_routes"]
    # 10 个功能组全在，默认值正确
    assert set(routes) == set(ms.FEATURE_GROUPS)
    assert routes["chat"]["value"] == "model1"
    assert routes["prompt_opt"]["value"] == "gen"
    assert routes["prompt_opt"]["resolved"] == "模型2（Kimi（月之暗面） · kimi-k2.6）"
    # 选项内嵌槽位实际模型名（作者要「看清楚用的什么模型」）
    labels = [o["label"] for o in routes["chat"]["options"]]
    assert any("deepseek-flash" in x for x in labels)
    assert any("kimi-k2.6" in x for x in labels)
    # 提示词优化组多一个「跟随生成方」
    assert any(o["v"] == "gen" for o in routes["prompt_opt"]["options"])

    saved = c.put("/api/settings/models", json=_valid_payload(feature_routes={"chat": "model2"}))
    assert saved.status_code == 200, saved.text
    assert saved.json()["feature_routes"]["chat"]["value"] == "model2"

    # 立即生效：路由解析读到新值
    assert ms.feature_route(session, "chat") == "model2"


def test_api_feature_routes_invalid_returns_400(client):
    c, _session = client
    res = c.put("/api/settings/models", json=_valid_payload(feature_routes={"chat": "model3"}))
    assert res.status_code == 400
    assert "chat" in res.json()["detail"] or "AI 对话" in res.json()["detail"]
