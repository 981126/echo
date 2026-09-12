"""R-139：统一模型路由与降级层测试。

覆盖验收标准：
- 模型1 主用，报错/超时/空正文/输出不合法（缺契约字段）四种情况都降级到模型2；
- 降级可见：日志 + 站内通知 + `degraded` 标记；
- 参数按厂家归一化：kimi（不支持 temperature）不传 temperature、max_tokens 抬到下限；
- 脚本生成（手动 + 自动）走生成方/评审方双模型讨论，轮次与设置一致；
- 每日自动生成篇数取运行时配置。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import Base
from app.models.draft import Draft
from app.models.kv import Kv
from app.models.notification import Notification
from app.models.platform import Creator
from app.models.prompt import AiPrompt
from app.services import debate as debate_mod
from app.services import llm_router, model_settings
from app.services import prompt_service as ps
from app.services.llm import LLMError, OpenAIClient


@pytest.fixture()
def db(tmp_path):
    eng = create_engine(f"sqlite:///{tmp_path}/t.db", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=eng)
    session = sessionmaker(bind=eng, autoflush=False, autocommit=False)()
    for key in ps.PROMPT_META:
        session.add(AiPrompt(key=key, version=1, content=ps.default_content(key), status="enabled", note="t"))
    session.add(Creator(kind="owner", name="我", is_current=True))
    session.commit()
    yield session
    session.close()
    eng.dispose()


def _set_kv(db, key: str, value: str) -> None:
    row = db.get(Kv, key)
    if row is None:
        db.add(Kv(key=key, value=value))
    else:
        row.value = value
    db.commit()


def _configure(db, *, gen_role: str = "model1", referee_role: str = "model2") -> None:
    _set_kv(db, "model1_vendor", "deepseek")
    _set_kv(db, "model1_model", "deepseek-flash")
    _set_kv(db, "model2_vendor", "kimi")
    _set_kv(db, "model2_model", "kimi-k2.6")
    _set_kv(db, "gen_role", gen_role)
    _set_kv(db, "referee_role", referee_role)


class _RecordingNotifier:
    def __init__(self):
        self.calls: list[tuple[str, str, str]] = []

    def __call__(self, feature: str, detail: str, target: str) -> None:
        self.calls.append((feature, detail, target))


@pytest.fixture(autouse=True)
def _clear_cooldown():
    llm_router.reset_notify_cooldown()
    yield
    llm_router.reset_notify_cooldown()


# ---------- 槽位解析 / 快照 ----------


def test_route_snapshot_resolves_both_slots(db):
    _configure(db)
    route = llm_router.snapshot(db)
    gen_slot, critic_slot = route.generation_pair()
    assert gen_slot["vendor"] == "deepseek" and gen_slot["model"] == "deepseek-flash"
    assert critic_slot["vendor"] == "kimi" and critic_slot["model"] == "kimi-k2.6"
    # 参数约束按厂家归一化：kimi 是推理模型
    assert critic_slot["supports_temperature"] is False
    assert critic_slot["min_max_tokens"] >= 3000
    # 两方可以选同一个模型
    _configure(db, gen_role="model2", referee_role="model2")
    gen_slot, critic_slot = llm_router.snapshot(db).generation_pair()
    assert gen_slot["slot"] == critic_slot["slot"] == "model2"


def test_kimi_slot_does_not_send_temperature(db, monkeypatch):
    """参数归一化：kimi 不传 temperature；max_tokens 抬到厂家下限（防「降级像退化」）。"""
    _configure(db)
    sent: dict = {}

    def _fake_post(self, payload):  # noqa: ANN001
        sent.update(payload)
        return {"content": "正文"}

    monkeypatch.setattr(OpenAIClient, "_post", _fake_post)
    llm = llm_router.RoutedLLM("chat", llm_router.snapshot(db), primary="model2", fallback=None)
    llm.chat([{"role": "user", "content": "hi"}], temperature=0.3, max_tokens=100)
    assert "temperature" not in sent, "kimi 推理模型不接受 temperature"
    assert sent["max_tokens"] >= 3000, "推理模型必须给足 max_tokens，否则正文会被思考吃光"


def test_deepseek_slot_sends_temperature(db, monkeypatch):
    _configure(db)
    sent: dict = {}

    def _fake_post(self, payload):  # noqa: ANN001
        sent.update(payload)
        return {"content": "正文"}

    monkeypatch.setattr(OpenAIClient, "_post", _fake_post)
    llm = llm_router.RoutedLLM("chat", llm_router.snapshot(db), primary="model1", fallback=None)
    llm.chat([{"role": "user", "content": "hi"}], temperature=0.3, max_tokens=100)
    assert sent["temperature"] == 0.3


# ---------- 降级四种触发条件 ----------


def _routed(db, feature: str = "chat", notifier=None):
    _configure(db)
    return llm_router.RoutedLLM(
        feature, llm_router.snapshot(db), notifier=notifier, target="/prompts"
    )


def test_fallback_on_error(db, monkeypatch):
    notifier = _RecordingNotifier()
    llm = _routed(db, notifier=notifier)

    class _Client:
        def __init__(self, slot):
            self.slot = slot

        def chat(self, *_a, **_k):
            if self.slot["slot"] == "model1":
                raise RuntimeError("connection reset")
            return "模型2 的正文"

    monkeypatch.setattr(llm_router, "build_client", lambda slot: _Client(slot))
    out = llm.chat([{"role": "user", "content": "hi"}])
    assert out == "模型2 的正文"
    assert llm.degraded is True
    assert llm.used_slot == "model2"
    assert len(notifier.calls) == 1
    assert "connecting reset" in notifier.calls[0][1] or "RuntimeError" in notifier.calls[0][1]


def test_fallback_on_empty_body(db, monkeypatch):
    llm = _routed(db, notifier=_RecordingNotifier())

    class _Client:
        def __init__(self, slot):
            self.slot = slot

        def chat(self, *_a, **_k):
            return "" if self.slot["slot"] == "model1" else "备用模型正文"

    monkeypatch.setattr(llm_router, "build_client", lambda slot: _Client(slot))
    assert llm.chat([{"role": "user", "content": "hi"}]) == "备用模型正文"
    assert llm.degraded is True


def test_fallback_on_invalid_json_and_missing_contract(db, monkeypatch):
    """JSON 解析失败 + 缺契约字段，都算「输出不合法」→ 降级。"""
    llm = _routed(db, notifier=_RecordingNotifier())
    calls = {"n": 0}

    class _Client:
        def __init__(self, slot):
            self.slot = slot

        def chat_json(self, *_a, **_k):
            calls["n"] += 1
            if self.slot["slot"] == "model1":
                raise LLMError("模型未返回合法 JSON")
            return {"title": "t", "script": "正文", "cover_text": "c"}

    monkeypatch.setattr(llm_router, "build_client", lambda slot: _Client(slot))
    data = llm.chat_json([{"role": "user", "content": "hi"}], require=("script",))
    assert data["script"] == "正文"
    assert llm.degraded is True
    assert calls["n"] == 2

    # 第二个：模型1 返回合法 JSON 但缺契约字段 → 判为不合法 → 降级
    llm2 = _routed(db, notifier=_RecordingNotifier())

    class _Client2:
        def __init__(self, slot):
            self.slot = slot

        def chat_json(self, *_a, **_k):
            if self.slot["slot"] == "model1":
                return {"title": "只有标题"}
            return {"script": "完整正文"}

    monkeypatch.setattr(llm_router, "build_client", lambda slot: _Client2(slot))
    data = llm2.chat_json([{"role": "user", "content": "hi"}], require=("script",))
    assert data["script"] == "完整正文"
    assert llm2.degraded is True


def test_primary_success_does_not_degrade(db, monkeypatch):
    notifier = _RecordingNotifier()
    llm = _routed(db, notifier=notifier)

    class _Client:
        def __init__(self, slot):
            self.slot = slot

        def chat(self, *_a, **_k):
            return f"{self.slot['slot']} 正文"

    monkeypatch.setattr(llm_router, "build_client", lambda slot: _Client(slot))
    assert llm.chat([{"role": "user", "content": "hi"}]) == "model1 正文"
    assert llm.degraded is False
    assert llm.used_slot == "model1"
    assert notifier.calls == []


def test_empty_body_retries_with_doubled_budget(db, monkeypatch):
    """推理模型思考吃满预算 → 空正文时，同模型重试并把 max_tokens 翻倍（R-139）。"""
    llm = _routed(db, notifier=_RecordingNotifier())
    seen: list[int] = []

    class _Client:
        def __init__(self, slot):
            self.slot = slot

        def chat(self, *_a, **kw):
            seen.append(kw["max_tokens"])
            # 第一次（预算内）空正文；翻倍后给出正文
            return "" if len(seen) == 1 else "翻倍预算后的正文"

    monkeypatch.setattr(llm_router, "build_client", lambda slot: _Client(slot))
    out = llm.chat([{"role": "user", "content": "hi"}], max_tokens=3000)
    assert out == "翻倍预算后的正文"
    assert seen[1] == seen[0] * 2, "重试必须抬高推理预算"
    assert seen[0] >= 3000, "首次至少用调用方给的预算（或厂家下限）"
    assert llm.degraded is False, "同模型重试成功不算降级"
    assert llm.used_slot == "model1"


def test_thinking_budget_exhausted_escalates_before_fallback(db, monkeypatch):
    """「思考吃光预算」是输出不可用（可重试），不是服务故障：先抬预算重试，别急着降级。"""
    from app.services.llm import LLMUnusableOutput

    notifier = _RecordingNotifier()
    llm = _routed(db, notifier=notifier)
    seen: list[int] = []

    class _Client:
        def __init__(self, slot):
            self.slot = slot

        def chat(self, *_a, **kw):
            seen.append(kw["max_tokens"])
            if len(seen) == 1:  # 首次思考吃光预算；抬预算后成功
                raise LLMUnusableOutput("推理预算被思考吃光（思考 6971 字、正文为空）")
            return "正文"

    monkeypatch.setattr(llm_router, "build_client", lambda slot: _Client(slot))
    assert llm.chat([{"role": "user", "content": "hi"}]) == "正文"
    assert seen[1] == seen[0] * 2, "同模型重试要抬高推理预算"
    assert llm.degraded is False, "同模型重试成功就不该报降级"
    assert notifier.calls == []
    assert llm.used_slot == "model1"


def test_escalated_retry_exhausted_then_falls_back_with_per_vendor_floor(db, monkeypatch):
    """主模型两次都不行才降级；备用槽位用**自己厂家**的下限，不是主模型翻倍后的预算。"""
    from app.services.llm import LLMUnusableOutput

    notifier = _RecordingNotifier()
    llm = _routed(db, notifier=notifier)
    seen: list[tuple[str, int]] = []

    class _Client:
        def __init__(self, slot):
            self.slot = slot

        def chat(self, *_a, **kw):
            seen.append((self.slot["slot"], kw["max_tokens"]))
            if self.slot["slot"] == "model1":
                raise LLMUnusableOutput("思考吃光预算")
            return "备用模型正文"

    monkeypatch.setattr(llm_router, "build_client", lambda slot: _Client(slot))
    assert llm.chat([{"role": "user", "content": "hi"}]) == "备用模型正文"
    assert seen == [("model1", 4000), ("model1", 8000), ("model2", 6000)]
    assert llm.degraded is True and llm.used_slot == "model2"
    assert len(notifier.calls) == 1
    assert "思考吃光" in notifier.calls[0][1]


def test_call_deadline_is_enforced(monkeypatch):
    """墙钟上限：httpx 的 read timeout 挡不住长时间挂起（实测曾挂 39 分钟），必须自己掐表。"""
    import httpx as _httpx

    from app.services.llm import OpenAIClient

    client = OpenAIClient("https://example.invalid", "sk-x", "m", timeout_seconds=30)
    client.timeout_seconds = 0  # deadline 立即到期；服务端还在持续吐字节（read timeout 永不触发）

    class _Resp:
        status_code = 200

        def __enter__(self):
            return self

        def __exit__(self, *_a):
            return False

        def iter_raw(self):
            def _gen():
                while True:
                    yield b" "

            return _gen()

    class _Client:
        def __init__(self, *_a, **_k):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_a):
            return False

        def stream(self, *_a, **_k):
            return _Resp()

    monkeypatch.setattr(_httpx, "Client", _Client)
    with pytest.raises(LLMError, match="按超时处理"):
        client._post({"model": "m", "messages": []})


def test_read_timeout_becomes_readable_error(monkeypatch):
    """连接层超时也要转成可读的 LLMError（而不是裸 httpx 异常）。"""
    import httpx as _httpx

    from app.services.llm import OpenAIClient

    client = OpenAIClient("https://example.invalid", "sk-x", "m")

    def _raise(*_a, **_k):
        raise _httpx.ReadTimeout("timed out")

    class _Client:
        def __init__(self, *_a, **_k):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_a):
            return False

        stream = staticmethod(_raise)

    monkeypatch.setattr(_httpx, "Client", _Client)
    with pytest.raises(LLMError, match="调用超时"):
        client._post({"model": "m", "messages": []})


def test_http_error_gives_readable_reason(monkeypatch):
    """HTTP 4xx/5xx 转成可读的 LLMError（降级通知里能直接看出是 Key 失效还是限流）。"""
    import httpx as _httpx

    from app.services.llm import OpenAIClient

    client = OpenAIClient("https://example.invalid", "sk-x", "m")

    class _Resp:
        status_code = 401
        text = '{"error":"invalid key"}'

        def __enter__(self):
            return self

        def __exit__(self, *_a):
            return False

        def read(self):
            return self.text

    class _Client:
        def __init__(self, *_a, **_k):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_a):
            return False

        def stream(self, *_a, **_k):
            return _Resp()

    monkeypatch.setattr(_httpx, "Client", _Client)
    with pytest.raises(LLMError, match="HTTP 401"):
        client._post({"model": "m", "messages": []})


def test_reasoning_budget_error_is_readable():
    """deepseek-flash / kimi 都是推理模型：正文为空但有思考时，报错要说清原因。"""
    from app.services.llm import _content_or_reason

    with pytest.raises(LLMError, match="思考"):
        _content_or_reason({"content": "", "reasoning_content": "想了很久"})
    assert _content_or_reason({"content": "正文"}) == "正文"
    assert _content_or_reason({"content": "", "reasoning_content": ""}) == ""


def test_both_models_fail_raises(db, monkeypatch):
    llm = _routed(db, notifier=_RecordingNotifier())

    class _Client:
        def __init__(self, slot):
            self.slot = slot

        def chat(self, *_a, **_k):
            raise RuntimeError(f"{self.slot['slot']} 挂了")

    monkeypatch.setattr(llm_router, "build_client", lambda slot: _Client(slot))
    with pytest.raises(LLMError, match="均未产出可用结果"):
        llm.chat([{"role": "user", "content": "hi"}])


def test_no_fallback_when_fallback_is_primary(db, monkeypatch):
    """两方选同一个模型时不重复调两遍。"""
    _configure(db, gen_role="model1", referee_role="model1")
    llm = llm_router.RoutedLLM("chat", llm_router.snapshot(db), notifier=_RecordingNotifier())
    calls = {"n": 0}

    class _Client:
        def __init__(self, slot):
            self.slot = slot

        def chat(self, *_a, **_k):
            calls["n"] += 1
            return "正文"

    monkeypatch.setattr(llm_router, "build_client", lambda slot: _Client(slot))
    llm.chat([{"role": "user", "content": "hi"}])
    assert calls["n"] == 1


# ---------- 站内通知（降级可见） ----------


def test_degradation_writes_in_app_notification(db, monkeypatch):
    """默认通知落地：站内通知表有 llm_fallback 记录（带功能名与原因）。"""
    llm = _routed(db)  # 不注入 notifier → 走默认通知

    class _Client:
        def __init__(self, slot):
            self.slot = slot

        def chat(self, *_a, **_k):
            if self.slot["slot"] == "model1":
                raise RuntimeError("boom")
            return "备用正文"

    monkeypatch.setattr(llm_router, "build_client", lambda slot: _Client(slot))
    llm.chat([{"role": "user", "content": "hi"}])
    # 默认通知走 SessionLocal 短连接（跨线程安全），所以用会话工厂查
    from app.db import SessionLocal

    own = SessionLocal()
    try:
        rows = own.query(Notification).filter(Notification.kind == "llm_fallback").all()
    finally:
        own.close()
    assert rows, "降级必须写站内通知"
    assert "模型1" in rows[-1].title and "AI 对话" in rows[-1].title
    assert rows[-1].target == "/prompts"


def test_fallback_detail_mentions_feature_and_reason(db, monkeypatch):
    notifier = _RecordingNotifier()
    llm = _routed(db, feature="persona_init", notifier=notifier)

    class _Client:
        def __init__(self, slot):
            self.slot = slot

        def chat_json(self, *_a, **_k):
            if self.slot["slot"] == "model1":
                raise RuntimeError("timeout")
            return {"tags": ["a"]}

    monkeypatch.setattr(llm_router, "build_client", lambda slot: _Client(slot))
    llm.chat_json([{"role": "user", "content": "hi"}])
    feature, detail, target = notifier.calls[0]
    assert feature == "persona_init"
    assert "人设提取" in detail and "超时" not in detail  # 详情写的是原始异常
    assert "RuntimeError" in detail
    assert target == "/prompts"


# ---------- 脚本生成：双模型讨论 + 轮次 ----------


def _fake_debate_clients(monkeypatch, calls: list[tuple[str, str]], *, script: str = "脚本正文，够长了吧看看。"):
    class _Client:
        def __init__(self, slot):
            self.slot = slot

        def chat_json(self, *_a, **_k):
            calls.append((self.slot["slot"], "json"))
            return {"title": "标题", "cover_text": "封面", "script": script, "shells": {"douyin": "d"}}

        def chat(self, *_a, **_k):
            calls.append((self.slot["slot"], "chat"))
            return "评审或修订后的正文"

    monkeypatch.setattr(llm_router, "build_client", lambda slot: _Client(slot))


def test_run_debate_uses_configured_pair_and_rounds(db, monkeypatch):
    _configure(db, gen_role="model2", referee_role="model1")
    _set_kv(db, "debate_rounds", "3")
    calls: list[tuple[str, str]] = []
    _fake_debate_clients(monkeypatch, calls)

    draft = Draft(title="选题", script="（占位）", source="ai")
    db.add(draft)
    db.commit()
    res = debate_mod.run_debate(db, draft, "选题")
    assert res["models"] == {"gen": "model2", "critic": "model1"}
    assert res["rounds"] == 3
    quality = json.loads(draft.quality)
    assert quality["rounds"] == 3
    assert quality["rounds_done"] == 3, "讨论轮次必须跟随设置"
    # 每轮：评审 + 修订
    assert calls.count(("model1", "chat")) == 3
    assert calls.count(("model2", "chat")) >= 3


def test_run_debate_falls_back_to_other_slot_for_initial(db, monkeypatch):
    _configure(db, gen_role="model1", referee_role="model2")
    _set_kv(db, "debate_rounds", "1")

    class _Client:
        def __init__(self, slot):
            self.slot = slot

        def chat_json(self, *_a, **_k):
            if self.slot["slot"] == "model1":
                raise RuntimeError("生成方挂了")
            return {"title": "备选标题", "cover_text": "封面", "script": "备选正文"}

        def chat(self, *_a, **_k):
            return "评审或修订后的正文"

    monkeypatch.setattr(llm_router, "build_client", lambda slot: _Client(slot))
    draft = Draft(title="选题", script="（占位）", source="ai")
    db.add(draft)
    db.commit()
    res = debate_mod.run_debate(db, draft, "选题")
    assert res["fallback"] is True
    assert draft.title == "备选标题"
    assert json.loads(draft.quality)["fallback"] is True


def test_debate_rounds_reads_kv_then_env(db):
    _set_kv(db, "debate_rounds", "7")
    assert debate_mod.debate_rounds(db) == 7
    _set_kv(db, "debate_rounds", "999")
    assert debate_mod.debate_rounds(db) == 10  # 夹在 1–10


def test_daily_pipeline_topics_count_follows_runtime_config(db):
    _set_kv(db, "pipeline_topics_count", "4")
    assert model_settings.topics_count(db) == 4
    model_settings.save_topics_count(db, 1)
    assert model_settings.topics_count(db) == 1


# ---------- ASR 运行时配置实时生效（R-138 接线验证） ----------


def test_transcription_uses_runtime_asr_config(db, monkeypatch):
    """在设置页改 ASR 后，**下一次转写**就用新配置（不是重启后才生效）。"""
    from app.models.video import Video
    from app.services import ingest

    video = Video(filename="a.mp4", title="素材")
    db.add(video)
    db.commit()

    seen: dict = {}

    class _FakeTranscriber:
        def __init__(self, settings=None, mode=None, model=None):
            seen["mode"] = mode
            seen["model"] = model

        def transcribe(self, _path):
            return "转写正文"

    monkeypatch.setattr(ingest, "Transcriber", _FakeTranscriber)
    monkeypatch.setattr(ingest, "correct_transcript", lambda text, source_text="", llm=None, db=None: text)
    monkeypatch.setattr(ingest, "enqueue_persona_incremental", lambda db, video=None, creator_id=None: None)
    monkeypatch.setattr(ingest.PersonaService, "suggest_video_tags", lambda self, text: {})

    # 运行时配置：硅基流动 + 指定模型（不动 .env）
    _set_kv(db, "asr_mode", "siliconflow")
    _set_kv(db, "asr_model", "FunAudioLLM/SenseVoiceSmall")
    ingest.import_video_task(db, {"video_id": video.id})
    assert seen == {"mode": "siliconflow", "model": "FunAudioLLM/SenseVoiceSmall"}
    db.refresh(video)
    assert video.transcript.asr_provider == "siliconflow"
    assert video.transcript.asr_model == "FunAudioLLM/SenseVoiceSmall"


# ---------- 非脚本生成功能走模型1 ----------


def test_chat_service_uses_model1_primary(db, monkeypatch):
    from app.services.chat_service import ChatService

    _configure(db)
    seen: list[str] = []

    class _Client:
        def __init__(self, slot):
            self.slot = slot

        def chat_completion(self, *_a, **_k):
            seen.append(self.slot["slot"])
            return {"content": "回答"}

    monkeypatch.setattr(llm_router, "build_client", lambda slot: _Client(slot))
    service = ChatService(db=db)
    assert service.reply(db, "你好", []) == "回答"
    assert seen == ["model1"]


def test_persona_service_defaults_to_model1(db, monkeypatch):
    from app.services.persona import PersonaService

    _configure(db)
    seen: list[str] = []

    class _Client:
        def __init__(self, slot):
            self.slot = slot

        def chat_json(self, *_a, **_k):
            seen.append(self.slot["slot"])
            return {"tags": [{"label": "直接", "description": "d", "dimension": "语气", "evidence": "e"}], "redlines": []}

    monkeypatch.setattr(llm_router, "build_client", lambda slot: _Client(slot))
    service = PersonaService(db=db)
    service.analyze_one("一篇口播稿")
    assert seen == ["model1"]
    assert service.last_routing["degraded"] is False
    assert service.last_routing["used"].startswith("model1")


def test_openai_client_still_default_for_injected_llm(db):
    """注入 llm 时不做路由（测试/显式指定路径不能被破坏）。"""
    from app.services.persona import PersonaService

    class _Fake:
        def chat_json(self, *_a, **_k):
            return {"tags": [], "redlines": []}

    service = PersonaService(llm=_Fake(), db=db)
    service.analyze_one("x")
    assert service.last_routing == {}
