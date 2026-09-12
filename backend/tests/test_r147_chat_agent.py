"""R-147：AI 对话升级为通用型 agent 的测试（P0 多步 / P1 只读 SQL / P2 写操作确认）。

三块各自的护栏：
- **P0**：回合/工具预算/墙钟到限时**返回答案而不是抛「未收敛」**；每步工具调用通过 `on_step` 抛出。
- **P1**：`sql_query` 只能查只读视图 —— 敏感表、多语句、写操作、注释绕过、子查询偷查原表全部拒绝；
  返回必须带 `row_count`/`truncated`（延续 R-146「不许把分页当总数」）。
- **P2**：写工具**只登记提案不执行**；确认后才执行、取消后不动数据；失败写 `failed` + 原因。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core import analytics_views
from app.db import Base
from app.models.agent_action import AgentAction
from app.models.draft import Draft
from app.models.prompt import AiPrompt
from app.services import agent_actions, chat_service
from app.services import prompt_service as ps
from app.services.chat_service import ChatService


@pytest.fixture()
def db(tmp_path):
    eng = create_engine(f"sqlite:///{tmp_path}/agent.db", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=eng)
    analytics_views.ensure_views(eng)  # sql_query 要查视图
    session = sessionmaker(bind=eng, autoflush=False, autocommit=False)()
    for key in ps.PROMPT_META:
        session.add(AiPrompt(key=key, version=1, content=ps.default_content(key), status="enabled", note="t"))
    session.commit()
    yield session
    session.close()
    eng.dispose()


# ---------- P1：只读 SQL 安全边界 ----------


def test_sql_query_allows_views(db):
    db.add(Draft(title="稿A", script="正文", source="ai", status="draft"))
    db.commit()
    out = chat_service._dispatch(db, "sql_query", {"sql": "SELECT status, COUNT(*) AS n FROM v_drafts GROUP BY status"})
    assert out["row_count"] == 1
    assert out["columns"] == ["status", "n"]
    assert out["rows"][0] == ["draft", "1"]
    assert out["truncated"] is False


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT * FROM app_kv",  # 明文模型 Key 所在表
        "SELECT content FROM ai_prompts",  # 提示词正文
        "SELECT * FROM chat_messages",
        "SELECT 1; DROP TABLE drafts",  # 多语句
        "DELETE FROM drafts",  # 写操作
        "UPDATE drafts SET status='used'",
        "PRAGMA table_info(drafts)",
        "ATTACH DATABASE '/tmp/x.db' AS x",
        "SELECT * FROM v_videos -- 注释绕过",
        "SELECT * FROM v_videos WHERE id IN (SELECT id FROM app_kv)",  # 子查询偷查原表
    ],
)
def test_sql_query_rejects_dangerous(db, sql):
    out = chat_service._dispatch(db, "sql_query", {"sql": sql})
    assert out.get("error"), f"应被拒绝：{sql}"
    assert out["row_count"] == 0


def test_sql_query_auto_limit_and_truncation(db):
    for i in range(5):
        db.add(Draft(title=f"稿{i}", script="正文", source="ai"))
    db.commit()
    out = chat_service._dispatch(db, "sql_query", {"sql": "SELECT id FROM v_drafts"})
    assert out["row_count"] == 5
    assert "LIMIT" in out["sql"].upper(), "未写 LIMIT 时应自动补"


def test_schema_card_lists_views_and_columns(db):
    from app.core.analytics_views import schema_card

    card = schema_card(db.get_bind())
    for view in ("v_videos", "v_drafts", "v_metrics"):
        assert view in card
    assert "status" in card and "planned=待发布" in card


def test_views_exclude_sensitive_tables():
    """视图定义里绝不能出现敏感/内部表。"""
    joined = " ".join(analytics_views.VIEWS.values()).lower()
    for forbidden in ("app_kv", "ai_prompts", "chat_messages", "schema_migrations", "background_tasks"):
        assert forbidden not in joined, f"视图不应引用 {forbidden}"
    assert "v_videos" in analytics_views.allowed_views()


# ---------- P2：写操作只提议、确认后才执行 ----------


def test_write_tool_only_proposes(db):
    """问「帮我生成」→ 只登记提案，**不建草稿**。"""
    before = db.query(Draft).count()
    out = chat_service._dispatch(db, "generate_draft", {"topic": "面试技巧"})
    assert out["status"] == "pending_confirmation"
    assert out["action_id"]
    assert db.query(Draft).count() == before, "确认前不应有任何数据被写入"
    row = db.get(AgentAction, out["action_id"])
    assert row is not None and row.status == "pending"
    assert "面试技巧" in row.preview


def test_cancel_does_not_touch_data(db):
    draft = Draft(title="稿A", script="正文", source="ai", status="draft")
    db.add(draft)
    db.commit()
    out = chat_service._dispatch(db, "set_draft_status", {"draft_id": draft.id, "status": "deleted"})
    row = agent_actions.cancel(db, out["action_id"])
    assert row.status == "cancelled"
    assert db.get(Draft, draft.id).status == "draft", "取消后数据不变"
    assert db.query(AgentAction).filter(AgentAction.status == "pending").count() == 0


def test_set_draft_status_executes_on_confirm(db):
    draft = Draft(title="稿A", script="正文", source="ai", status="draft")
    db.add(draft)
    db.commit()
    out = chat_service._dispatch(db, "set_draft_status", {"draft_id": draft.id, "status": "used"})
    assert db.get(Draft, draft.id).status == "draft", "确认前不改"
    row = agent_actions.confirm(db, out["action_id"])
    assert row.status == "done"
    assert db.get(Draft, draft.id).status == "used"
    assert "已标记" in row.result


def test_generate_draft_confirm_enqueues_task(db):
    out = chat_service._dispatch(db, "generate_draft", {"topic": "面试开场"})
    row = agent_actions.confirm(db, out["action_id"])
    assert row.status == "done"
    assert row.task_id, "确认后应入队后台任务"
    # 占位草稿已建立（讨论任务随后会填内容）
    assert db.query(Draft).count() == 1


def test_confirm_twice_rejected(db):
    out = chat_service._dispatch(db, "generate_draft", {"topic": "x"})
    agent_actions.confirm(db, out["action_id"])
    with pytest.raises(agent_actions.AgentActionError, match="不能重复确认"):
        agent_actions.confirm(db, out["action_id"])


def test_proposal_rejects_missing_draft(db):
    """提案阶段就校验：草稿不存在 → 直接返回 error，不登记无效提案。"""
    out = chat_service._dispatch(db, "set_draft_status", {"draft_id": 0, "status": "used"})
    assert out.get("error")
    assert db.query(AgentAction).count() == 0


def test_confirm_failure_is_recorded(db):
    """确认后执行失败 → 提案写 failed + 可读原因（不抛给前端，让作者看到状态）。"""
    draft = Draft(title="稿A", script="正文", source="ai", status="draft")
    db.add(draft)
    db.commit()
    out = chat_service._dispatch(db, "set_draft_status", {"draft_id": draft.id, "status": "used"})
    db.delete(draft)   # 确认前草稿被删掉 → 执行必然失败
    db.commit()
    row = agent_actions.confirm(db, out["action_id"])
    assert row.status == "failed"
    assert "不存在" in row.error


def test_unknown_action_rejected(db):
    out = chat_service._dispatch(db, "drop_everything", {})
    assert "未知工具" in out["error"]


def test_action_payload_and_preview_are_recorded(db):
    draft = Draft(title="稿B", script="正文", source="ai", status="draft")
    db.add(draft)
    db.commit()
    out = chat_service._dispatch(db, "set_draft_status", {"draft_id": draft.id, "status": "archived"})
    row = db.get(AgentAction, out["action_id"])
    assert json.loads(row.payload)["status"] == "archived"
    assert "不采用" in row.preview
    assert agent_actions.to_dict(row)["label"] == "修改草稿状态"


# ---------- P0：多步与到限收尾 ----------


class _ScriptedLLM:
    """按脚本依次返回 tool_calls / 最终答案，用来模拟多轮 agent。"""

    def __init__(self, rounds: int):
        self.rounds = rounds
        self.calls = 0

    def chat_completion(self, messages, **kw):
        self.calls += 1
        # 没给 tools 的收尾调用必须直接作答（真实模型也拿不到工具）
        if kw.get("tools") and self.calls <= self.rounds:
            return {
                "content": "",
                "tool_calls": [
                    {
                        "id": f"c{self.calls}",
                        "function": {"name": "search_videos", "arguments": "{}"},
                    }
                ],
            }
        return {"content": f"最终答案（第 {self.calls} 次调用）"}


def test_agent_steps_are_emitted(db, monkeypatch):
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "agent_max_rounds", 5, raising=False)
    steps: list[dict] = []
    service = ChatService(llm=_ScriptedLLM(rounds=2), db=db)
    reply = service.reply(db, "素材库有多少条", [], conversation_id=None, on_step=steps.append)
    assert "最终答案" in reply
    kinds = [s["kind"] for s in steps]
    assert kinds == ["tool", "result", "tool", "result"], "每步工具调用与结果都应抛出"
    assert all(s["name"] == "search_videos" for s in steps)
    assert steps[1]["summary"].startswith("共 "), "结果摘要要说清条数"


def test_round_limit_wraps_up_instead_of_raising(db, monkeypatch):
    """到回合上限时**返回答案**（带着已有数据收尾），不再抛「未收敛」。"""
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "agent_max_rounds", 2, raising=False)
    steps: list[dict] = []
    reply = ChatService(llm=_ScriptedLLM(rounds=99), db=db).reply(db, "随便问问", [], on_step=steps.append)
    assert "最终答案" in reply, "到限也必须有答案"
    tools = [s for s in steps if s["kind"] == "tool"]
    assert len(tools) == 2, f"最多 2 轮工具，实际 {len(tools)}"


def test_tool_call_budget_wraps_up(db, monkeypatch):
    """工具调用总次数到上限也要收尾作答，而不是一直查下去。"""
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "agent_max_rounds", 9, raising=False)
    monkeypatch.setattr(get_settings(), "agent_max_tool_calls", 2, raising=False)
    steps: list[dict] = []
    reply = ChatService(llm=_ScriptedLLM(rounds=99), db=db).reply(db, "随便问问", [], on_step=steps.append)
    assert "最终答案" in reply
    assert len([s for s in steps if s["kind"] == "tool"]) == 2, "工具调用数不得超过预算"


def test_system_message_includes_schema_and_rules(db):
    from app.services.chat_service import TOOL_DATA_RULES

    seen: list[dict] = []

    class _Capture:
        def chat_completion(self, messages, **_kw):
            seen.extend(messages)
            return {"content": "好的"}

    ChatService(llm=_Capture(), db=db).reply(db, "hi", [])
    system = seen[0]["content"]
    assert TOOL_DATA_RULES.strip() in system
    assert "v_videos" in system, "必须把只读视图 schema 告诉模型，否则写不出对的 SQL"
    assert "只会生成**待作者确认的提案**" in system
