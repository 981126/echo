"""R-229：生成方换强模型 + 提示词优化路由跟随生成方槽位。

背景：原配置生成方 = deepseek-flash（弱模型写字）、评审方 = kimi-k2.6（强模型只挑刺），
成稿上限被生成方锁死；提示词优化也固定走模型1（弱模型自调，v3~v10 候选越调越歪）。
本需求：
1. `llm_router.primary_llm` 支持指定主用槽位（primary=生成方槽位），主用非模型1 时
   自动以另一槽位兜底；
2. `prompt_service._optimize_llm` 主用生成方槽位；
3. 交付时主库 app_kv 对调 gen_role/referee_role（生成 = kimi-k2.6）。
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import Base
from app.models.kv import Kv
from app.services import llm_router
from app.services.prompt_service import _optimize_llm


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


def _configure_models(db, *, gen_role: str, referee_role: str):
    _set_kv(db, "model1_vendor", "deepseek")
    _set_kv(db, "model1_model", "deepseek-flash")
    _set_kv(db, "model2_vendor", "kimi")
    _set_kv(db, "model2_model", "kimi-k2.6")
    _set_kv(db, "gen_role", gen_role)
    _set_kv(db, "referee_role", referee_role)


def test_primary_llm_default_still_model1(db):
    """不传 primary 时保持原行为：模型1 主用、模型2 兜底。"""
    _configure_models(db, gen_role="model1", referee_role="model2")
    client = llm_router.primary_llm(db, "prompt_optimize")
    assert client.primary_slot_name == "model1"
    assert client.fallback_slot_name == "model2"


def test_primary_llm_explicit_primary_switches_fallback(db):
    """R-229：主用指定为 model2 时，兜底自动换成 model1（否则降级无意义）。"""
    _configure_models(db, gen_role="model2", referee_role="model1")
    client = llm_router.primary_llm(db, "prompt_optimize", primary="model2")
    assert client.primary_slot_name == "model2"
    assert client.fallback_slot_name == "model1"
    assert "kimi-k2.6" in client.routing()["primary"]


def test_optimize_llm_follows_generation_slot(db):
    """提示词优化主用生成方槽位：生成方 = model2 时优化也用 model2。"""
    _configure_models(db, gen_role="model2", referee_role="model1")
    client, used_model = _optimize_llm(db)
    assert client.primary_slot_name == "model2"
    assert used_model == "kimi-k2.6"


def test_optimize_llm_keeps_model1_when_gen_is_model1(db):
    """生成方仍是模型1 的旧配置下行为不变。"""
    _configure_models(db, gen_role="model1", referee_role="model2")
    client, used_model = _optimize_llm(db)
    assert client.primary_slot_name == "model1"
    assert used_model == "deepseek-flash"


def test_generation_pair_reflects_swapped_roles(db):
    """R-229 交付口径：对调后生成链路（生成方初稿 + 每轮修订）用 model2/kimi-k2.6。"""
    _configure_models(db, gen_role="model2", referee_role="model1")
    route = llm_router.snapshot(db)
    gen_slot, critic_slot = route.generation_pair()
    assert gen_slot["slot"] == "model2"
    assert gen_slot["model"] == "kimi-k2.6"
    assert critic_slot["slot"] == "model1"
