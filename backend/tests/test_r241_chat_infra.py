"""R-241 实施 B：chat 流 async 化 + ChatService 连接释放 + 工具墙钟 + 模型自检并行。

覆盖（对应 design §5.2/§5.5）：
1. `POST /api/chat/stream` 为 async 端点：SSE 事件类型/顺序/JSON/文案与旧实现一致，
   error/空消息/会话不存在等错误语义不变，流结束后 user+assistant 消息正常落库；
2. `ChatService.reply` 每次 LLM/工具调用前 commit（DB 读事务不跨调用常驻）；
3. 只读工具走独立 Session + 线程池，单工具超时返回可读跳过原因；写操作工具仍在主线程/主 Session；
4. `model_health.run_selfcheck` 2 槽 × 3 探针并行（并发 ≤3）、单探针超时记 incompatible + 耗时，
   结果结构与保存（app_kv）不变。
"""

from __future__ import annotations

import inspect
import json
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest
from conftest import ensure_schema, fresh_engine
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from app.api import chat as chat_api
from app.models.chat import ChatMessage
from app.services import chat_service, model_health
from app.services.chat_service import ChatService


@pytest.fixture()
def db(tmp_path):
    eng = fresh_engine()
    ensure_schema(eng)
    session = sessionmaker(bind=eng, autoflush=False, autocommit=False)()
    yield session
    session.close()


@pytest.fixture()
def client():
    app = FastAPI()
    app.include_router(chat_api.router, prefix="/api/chat")
    with TestClient(app) as c:
        yield c


# ---------- ① SSE 流：async 端点 + 事件契约 ----------


def _parse_sse(text: str) -> list[dict]:
    """把 SSE 文本解析成 [{event, data}]（无 event 行的默认帧记作 message）。"""
    events: list[dict] = []
    for block in text.split("\n\n"):
        block = block.strip("\n")
        if not block:
            continue
        event = "message"
        data_text = ""
        for line in block.split("\n"):
            if line.startswith("event: "):
                event = line[len("event: ") :]
            elif line.startswith("data: "):
                data_text += line[len("data: ") :]
        events.append({"event": event, "data": json.loads(data_text) if data_text else None})
    return events


def test_stream_endpoint_is_async():
    """流期间不占 anyio 线程的前提：端点必须是 async（同步生成器会被 iterate_in_threadpool 占线程）。"""
    assert inspect.iscoroutinefunction(chat_api.chat_stream)


class _ScriptedChatService:
    """按脚本产出两条 step，再返回固定回答（不碰 LLM/DB 工具）。"""

    def __init__(self, db=None):
        self.db = db

    def reply(self, db, user_message, history, *, conversation_id=None, on_step=None, mode="ops"):
        if on_step is not None:
            on_step({"kind": "tool", "name": "search_videos", "args": {}, "round": 1})
            on_step({"kind": "result", "name": "search_videos", "summary": "共 0 条"})
        return "这是一段超过十二个字的回答内容"


class _BoomChatService:
    def __init__(self, db=None):
        self.db = db

    def reply(self, db, user_message, history, *, conversation_id=None, on_step=None, mode="ops"):
        raise RuntimeError("模型挂了")


def test_stream_events_keep_old_format_and_order(client, db, monkeypatch):
    monkeypatch.setattr(chat_api, "ChatService", _ScriptedChatService)
    res = client.post(
        "/api/chat/stream",
        json={"message": "素材库有多少条", "conversation_id": None},
    )
    assert res.status_code == 200
    assert res.headers["content-type"].startswith("text/event-stream")
    assert res.headers["cache-control"] == "no-cache"

    events = _parse_sse(res.text)
    assert [e["event"] for e in events] == ["step", "step", "start", "message", "message", "done"]
    assert events[0]["data"] == {"kind": "tool", "name": "search_videos", "args": {}, "round": 1}
    assert events[1]["data"] == {"kind": "result", "name": "search_videos", "summary": "共 0 条"}
    message_id = events[2]["data"]["message_id"]
    assert isinstance(message_id, int) and message_id > 0
    deltas = [e["data"]["delta"] for e in events if e["event"] == "message"]
    assert [len(d) for d in deltas] == [12, 3], "打字机按 12 字一段（与旧实现一致）"
    assert "".join(deltas) == "这是一段超过十二个字的回答内容"
    assert events[-1]["data"] == {"done": True, "message_id": message_id}

    # 逐字帧格式（event/data 行、UTF-8 原文、空行分隔）与旧实现一致
    assert 'event: step\ndata: {"kind": "tool", "name": "search_videos", "args": {}, "round": 1}\n\n' in res.text
    assert f'event: start\ndata: {{"message_id": {message_id}}}\n\n' in res.text
    assert 'data: {"delta": "这是一段超过十二个字的回"}\n\n' in res.text
    assert res.text.endswith(f'event: done\ndata: {{"done": true, "message_id": {message_id}}}\n\n')

    # worker 已把 user / assistant 消息落库（流结束后立即可见）
    rows = db.query(ChatMessage).order_by(ChatMessage.id).all()
    assert [r.role for r in rows] == ["user", "assistant"]
    assert rows[0].content == "素材库有多少条"
    assert rows[1].content == "这是一段超过十二个字的回答内容"
    assert rows[1].id == message_id


