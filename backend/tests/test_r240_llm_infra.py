"""R-240 S4/M6：LLM 客户端复用 + KV 批读 + 超时预算/deadline（后端自测）。

覆盖：
- `llm.py` 共享 httpx.Client：同 base_url 只建一次、per-request timeout、墙钟 deadline 仍生效、
  `close_all_clients()` 关闭并清空、共享池构造失败仍回退旧行为（每次新建）；
- `model_settings._kv_get_many`：一次 `key IN`、strip/缺失语义、已解析 config 复用、保存立即生效；
- `llm_router.snapshot`：KV 查询 20~21 条 → ≤3（实际 1 条）；
- M6 feature 超时表取值、全局上限与调用方剩余 deadline 的 min 规则；
- `RoutedLLM` 每次 attempt 带 feature 预算，且降级/重试语义、对旧单参 `build_client` 的兼容不变；
- `chat_service` 每次 LLM 调用传剩余 deadline；
- `evidence.select_references` 选文调用传 ≤45s 单次预算（线程泄漏上限从 600s 降到 45s）。
"""

from __future__ import annotations

import json
import sys
import types
from contextlib import contextmanager
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import httpx
import pytest
from conftest import ensure_schema, fresh_engine
from sqlalchemy import event
from sqlalchemy.orm import sessionmaker

from app.config import get_settings
from app.models.kv import Kv
from app.services import evidence, llm_router, model_settings
from app.services import llm as llm_mod
from app.services.chat_service import ChatService
from app.services.llm import LLMError, OpenAIClient


@pytest.fixture()
def db(tmp_path):
    eng = fresh_engine()
    ensure_schema(eng)
    session = sessionmaker(bind=eng, autoflush=False, autocommit=False)()
    yield session
    session.close()


@pytest.fixture(autouse=True)
def _reset_llm_clients():
    """共享 Client 是进程级的：每个用例前后都清空，避免假客户端/旧连接串到下一用例。"""
    llm_mod.close_all_clients()
    yield
    llm_mod.close_all_clients()


@pytest.fixture(autouse=True)
def _pin_llm_global_timeout(monkeypatch):
    """本文件断言的是 feature 表取值：把全局上限固定为默认 600，避免 .env 调参影响结果。"""
    monkeypatch.setattr(get_settings(), "llm_timeout_seconds", 600, raising=False)


def _set_kv(db, key: str, value: str) -> None:
    row = db.get(Kv, key)
    if row is None:
        db.add(Kv(key=key, value=value))
    else:
        row.value = value
    db.commit()


def _configure_models(db) -> None:
    _set_kv(db, "model1_vendor", "deepseek")
    _set_kv(db, "model1_model", "deepseek-flash")
    _set_kv(db, "model1_key", "sk-model1")
    _set_kv(db, "model2_vendor", "kimi")
    _set_kv(db, "model2_model", "kimi-k2.6")
    _set_kv(db, "model2_key", "sk-model2")
    _set_kv(db, "gen_role", "model1")
    _set_kv(db, "referee_role", "model2")


@contextmanager
def _sql_count(db):
    """统计上下文内执行的 SQL 条数（R-240 验收：KV 批读/配置复用必须减少往返）。"""
    counter = {"n": 0}
    bind = db.get_bind()

    def _before(*_args, **_kwargs):
        counter["n"] += 1

    event.listen(bind, "before_cursor_execute", _before)
    try:
        yield counter
    finally:
        event.remove(bind, "before_cursor_execute", _before)


# ---------- S4：model_settings KV 批读 ----------


def test_kv_get_many_is_one_query_and_strips(db):
    _set_kv(db, "model1_vendor", "  deepseek  ")
    _set_kv(db, "model1_model", "deepseek-flash")
    with _sql_count(db) as counter:
        kv = model_settings._kv_get_many(
            db, ["model1_vendor", "model1_model", "missing_key"]
        )
    assert counter["n"] == 1, "批读必须一条 key IN，不能退化成逐 key 查询"
    assert kv == {"model1_vendor": "deepseek", "model1_model": "deepseek-flash"}
    assert "missing_key" not in kv, "缺失键不在结果里（调用方用 .get 取空串）"


