"""R-255：全部 AI 提示词统一入库（ai_prompt_defs 注册表 + 运行时读表 + 幂等补种）。

覆盖：
1. 注册表完整性：45 行 = 34 条系统提示词/探针 + 11 条程序固定契约；每条有中文名/模块/用途/代码位置/默认正文；
2. 运行时读表优先级：ai_prompts enabled → ai_prompt_defs.default_content → 代码默认；
3. 启动补种幂等：缺登记补登记、缺启用版本补 v1、已有作者版本绝不覆盖；
4. 契约只读：editable/optimizable=false，镜像与 prompt_contract 一致；
5. video_review 一次性升级（旧 54 字种子 → 完整版；已手改则不动）；
6. 接口：/keys 返回全部元数据；契约不可保存/启用；未开放优化返回 400；新 key 保存生效；
7. 读表生效：新增 chat_create_mode 的正文改库后被真实拼进对话 system。
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest
from conftest import ensure_schema, fresh_engine
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from app.api import prompts as prompts_api
from app.db import get_db
from app.models.kv import Kv
from app.models.prompt import AiPrompt, AiPromptDef
from app.services import chat_service, prompt_catalog, prompt_contract, prompt_service


@pytest.fixture()
def db(tmp_path):
    eng = fresh_engine()
    ensure_schema(eng)
    session = sessionmaker(bind=eng, autoflush=False, autocommit=False)()
    yield session
    session.close()


@pytest.fixture()
def api_client(db):
    app = FastAPI()
    app.include_router(prompts_api.router, prefix="/api/prompts")
    app.dependency_overrides[get_db] = lambda: db
    return TestClient(app)


def _seed(db) -> dict[str, int]:
    return prompt_service.ensure_prompt_catalog(db)


def _enabled(db, key):
    return (
        db.query(AiPrompt)
        .filter(AiPrompt.key == key, AiPrompt.status == "enabled")
        .order_by(AiPrompt.version.desc())
        .first()
    )


# ---------- 1. 注册表完整性 ----------


def test_registry_complete() -> None:
    specs = prompt_catalog.PROMPT_SPECS
    assert len(specs) == 45
    assert len({s.key for s in specs}) == 45
    by_category = {c: sum(1 for s in specs if s.category == c) for c in ("system", "probe", "contract")}
    assert by_category == {"system": 32, "probe": 2, "contract": 11}
    module_names = {name for name, _label in prompt_catalog.MODULES}
    for spec in specs:
        assert spec.title, spec.key
        assert spec.module in module_names, spec.key
        assert spec.module_label and spec.module_label == prompt_catalog.MODULE_LABELS[spec.module]
        assert spec.purpose and re.search(r"[\u4e00-\u9fff]", spec.purpose), spec.key
        assert spec.entry and spec.code_ref, spec.key
    assert len({s.sort_order for s in specs}) == 45


def test_registry_default_content_all_available() -> None:
    """每条提示词（含契约镜像）都能取到非空代码默认正文。"""
    for spec in prompt_catalog.PROMPT_SPECS:
        content = prompt_catalog.default_content(spec.key)
        assert content.strip(), f"缺少默认正文：{spec.key}"
        if spec.category == "contract":
            base = spec.key[: -len(".contract")]
            assert content == prompt_contract.CONTRACTS[base]


def test_contracts_cover_video_review() -> None:
    """R-255 顺带把视频复盘两条内嵌契约抽进 prompt_contract（只读镜像来源）。"""
    assert "video_review" in prompt_contract.CONTRACTS
    assert "video_review_advice" in prompt_contract.CONTRACTS


def test_only_existing_ten_optimizable() -> None:
    assert prompt_catalog.OPTIMIZABLE_KEYS == {
        "generation",
        "persona_init",
        "persona_merge",
        "persona_updates",
        "persona_compare",
        "video_tags",
        "correct",
        "diff",
        "chat",
        "video_review",
    }
    for spec in prompt_catalog.PROMPT_SPECS:
        if spec.category in ("contract", "probe"):
            assert spec.editable is False, spec.key
            assert spec.optimizable is False, spec.key


def test_prompt_meta_backwards_compatible() -> None:
    """旧 migration（7a6f…）与测试仍用 PROMPT_META：34 条系统提示词/探针都要在。"""
    assert len(prompt_service.PROMPT_META) == 34
    for key in prompt_service.PROMPT_META:
        assert prompt_service.default_content(key).strip(), key


# ---------- 2. 运行时读表优先级 ----------


def test_get_prompt_prefers_enabled_version(db) -> None:
    db.add(AiPrompt(key="rewrite_critic", version=1, content="库内启用版", status="enabled", note="t"))
    db.commit()
    assert prompt_service.get_prompt("rewrite_critic", db) == "库内启用版"


def test_get_prompt_falls_back_to_defs_default(db) -> None:
    _seed(db)
    db.query(AiPrompt).filter(AiPrompt.key == "rewrite_critic").delete()
    db.commit()
    assert prompt_service.get_prompt("rewrite_critic", db) == prompt_catalog.default_content("rewrite_critic")


def test_get_prompt_falls_back_to_code_when_defs_missing(db) -> None:
    """注册表未初始化（如旧库尚未补种）时回退代码常量，行为与升级前一致。"""
    assert db.query(AiPromptDef).count() == 0
    assert prompt_service.get_prompt("ideas_match", db) == prompt_catalog.default_content("ideas_match")


# ---------- 3. 启动补种幂等 ----------


def test_ensure_catalog_idempotent(db) -> None:
    first = _seed(db)
    assert first["registered"] == 45
    assert first["seeded"] == 34
    second = _seed(db)
    assert second == {"registered": 0, "updated": 0, "seeded": 0, "skipped": 0}
    assert db.query(AiPromptDef).count() == 45
    enabled_keys = {r.key for r in db.query(AiPrompt).filter(AiPrompt.status == "enabled").all()}
    assert enabled_keys == set(prompt_service.PROMPT_META)


def test_ensure_catalog_keeps_author_versions(db) -> None:
    db.add(AiPrompt(key="generation", version=7, content="作者改过的生成提示词", status="enabled", note="手动编辑"))
    db.commit()
    _seed(db)
    row = _enabled(db, "generation")
    assert row is not None and row.content == "作者改过的生成提示词" and row.version == 7
    assert db.query(AiPrompt).filter(AiPrompt.key == "generation").count() == 1


def test_ensure_catalog_metadata_synced(db) -> None:
    _seed(db)
    row = db.query(AiPromptDef).filter(AiPromptDef.key == "rewrite_critic").one()
    assert row.title == "洗稿讨论-评审"
    assert row.module_label == "对标洗稿"
    assert row.category == "system"
    assert row.editable is True and row.optimizable is False
    assert row.default_content == prompt_catalog.default_content("rewrite_critic")


def test_contract_rows_readonly_and_mirrored(db) -> None:
    _seed(db)
    for spec in prompt_catalog.PROMPT_SPECS:
        if spec.category != "contract":
            continue
        row = db.query(AiPromptDef).filter(AiPromptDef.key == spec.key).one()
        assert row.editable is False and row.optimizable is False
        base = spec.key[: -len(".contract")]
        assert row.default_content == prompt_contract.CONTRACTS[base]


# ---------- 4. video_review 一次性升级 ----------


def test_video_review_prompt_upgraded_once(db) -> None:
    db.add(
        AiPrompt(
            key="video_review",
            version=1,
            content=prompt_service.VIDEO_REVIEW_OLD_SEED,
            status="enabled",
            note="R-237 视频复盘默认提示词",
        )
    )
    db.commit()
    _seed(db)

    assert prompt_service.run_r255_video_review_upgrade_once(db) is True
    enabled = _enabled(db, "video_review")
    assert enabled is not None and enabled.version == 2 and len(enabled.content) > 100
    assert enabled.content == prompt_catalog.default_content("video_review")
    old = db.query(AiPrompt).filter(AiPrompt.key == "video_review", AiPrompt.version == 1).one()
    assert old.status == "archived"
    assert db.get(Kv, prompt_service.VIDEO_REVIEW_UPGRADE_KV) is not None
    assert prompt_service.run_r255_video_review_upgrade_once(db) is False


def test_video_review_upgrade_skips_author_edited(db) -> None:
    custom = "作者自己改的复盘提示词：只根据真实数据解释。"
    db.add(AiPrompt(key="video_review", version=3, content=custom, status="enabled", note="手动编辑"))
    db.commit()
    _seed(db)

    assert prompt_service.run_r255_video_review_upgrade_once(db) is False
    enabled = _enabled(db, "video_review")
    assert enabled is not None and enabled.content == custom
    assert db.get(Kv, prompt_service.VIDEO_REVIEW_UPGRADE_KV) is not None


# ---------- 5. 接口 ----------


def test_api_keys_returns_all_registry(api_client, db) -> None:
    _seed(db)
    res = api_client.get("/api/prompts/keys")
    assert res.status_code == 200
    data = res.json()
    assert len(data) == 45
    keys = {item["key"] for item in data}
    assert "rewrite_critic" in keys and "chat.contract" in keys and "selfcheck_probe_json" in keys
    item = next(i for i in data if i["key"] == "rewrite_critic")
    assert item["title"] == "洗稿讨论-评审"
    assert item["module_label"] == "对标洗稿"
    assert item["purpose"]
    assert item["category"] == "system" and item["editable"] is True and item["optimizable"] is False
    assert item["llm_feature"] == "generation"
    assert item["enabled_version"] == 1
    contract = next(i for i in data if i["key"] == "chat.contract")
    assert contract["category"] == "contract" and contract["editable"] is False and contract["content"]


def test_api_save_contract_rejected(api_client, db) -> None:
    _seed(db)
    res = api_client.post("/api/prompts/chat.contract/save", json={"content": "改契约"})
    assert res.status_code == 400
    assert "程序固定" in res.json()["detail"]


def test_api_enable_contract_rejected(api_client, db) -> None:
    _seed(db)
    res = api_client.post("/api/prompts/chat.contract/enable", json={"version": 1})
    assert res.status_code == 400


def test_api_unknown_key_rejected(api_client, db) -> None:
    _seed(db)
    res = api_client.post("/api/prompts/not_exists/save", json={"content": "x"})
    assert res.status_code == 404


def test_api_optimize_not_open_rejected(api_client, db) -> None:
    _seed(db)
    res = api_client.post("/api/prompts/rewrite_critic/optimize", json={"material": ""})
    assert res.status_code == 400
    assert "暂未开放" in res.json()["detail"]


def test_api_save_new_key_creates_version(api_client, db) -> None:
    _seed(db)
    before = db.query(AiPrompt).filter(AiPrompt.key == "rewrite_critic").count()
    res = api_client.post(
        "/api/prompts/rewrite_critic/save",
        json={"content": "新的洗稿评审提示词：对照作者上下文挑问题。"},
    )
    assert res.status_code == 200
    payload = res.json()
    assert payload["version"] == before + 1
    assert payload["status"] == "enabled"
    enabled = _enabled(db, "rewrite_critic")
    assert enabled is not None and enabled.content.startswith("新的洗稿评审提示词")


# ---------- 6. 读表生效（新 key 真实进 LLM 消息） ----------


class _CaptureLLM:
    def __init__(self) -> None:
        self.messages: list[dict] = []

    def chat_completion(self, messages, **_kwargs):
        self.messages = list(messages)
        return {"content": "好的"}


def test_new_prompt_read_at_runtime(db) -> None:
    """chat_create_mode 是新 key：改库后真实拼进对话 system（证明 22 个调用点读表）。"""
    _seed(db)
    prompt_service.save_new_version(db, "chat_create_mode", "【R255 测试创作模式段】")
    fake = _CaptureLLM()
    service = chat_service.ChatService(llm=fake)
    answer = service.reply(db, "帮我聊个选题", [], mode="create")
    assert answer == "好的"
    system = fake.messages[0]["content"]
    assert "【R255 测试创作模式段】" in system
    assert system.startswith(prompt_service.get_prompt("chat", db))