def test_stream_error_event_keeps_message_shape(client, db, monkeypatch):
    monkeypatch.setattr(chat_api, "ChatService", _BoomChatService)
    res = client.post("/api/chat/stream", json={"message": "问题", "conversation_id": None})
    assert res.status_code == 200
    # 与旧实现一致：event: error + {"message": str(exc)}，且不出现 done
    assert res.text == 'event: error\ndata: {"message": "模型挂了"}\n\n'
    assert "event: done" not in res.text
    # 失败时只有 user 消息落库，不写 assistant
    assert [r.role for r in db.query(ChatMessage).order_by(ChatMessage.id).all()] == ["user"]


def test_stream_unknown_conversation_reports_error(client, db, monkeypatch):
    monkeypatch.setattr(chat_api, "ChatService", _ScriptedChatService)
    res = client.post("/api/chat/stream", json={"message": "问题", "conversation_id": 999999})
    assert res.status_code == 200
    assert res.text == 'event: error\ndata: {"message": "会话不存在"}\n\n'


def test_stream_empty_message_returns_400(client):
    res = client.post("/api/chat/stream", json={"message": "   "})
    assert res.status_code == 400
    assert res.json()["detail"] == "消息不能为空"


# ---------- ② ChatService：每次 LLM/工具调用前 commit ----------


def test_reply_commits_before_llm_and_tool_calls(db, monkeypatch):
    llm_states: list[bool] = []
    tool_calls: list[tuple[str, bool, bool, str]] = []

    class _LLM:
        def __init__(self) -> None:
            self.calls = 0

        def chat_completion(self, messages, **_kwargs):
            llm_states.append(db.in_transaction())
            self.calls += 1
            if self.calls == 1:
                return {
                    "content": "",
                    "tool_calls": [
                        {"id": "c1", "function": {"name": "search_videos", "arguments": "{}"}},
                        {
                            "id": "c2",
                            "function": {"name": "generate_draft", "arguments": '{"topic": "x"}'},
                        },
                    ],
                }
            return {"content": "最终回答"}

    def _fake_dispatch(session, name, args, context=None):
        tool_calls.append(
            (name, session is db, session.in_transaction(), threading.current_thread().name)
        )
        return {"ok": True}

    monkeypatch.setattr(chat_service, "_dispatch", _fake_dispatch)
    reply = ChatService(llm=_LLM(), db=db).reply(db, "问题", [])

    assert reply == "最终回答"
    assert llm_states, "应有两次 LLM 调用"
    assert not any(llm_states), "每次 LLM 调用前必须 commit（不再持有读事务/DB 连接）"
    read_tool = next(t for t in tool_calls if t[0] == "search_videos")
    write_tool = next(t for t in tool_calls if t[0] == "generate_draft")
    assert read_tool[1] is False, "只读工具用独立 Session"
    assert read_tool[3].startswith("echo-chat-tool"), "只读工具在线程池线程执行"
    assert write_tool[1] is True, "写操作工具仍在主 Session"
    assert write_tool[3] == threading.current_thread().name, "写操作工具仍在主线程"


# ---------- ③ chat 工具单工具墙钟 ----------


def test_run_tool_timeout_returns_readable_skip(db, monkeypatch):
    monkeypatch.setattr(chat_service, "TOOL_TIMEOUT_SECONDS", 0.2)

    def _slow_dispatch(session, name, args, context=None):
        time.sleep(0.8)
        return {"total": 1}

    monkeypatch.setattr(chat_service, "_dispatch", _slow_dispatch)
    started = time.monotonic()
    out = chat_service._run_tool(db, "search_videos", {}, None)
    elapsed = time.monotonic() - started

    assert out == {"error": "该工具超过 30s 已跳过，请基于已有数据作答"}
    assert chat_service.TOOL_TIMEOUT_MESSAGE == "该工具超过 30s 已跳过，请基于已有数据作答"
    assert elapsed < 0.8, "超时后应立即返回可读跳过原因，而不是等工具跑完"