def test_model_config_reuse_avoids_extra_queries(db):
    _configure_models(db)
    config = model_settings.get_model_config(db)
    with _sql_count(db) as counter:
        slots = model_settings.resolve_slots(db, config)
        roles = model_settings.generation_roles(db, config)
        asr = model_settings.asr_config(db, config)
    assert counter["n"] == 0, "传入已解析 config 后不应再查库（单请求内只解析一次）"
    assert slots["model1"]["api_key"] == "sk-model1"
    assert slots["model2"]["model"] == "kimi-k2.6"
    assert roles == ("model1", "model2")
    assert asr["mode"] == "mock"  # 测试环境 .env ECHO_ASR_MODE=mock


def test_feature_route_reuses_config_for_gen_expansion(db):
    _configure_models(db)  # gen_role = model1
    config = model_settings.get_model_config(db)
    # prompt_opt 组默认 `gen`（跟随生成方）：复用 config 展开，不再重复批读
    assert model_settings.feature_route(db, "prompt_optimize", config) == "model1"
    assert model_settings.feature_route(db, "chat", config) == "model1"


def test_snapshot_batches_config_read(db):
    _configure_models(db)
    with _sql_count(db) as counter:
        route = llm_router.snapshot(db)
    assert counter["n"] <= 3, f"snapshot 应从 20~21 条 KV 降到 ≤3 条，实际 {counter['n']}"
    gen_slot, critic_slot = route.generation_pair()
    assert gen_slot["slot"] == "model1" and gen_slot["model"] == "deepseek-flash"
    assert critic_slot["slot"] == "model2" and critic_slot["model"] == "kimi-k2.6"
    assert gen_slot["api_key"] == "sk-model1", "Key 仍优先取 DB 配置"


def test_settings_take_effect_immediately_without_cache(db):
    _configure_models(db)
    assert model_settings.resolve_slots(db)["model1"]["model"] == "deepseek-flash"
    _set_kv(db, "model1_model", "deepseek-v4-pro")
    assert model_settings.resolve_slots(db)["model1"]["model"] == "deepseek-v4-pro", (
        "保存设置必须立即生效：只做单请求内复用，不做跨请求长缓存"
    )


# ---------- M6：feature 超时预算表 ----------


def test_feature_timeout_table_values():
    assert llm_router.feature_timeout_seconds("chat") == 90
    assert llm_router.feature_timeout_seconds("ideas") == 30
    assert llm_router.feature_timeout_seconds("draft_meta") == 90
    assert llm_router.feature_timeout_seconds("correct") == 120
    assert llm_router.feature_timeout_seconds("video_tags") == 120
    assert llm_router.feature_timeout_seconds("persona_init") == 300
    assert llm_router.feature_timeout_seconds("persona_merge") == 360
    assert llm_router.feature_timeout_seconds("persona_updates") == 120
    assert llm_router.feature_timeout_seconds("persona_compare") == 120
    assert llm_router.feature_timeout_seconds("diff") == 120
    assert llm_router.feature_timeout_seconds("feedback_analysis") == 120
    assert llm_router.feature_timeout_seconds("prompt_optimize") == 240
    assert llm_router.feature_timeout_seconds("prompt_eval") == 180
    assert llm_router.feature_timeout_seconds("benchmark") == 240
    assert llm_router.feature_timeout_seconds("video_review") == 180
    assert llm_router.feature_timeout_seconds("generation") == 360
    assert llm_router.feature_timeout_seconds("debate") == 360
    assert llm_router.feature_timeout_seconds("rework") == 360
    assert llm_router.feature_timeout_seconds("rewrite") == 360
    assert llm_router.feature_timeout_seconds("unknown_feature") == 120, "未标定功能走 misc 兜底"
    assert llm_router.feature_timeout_seconds("chat") < llm_router.feature_timeout_seconds("generation")


def test_all_known_features_have_bounded_budget():
    for feature in llm_router.FEATURE_LABELS:
        budget = llm_router.feature_timeout_seconds(feature)
        assert 30 <= budget <= 600, f"{feature} 的超时预算 {budget}s 不在合理区间"


