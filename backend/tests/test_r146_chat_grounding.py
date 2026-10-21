"""R-146：AI 对话「瞎回复」修复的回归测试。

**背景（实测复现）**：问「素材库一共有多少条视频」答 *50*（真值 292）、问「一共多少篇草稿」答 *10*（真值 22）。
根因：`search_videos` / `search_drafts` 只返回**截断后的列表且不带总数**（默认取 10、封顶 50），
模型无从知道自己在看一页，就把取回条数当成了总数。`get_metrics_summary.top_videos` 同类。

本文件锁住：
1. 分页类工具必须返回 `total / returned / truncated`，且 `total` 是**筛选后的真实总数**；
2. 所有分页入口都暴露 `total`（契约测试，防以后新加工具又漏）；
3. 系统消息里含**程序固定**的「工具数据使用规则」，且与 `ai_prompts` 内容无关；
4. 遗留非流式接口不再跨会话混历史。
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest
from conftest import ensure_schema, fresh_engine
from sqlalchemy.orm import sessionmaker

from app.api.chat import _last_history
from app.models.chat import ChatConversation, ChatMessage
from app.models.draft import Draft
from app.models.video import Video
from app.services import chat_service
from app.services.chat_service import ChatService


@pytest.fixture()
def db(tmp_path):
    eng = fresh_engine()
    ensure_schema(eng)
    session = sessionmaker(bind=eng, autoflush=False, autocommit=False)()
    yield session
    session.close()


def _videos(db, n: int, *, platform: str = "douyin", status: str = "published", tag: str = "") -> None:
    """插入 n 条素材。filename 全库唯一，用 tag 区分不同批次。"""
    for i in range(n):
        db.add(
            Video(
                filename=f"v{tag}{i}.mp4",
                title=f"素材{i}",
                platforms=f'["{platform}"]' if i % 2 == 0 else '["bilibili"]',
                status=status,
                main_topics='["面试"]',
                platform_post_id=f"post{tag}{i}",
            )
        )
    db.commit()


# ---------- 核心：total 才是总数 ----------


def test_search_videos_reports_total_not_page_size(db):
    """25 条素材、默认取 10 条时：total 必须是 25（而不是 10）。"""
    _videos(db, 25)
    out = chat_service._dispatch(db, "search_videos", {})
    assert out["total"] == 25, "total 必须是真实总数，不是这一页的条数"
    assert out["returned"] == 10
    assert out["truncated"] is True
    assert len(out["videos"]) == 10


def test_search_videos_total_respects_filters(db):
    """total 要跟筛选条件一致，不能是全库条数。"""
    _videos(db, 12, platform="douyin", tag="a")
    _videos(db, 8, platform="xiaohongshu", tag="b")
    out = chat_service._dispatch(db, "search_videos", {"platform": "xiaohongshu", "limit": 50})
    assert out["total"] == 4, "只统计 platforms 含 xiaohongshu 的（偶数下标的一半）"
    assert out["truncated"] is False


def test_search_videos_not_truncated_when_limit_covers_all(db):
    _videos(db, 3)
    out = chat_service._dispatch(db, "search_videos", {"limit": 50})
    assert out["total"] == out["returned"] == 3
    assert out["truncated"] is False


def test_search_videos_limit_is_clamped(db):
    _videos(db, 60)
    out = chat_service._dispatch(db, "search_videos", {"limit": 9999})
    assert out["returned"] == 50, "单次取回仍封顶 50（成本考虑），但 total 必须给全"
    assert out["total"] == 60


def test_search_drafts_reports_total(db):
    for i in range(14):
        db.add(Draft(title=f"稿{i}", script="正文", source="ai", status="draft" if i % 2 == 0 else "archived"))
    db.commit()
    out = chat_service._dispatch(db, "search_drafts", {})
    assert out["total"] == 14
    assert out["returned"] == 10
    assert out["truncated"] is True
    only_draft = chat_service._dispatch(db, "search_drafts", {"status": "draft"})
    assert only_draft["total"] == 7, "筛选 status 后 total 要跟着变"


def test_metrics_summary_exposes_video_total(db):
    """video_total = **有数据的**视频数（指标汇总只看库里真有指标记录的），top_videos 只是前 10 条。"""
    _videos(db, 4)
    out = chat_service._dispatch(db, "get_metrics_summary", {})
    assert "video_total" in out, "必须告诉模型总数，否则又会把 top_videos 的长度当总数"
    assert out["video_total"] == 0, "这 4 条还没有指标记录 → 有数据的为 0"
    assert "video_total" in out["top_videos_note"]
    assert len(out["top_videos"]) <= 10


def test_every_paginated_tool_exposes_total(db):
    """契约测试：分页类工具都必须暴露 total（以后新加工具漏了就红）。"""
    _videos(db, 12)
    for i in range(12):
        db.add(Draft(title=f"稿{i}", script="正文", source="ai"))
    db.commit()
    for name, args in (
        ("search_videos", {}),
        ("search_drafts", {}),
        ("get_metrics_summary", {}),
    ):
        out = chat_service._dispatch(db, name, args)
        assert "total" in out or "video_total" in out, f"{name} 必须告诉模型总数"


# ---------- 程序固定的数据使用规则 ----------


class _CapturingLLM:
    def __init__(self):
        self.messages: list[dict] = []

    def chat_completion(self, messages, **_kw):
        self.messages = messages
        return {"content": "好的"}


def test_system_message_carries_fixed_data_rules(db):
    """规则由程序追加（与 ai_prompts 内容无关），优化改动不了它。"""
    llm = _CapturingLLM()
    service = ChatService(llm=llm, db=db)
    assert service.reply(db, "素材库有多少条", []) == "好的"
    system = llm.messages[0]
    assert system["role"] == "system"
    assert chat_service.TOOL_DATA_RULES.strip() in system["content"]
    assert "绝不能把列表长度当成总数" in system["content"]
    assert "不要编造" in system["content"]


def test_data_rules_are_not_part_of_optimizable_prompt(db):
    """规则不落在 ai_prompts 里 —— 保证「提示词优化」不会把它改坏。"""
    from app.models.prompt import AiPrompt

    content = chat_service.TOOL_DATA_RULES
    for row in db.query(AiPrompt).all():
        assert content not in (row.content or "")


def test_contract_note_tells_optimizer_not_to_duplicate():
    from app.services import prompt_contract

    note = prompt_contract.context_note_for("chat")
    assert "工具数据使用规则" in note


# ---------- 会话历史不再串味 ----------


def test_legacy_history_is_scoped_to_null_conversation(db):
    # PG 会校验 chat_messages.conversation_id 外键：会话行必须先存在
    db.add(ChatConversation(id=7, title="别的会话"))
    db.commit()
    db.add(ChatMessage(conversation_id=None, role="user", content="遗留线程问"))
    db.add(ChatMessage(conversation_id=None, role="assistant", content="遗留线程答"))
    db.add(ChatMessage(conversation_id=7, role="user", content="别的会话问"))
    db.add(ChatMessage(conversation_id=7, role="assistant", content="别的会话答"))
    db.commit()
    legacy = _last_history(db, None)
    assert [m["content"] for m in legacy] == ["遗留线程问", "遗留线程答"]
    conv7 = _last_history(db, 7)
    assert [m["content"] for m in conv7] == ["别的会话问", "别的会话答"]


def test_history_is_chronological(db):
    db.add(ChatConversation(id=1, title="会话1"))
    db.commit()
    for i in range(4):
        db.add(ChatMessage(conversation_id=1, role="user" if i % 2 == 0 else "assistant", content=f"m{i}"))
    db.commit()
    assert [m["content"] for m in _last_history(db, 1)] == ["m0", "m1", "m2", "m3"]