def test_run_tool_write_action_stays_on_main_thread(db, monkeypatch):
    seen: dict = {}

    def _fake_dispatch(session, name, args, context=None):
        seen["session"] = session
        seen["thread"] = threading.current_thread().name
        return {"status": "pending_confirmation"}

    monkeypatch.setattr(chat_service, "_dispatch", _fake_dispatch)
    out = chat_service._run_tool(db, "generate_draft", {"topic": "x"}, None)

    assert out["status"] == "pending_confirmation"
    assert seen["session"] is db
    assert seen["thread"] == threading.current_thread().name


# ---------- ④ model_health 自检并行 + 单探针超时 ----------


class _CountingProbeClient:
    """探针假客户端：记录并发峰值；`hang_when` 命中的 system 会睡到超时被记录。"""

    def __init__(self, slot: dict, state: dict, lock: threading.Lock, hang_when: str = ""):
        self.slot = slot
        self.state = state
        self.lock = lock
        self.hang_when = hang_when
        self.timeout_seconds: int | None = None

    def _call(self, messages):
        with self.lock:
            self.state["active"] += 1
            self.state["max"] = max(self.state["max"], self.state["active"])
        try:
            user = str(messages[1].get("content") or "")
            time.sleep(0.8 if self.hang_when and self.hang_when in user else 0.15)
        finally:
            with self.lock:
                self.state["active"] -= 1

    def chat(self, messages, **_kwargs):
        self._call(messages)
        return "正常"

    def chat_json(self, messages, **_kwargs):
        self._call(messages)
        return {"main_topics": ["面试"], "ok": True}


def _patch_probe_clients(monkeypatch, state: dict, lock: threading.Lock, hang_when: str = "") -> None:
    def _build(slot, timeout_seconds=None):
        return _CountingProbeClient(slot, state, lock, hang_when=hang_when)

    monkeypatch.setattr(model_health.llm_router, "build_client", _build)


def test_selfcheck_runs_probes_in_parallel_and_keeps_result_shape(db, monkeypatch):
    state = {"active": 0, "max": 0}
    lock = threading.Lock()
    _patch_probe_clients(monkeypatch, state, lock)

    started = time.monotonic()
    result = model_health.run_selfcheck(db, triggered_by="test")
    elapsed = time.monotonic() - started

    # 6 探针 × 0.15s：串行需 0.9s；并发 ≤3 约 0.3s
    assert elapsed < 0.7, f"自检应并行（6×0.15s 串行 0.9s），实际 {elapsed:.2f}s"
    assert 2 <= state["max"] <= model_health.SELFCHECK_CONCURRENCY, "并发数应 >1 且 ≤3"

    # 结果结构与旧实现一致
    assert set(result) == {"slots", "warnings", "checked_at", "triggered_by", "ok"}
    assert result["ok"] is True and result["warnings"] == []
    assert result["triggered_by"] == "test"
    assert len(result["checked_at"]) == 19  # "%Y-%m-%d %H:%M:%S"
    assert list(result["slots"]) == ["model1", "model2"]
    for name in ("model1", "model2"):
        per_slot = result["slots"][name]
        assert set(per_slot) == {"label", "probes", "ok"}
        assert per_slot["ok"] is True
        assert list(per_slot["probes"]) == [p["key"] for p in model_health.PROBES]
        for probe_key in per_slot["probes"]:
            outcome = per_slot["probes"][probe_key]
            assert set(outcome) == {"label", "ok", "reason", "seconds"}
            assert outcome["ok"] is True and outcome["reason"] == ""
    # 结果仍写 app_kv（设置页 GET /models 的 selfcheck 字段读它）
    assert model_health.last_result(db) == result


def test_selfcheck_probe_timeout_recorded_as_incompatible(db, monkeypatch):
    monkeypatch.setattr(model_health, "PROBE_TIMEOUT_SECONDS", 0.1)
    monkeypatch.setattr(model_health, "PROBE_FUTURE_GRACE_SECONDS", 0.1)
    state = {"active": 0, "max": 0}
    lock = threading.Lock()
    # 只让 json_basic 探针「卡住」：它的 user 消息是「输出 JSON。」（video_tags 的 system 也含 JSON 字样，别用 system 判）
    _patch_probe_clients(monkeypatch, state, lock, hang_when="输出 JSON。")

    result = model_health.run_selfcheck(db)

    assert result["ok"] is False
    assert len(result["warnings"]) == 2, "两个槽位的 json_basic 都应记不兼容"
    for name in ("model1", "model2"):
        per_slot = result["slots"][name]
        assert per_slot["ok"] is False
        stuck = per_slot["probes"]["json_basic"]
        assert stuck["ok"] is False
        assert "未返回" in stuck["reason"] and "跳过" in stuck["reason"]
        assert stuck["seconds"] >= 0.1, "超时要记录耗时"
        assert per_slot["probes"]["chat"]["ok"] is True
    assert any("在「JSON 输出能力」上不兼容" in w for w in result["warnings"])
    assert model_health.last_result(db)["ok"] is False