def test_feature_timeout_respects_global_limit_and_requested(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "llm_timeout_seconds", 60, raising=False)
    assert llm_router.feature_timeout_seconds("chat") == 60, "全局上限仍是兜底，取 min"
    assert llm_router.feature_timeout_seconds("chat", 45) == 45, "调用方剩余 deadline 再取 min"
    assert llm_router.feature_timeout_seconds("chat", 5) == 30, "不低过客户端下限（防误配 0/负数）"


def test_build_client_threads_timeout():
    slot = {
        "base_url": "https://llm.example",
        "api_key": "sk-x",
        "model": "m",
        "supports_temperature": True,
    }
    client = llm_router.build_client(slot, timeout_seconds=120)
    assert isinstance(client, OpenAIClient)
    assert client.timeout_seconds == 120


# ---------- M6：RoutedLLM 每次 attempt 使用预算 ----------


class _RecordingClient:
    """记录 chat 调用的假客户端（替换 build_client 用）。"""

    def __init__(self, slot: dict, fail: bool = False):
        self.slot = slot
        self.fail = fail
        self.timeout_seconds: int | None = None

    def chat(self, *_args, **_kwargs) -> str:
        if self.fail:
            raise LLMError("模型不可用")
        return "正文"


def test_routed_llm_passes_feature_budget_to_client(db, monkeypatch):
    _configure_models(db)
    seen: list[int | None] = []

    def _build(slot, timeout_seconds=None):
        seen.append(timeout_seconds)
        return _RecordingClient(slot)

    monkeypatch.setattr(llm_router, "build_client", _build)
    llm = llm_router.RoutedLLM("chat", llm_router.snapshot(db))
    assert llm.chat([{"role": "user", "content": "hi"}]) == "正文"
    assert seen == [90], "chat 单次调用预算是 90s"

    seen.clear()
    llm.chat([{"role": "user", "content": "hi"}], timeout_seconds=45)
    assert seen == [45], "调用方剩余 deadline 更紧时取 min"

    seen.clear()
    llm.chat([{"role": "user", "content": "hi"}], timeout_seconds=5)
    assert seen == [30], "预算不低过客户端下限"


def test_timeout_budget_does_not_change_fallback_semantics(db, monkeypatch):
    """只收紧单次墙钟，不改「主模型失败 → 降级模型」的语义与降级标记。"""
    _configure_models(db)
    seen: list[tuple[str, int | None]] = []

    def _build(slot, timeout_seconds=None):
        seen.append((slot["slot"], timeout_seconds))
        return _RecordingClient(slot, fail=slot["slot"] == "model1")

    monkeypatch.setattr(llm_router, "build_client", _build)
    llm = llm_router.RoutedLLM("chat", llm_router.snapshot(db), notifier=lambda *a: None)
    assert llm.chat([{"role": "user", "content": "hi"}]) == "正文"
    assert llm.degraded is True
    assert llm.used_slot == "model2"
    assert seen == [("model1", 90), ("model2", 90)]


def test_routed_llm_json_and_completion_also_carry_budget(db, monkeypatch):
    """chat_json / chat_completion 与 chat 一样带 feature 预算（三条主路径都要覆盖）。"""
    _configure_models(db)
    seen: list[int | None] = []

    class _Client:
        def __init__(self, slot: dict):
            self.slot = slot
            self.timeout_seconds: int | None = None

        def chat_json(self, *_args, **_kwargs) -> dict:
            return {"script": "正文"}

        def chat_completion(self, *_args, **_kwargs) -> dict:
            return {"content": "正文"}

    def _build(slot, timeout_seconds=None):
        seen.append(timeout_seconds)
        return _Client(slot)

    monkeypatch.setattr(llm_router, "build_client", _build)
    llm = llm_router.RoutedLLM("draft_meta", llm_router.snapshot(db))
    assert llm.chat_json([{"role": "user", "content": "hi"}], require=("script",))["script"] == "正文"
    assert llm.chat_completion([{"role": "user", "content": "hi"}])["content"] == "正文"
    assert llm.chat_json([{"role": "user", "content": "hi"}], timeout_seconds=45)["script"] == "正文"
    assert seen == [90, 90, 45], "draft_meta=90s；显式剩余 deadline 再取 min"


