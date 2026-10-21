"""R-138：模型槽位配置（模型1/2、生成方/评审方、ASR、轮次、每日篇数）测试。"""

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


def _valid_payload(**over):
    payload = {
        "model1": {"vendor": "deepseek", "model": "deepseek-flash", "key": "sk-test-1"},
        "model2": {"vendor": "kimi", "model": "kimi-k2.6", "key": "sk-test-2"},
        "gen_role": "model2",
        "referee_role": "model1",
        "asr_mode": "siliconflow",
        "asr_model": "Qwen/Qwen3-ASR-1.7B",
        "debate_rounds": 3,
        "topics_count": 2,
    }
    payload.update(over)
    return payload


# ---------- 默认与旧值迁移 ----------


def test_defaults_and_legacy_migration(db, monkeypatch):
    # 无任何 Kv 时：模型1=DeepSeek、模型2=Kimi（对应现状主力/降级）
    cfg = ms.get_model_config(db)
    assert cfg["model1"]["vendor"] == "deepseek" and cfg["model1"]["model"] == "deepseek-flash"
    assert cfg["model2"]["vendor"] == "kimi"

    # 旧 generation_model=kimi → 生成方应为 Kimi 所在槽位（model2）
    _set_kv(db, "generation_model", "kimi")
    cfg = ms.get_model_config(db)
    assert cfg["gen_role"] == "model2" and cfg["referee_role"] == "model1"

    # 旧 generation_model=deepseek → 生成方为 model1
    _set_kv(db, "generation_model", "deepseek")
    cfg = ms.get_model_config(db)
    assert cfg["gen_role"] == "model1" and cfg["referee_role"] == "model2"


# ---------- 保存与校验 ----------


def test_save_round_trip_and_resolve(db):
    saved = ms.save_model_config(db, _valid_payload())
    assert saved["model1"]["key"] == "sk-test-1"
    assert saved["gen_role"] == "model2" and saved["referee_role"] == "model1"
    assert saved["asr_mode"] == "siliconflow"

    slots = ms.resolve_slots(db)
    assert slots["model1"]["vendor"] == "deepseek" and slots["model1"]["api_key"] == "sk-test-1"
    assert slots["model2"]["model"] == "kimi-k2.6"
    assert slots["model2"]["supports_temperature"] is False  # 推理模型不吃 temperature
    assert slots["model2"]["min_max_tokens"] >= 2000  # 防"推理吃光 token → 空正文"
    assert slots["model1"]["base_url"].startswith("https://api.deepseek.com")


def test_reject_missing_key_without_env(db):
    payload = _valid_payload()
    payload["model1"]["key"] = ""
    with pytest.raises(ms.ModelConfigError) as exc:
        ms.save_model_config(db, payload)
    assert "API Key" in str(exc.value)


def test_reject_bad_vendor_role_and_asr(db):
    with pytest.raises(ms.ModelConfigError):
        ms.save_model_config(db, _valid_payload(model1={"vendor": "openai", "key": "k"}))
    with pytest.raises(ms.ModelConfigError):
        ms.save_model_config(db, _valid_payload(gen_role="model3"))
    with pytest.raises(ms.ModelConfigError):
        ms.save_model_config(db, _valid_payload(asr_mode="whisper"))
    with pytest.raises(ms.ModelConfigError):
        ms.save_model_config(db, _valid_payload(asr_mode="siliconflow", asr_model=""))


def test_asr_and_topics_runtime_override(db):
    ms.save_model_config(db, _valid_payload(asr_mode="mock"))
    assert ms.asr_config(db)["mode"] == "mock"

    assert ms.topics_count(db) >= 1  # 未在界面配置时回退 .env 的 ECHO_PIPELINE_TOPICS_COUNT
    assert ms.save_topics_count(db, 99) == 10  # 上限收敛
    assert ms.save_topics_count(db, 0) == 1
    assert ms.topics_count(db) == 1


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


def test_api_models_get_put(client):
    c, session = client
    got = c.get("/api/settings/models")
    assert got.status_code == 200
    body = got.json()
    assert body["model1"]["vendor"] == "deepseek" and "vendors" in body and body["warnings"]

    saved = c.put("/api/settings/models", json=_valid_payload(gen_role="model1", referee_role="model1"))
    assert saved.status_code == 200, saved.text
    body = saved.json()
    assert body["gen_role"] == "model1" and body["referee_role"] == "model1"  # 可以选同一个
    assert body["debate_rounds"] == 3 and body["topics_count"] == 2
    # 立即生效：ASR 接口同步变化
    assert c.get("/api/settings/asr").json()["mode"] == "siliconflow"


def test_api_models_put_invalid_returns_400(client):
    c, session = client
    bad = _valid_payload(model2={"vendor": "kimi", "model": "kimi-k2.6", "key": ""})  # 空 Key + .env 无 Key
    res = c.put("/api/settings/models", json=bad)
    assert res.status_code == 400 and "API Key" in res.json()["detail"]
