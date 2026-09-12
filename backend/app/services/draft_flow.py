"""草稿生成/回炉的入队流程（R-147）。

抽出来的原因：AI 对话的 agent 写操作（确认后）与 `api/drafts.py` 的「AI 生成」按钮
需要**完全一样**的入队逻辑（建占位草稿 → 入队双模型讨论 → 失败清理占位稿），
以前只写在 API 层，agent 复用不了。这里做成服务层，两边共用。
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from ..models.draft import Draft
from ..services.creator_service import current_creator_id
from ..tasks import start_task
from .debate import PLACEHOLDER_SCRIPT, clear_debate_state, run_debate_draft


def debate_task(db: Session, payload: dict) -> dict:
    """后台任务体：跑双模型讨论；失败时清进度与占位稿（R-134），再抛出。"""
    try:
        return run_debate_draft(db, payload)
    except Exception:
        try:
            clear_debate_state(db, int(payload.get("draft_id") or 0))
        except Exception:  # noqa: BLE001 清理失败不能掩盖原始错误
            db.rollback()
        raise


def create_placeholder_draft(db: Session, topic: str) -> Draft:
    """建一篇占位草稿（讨论结束后会被填上真实内容）。"""
    from .persona_profile import current_persona_version

    cid = current_creator_id(db)
    draft = Draft(
        title=topic,
        cover_text="",
        script=PLACEHOLDER_SCRIPT,
        source="ai",
        creator_id=cid,  # 归属当前主博主，否则工作台看不到
        persona_version=current_persona_version(db, cid),
    )
    db.add(draft)
    db.commit()
    db.refresh(draft)
    return draft


def start_generation(db: Session, topic: str) -> tuple[int, int]:
    """建占位稿 + 入队双模型讨论；返回 (task_id, draft_id)。"""
    draft = create_placeholder_draft(db, topic)
    task_id = start_task("generate_draft", {"draft_id": draft.id, "topic": topic}, debate_task)
    return task_id, draft.id


def start_rework(db: Session, draft_id: int) -> int:
    """在**同一篇草稿**上重跑双模型讨论（回炉）：保留 id 与反馈/讨论留痕。返回 task_id。"""
    draft = db.get(Draft, draft_id)
    if draft is None:
        raise ValueError("草稿不存在")
    topic = (draft.title or "").strip() or "重新生成一条口播脚本"
    return start_task("generate_draft", {"draft_id": draft.id, "topic": topic}, debate_task)


__all__ = ["create_placeholder_draft", "debate_task", "start_generation", "start_rework"]