def test_routed_llm_accepts_legacy_single_arg_build_client(db, monkeypatch):
    """`build_client` 新增可选 timeout 参数后，只有单参的旧实现/测试替身不能被打破。"""
    _configure_models(db)

    class _LegacyClient:
        def __init__(self, slot: dict):
            self.slot = slot
            self.timeout_seconds: int | None = None

        def chat(self, *_args, **_kwargs) -> str:
            return "正文"

    monkeypatch.setattr(llm_router, "build_client", lambda slot: _LegacyClient(slot))
    llm = llm_router.RoutedLLM("chat", llm_router.snapshot(db))
    assert llm.chat([{"role": "user", "content": "hi"}]) == "正文"


# ---------- S4：llm.py 共享 httpx.Client ----------


class _OkResponse:
    status_code = 200

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def iter_bytes(self):
        message = {"choices": [{"message": {"content": "正文"}}]}
        yield json.dumps(message).encode()


def test_shared_client_is_reused_per_base_url(monkeypatch):
    created: list[dict] = []

    class _FakeClient:
        def __init__(self, *_args, **kwargs):
            created.append(kwargs)
            self.stream_kwargs: list[dict] = []
            self.closed = False

        def stream(self, *_args, **kwargs):
            self.stream_kwargs.append(kwargs)
            return _OkResponse()

        def close(self):
            self.closed = True

    monkeypatch.setattr(llm_mod.httpx, "Client", _FakeClient)
    first = OpenAIClient("https://llm.example", "sk-x", "m", timeout_seconds=90)
    second = OpenAIClient("https://llm.example", "sk-x", "m", timeout_seconds=90)
    assert first._post({"model": "m"})["content"] == "正文"
    assert second._post({"model": "m"})["content"] == "正文"

    assert len(created) == 1, "同一个 base_url 只建一个 Client（复用 TCP/TLS 连接池）"
    client_kwargs = created[0]
    assert client_kwargs["timeout"] is None, "共享 Client 不设全局 timeout，改由每请求传入"
    assert client_kwargs["trust_env"] is True
    limits = client_kwargs["limits"]
    assert limits.max_connections == 8
    assert limits.max_keepalive_connections == 4
    assert limits.keepalive_expiry == pytest.approx(120.0), "keepalive_expiry=120s 保证讨论轮间连接不失效"

    shared = llm_mod._client_for("https://llm.example")
    assert len(shared.stream_kwargs) == 2
    for stream_kwargs in shared.stream_kwargs:
        timeout = stream_kwargs["timeout"]
        assert isinstance(timeout, httpx.Timeout)
        assert timeout.read == pytest.approx(90.0), "read 与本次墙钟同值"
        assert timeout.connect == pytest.approx(15.0)

    llm_mod.close_all_clients()
    assert shared.closed is True
    assert llm_mod._CLIENTS == {}, "close_all_clients 必须清空缓存（进程退出 atexit 调用）"


def test_shared_client_build_failure_falls_back_to_per_call_client(monkeypatch):
    """共享池构造失败 → 回退旧行为（每次新建、用完关闭）；恢复后重新缓存复用。"""
    created: list = []

    class _FlakyClient:
        fail_next = True

        def __init__(self, *_args, **_kwargs):
            if _FlakyClient.fail_next:
                _FlakyClient.fail_next = False
                raise RuntimeError("client pool boom")
            created.append(self)
            self.closed = False

        def stream(self, *_args, **_kwargs):
            return _OkResponse()

        def close(self):
            self.closed = True

    monkeypatch.setattr(llm_mod.httpx, "Client", _FlakyClient)
    client = OpenAIClient("https://llm.fallback", "sk-x", "m", timeout_seconds=30)
    assert client._post({"model": "m"})["content"] == "正文", "构造失败仍要能调用"
    assert len(created) == 1
    assert created[0].closed is True, "回退新建的 Client 用完必须关闭"

    assert client._post({"model": "m"})["content"] == "正文"
    assert len(created) == 2, "共享池恢复后应缓存复用，不再每次新建"


class _EndlessResponse:
    status_code = 200

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def iter_bytes(self):
        while True:
            yield b" "


def test_post_still_enforces_wall_clock_deadline(monkeypatch):
    """共享 Client 不能丢掉「有零碎字节但永不结束」时的墙钟掐表（R-139 实测挂 39 分钟）。"""

    class _FakeClient:
        def __init__(self, *_args, **_kwargs):
            pass

        def stream(self, *_args, **_kwargs):
            return _EndlessResponse()

    monkeypatch.setattr(llm_mod.httpx, "Client", _FakeClient)
    client = OpenAIClient("https://llm.deadline", "sk-x", "m", timeout_seconds=30)
    client.timeout_seconds = 0  # 墙钟立即到期；read timeout 不会触发
    with pytest.raises(LLMError, match="按超时处理"):
        client._post({"model": "m"})


# ---------- M6：chat_service 剩余 deadline 下传 ----------


def test_chat_service_passes_remaining_deadline(db, monkeypatch):
    monkeypatch.setattr(get_settings(), "agent_timeout_seconds", 120, raising=False)
    seen: list[int | None] = []

    class _ScriptedLLM:
        def __init__(self) -> None:
            self.calls = 0

        def chat_completion(self, messages, **kwargs):
            seen.append(kwargs.get("timeout_seconds"))
            self.calls += 1
            if self.calls == 1:
                return {
                    "content": "",
                    "tool_calls": [
                        {"id": "c1", "function": {"name": "search_videos", "arguments": "{}"}}
                    ],
                }
            return {"content": "最终回答"}

    reply = ChatService(llm=_ScriptedLLM(), db=db).reply(db, "素材库有多少条", [])
    assert reply == "最终回答"
    assert len(seen) == 2, "工具轮 + 收尾轮都要带剩余 deadline"
    for value in seen:
        assert value is not None
        assert 5 <= int(value) <= 120, f"剩余 deadline 应落在 [5, agent_timeout] 内，实际 {value}"


# ---------- M6：evidence 选文 timeout 下传 ----------


def _evidence_settings(monkeypatch, pick_timeout: int) -> None:
    monkeypatch.setattr(
        evidence,
        "get_settings",
        lambda: types.SimpleNamespace(
            online_ref_pick_min=2,
            online_ref_pick_max=3,
            online_pick_timeout_seconds=pick_timeout,
        ),
    )


def test_select_references_caps_picker_timeout(monkeypatch):
    seen: list[int | None] = []

    class _Picker:
        def chat_json(self, messages, **kwargs):
            seen.append(kwargs.get("timeout_seconds"))
            return {"picks": [{"id": 1, "reason": "提供薪资数据"}]}

    cands = [
        {"title": f"文章{i}", "url": f"https://x.com/{i}", "summary": "摘要"} for i in range(1, 4)
    ]
    _evidence_settings(monkeypatch, 45)
    picked = evidence.select_references(_Picker(), cands, topic="选题", min_pick=2, max_pick=3)
    assert seen == [45], "选文调用必须把 ≤45s 的单次预算传给底层 LLM"
    assert picked and picked[0]["reason"] == "提供薪资数据"

    seen.clear()
    _evidence_settings(monkeypatch, 10)
    evidence.select_references(_Picker(), cands, topic="选题", min_pick=2, max_pick=3)
    assert seen == [10], "配置更小时跟配置（不超过 45s 上限）"


def test_select_references_picker_without_timeout_kwarg_still_works(monkeypatch):
    """注入的旧客户端/测试替身不接受 timeout_seconds 时退回普通调用（R-233 兼容）。"""

    class _LegacyPicker:
        def chat_json(self, messages, temperature=0.3, max_tokens=800, require=()):
            return {"picks": [{"id": 1, "reason": "旧替身选文"}]}

    cands = [
        {"title": f"文章{i}", "url": f"https://x.com/{i}", "summary": "摘要"} for i in range(1, 4)
    ]
    _evidence_settings(monkeypatch, 45)
    picked = evidence.select_references(_LegacyPicker(), cands, topic="选题", min_pick=2, max_pick=3)
    assert picked and picked[0]["reason"] == "旧替身选文"
