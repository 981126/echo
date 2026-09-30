"""agent 写操作提案与执行（R-147 P2）。

**为什么不让模型直接写**：写操作一旦由模型直接执行，就没有"作者同意"的硬保证
（提示词约束是可以被绕过的），也没有审计。所以：
- 模型的写工具只调用 `propose()` 落一条 `pending` 提案（带**影响范围预览**）；
- 作者在对话里点「确认执行」→ `confirm()` → 服务端执行 → 写 `done` + 结果，或 `failed` + 原因；
- 点「取消」→ `cancelled`，不动任何数据。

可执行的动作（都复用既有服务，不新增数据操作方式）：
- `generate_draft`：建占位稿 + 入队双模型讨论（`services/draft_flow.start_generation`）
- `rework_draft`：在同一篇草稿上重跑讨论（`start_rework`）
- `set_draft_status`：立即改草稿状态（采用/不采用/删除＝软删）
"""

from __future__ import annotations

import json

from sqlalchemy.orm import Session

from ..core.log import get_logger
from ..core.timeutil import now as _app_now
from ..models.agent_action import AgentAction
from ..models.draft import Draft

log = get_logger("agent_actions")

# 动作名 → 中文标签（前端卡片标题）
ACTION_LABELS: dict[str, str] = {
    "generate_draft": "生成脚本草稿",
    "rework_draft": "回炉重写这篇稿子",
    "set_draft_status": "修改草稿状态",
}

DRAFT_STATUS_LABELS = {"draft": "草稿", "used": "待制作（采用）", "archived": "不采用", "deleted": "删除"}
WRITABLE_STATUSES = tuple(DRAFT_STATUS_LABELS)

# R-208：安全写操作白名单——免确认直接执行（审计照记 done），危险操作仍需作者确认。
SAFE_ACTIONS = frozenset({"generate_draft", "rework_draft"})
# set_draft_status 里这些可逆状态算安全；deleted（软删）仍需确认
_SAFE_STATUSES = frozenset({"draft", "used", "archived"})


def is_safe_action(action: str, payload: dict) -> bool:
    """该写操作是否免确认自动执行（R-208）。"""
    if action in SAFE_ACTIONS:
        return True
    if action == "set_draft_status" and str(payload.get("status") or "") in _SAFE_STATUSES:
        return True
    return False


class AgentActionError(ValueError):
    """提案/执行非法：API 转 400，带可读原因。"""


def _draft_label(db: Session, draft_id: int) -> str:
    draft = db.get(Draft, draft_id)
    if draft is None:
        raise AgentActionError(f"草稿 {draft_id} 不存在")
    return (draft.title or f"#{draft.id}")[:40]


def build_preview(db: Session, action: str, payload: dict) -> str:
    """给作者看的「影响范围预览」—— 确认前必须能看懂这一步会做什么。"""
    if action == "generate_draft":
        topic = str(payload.get("topic") or "").strip()
        if not topic:
            raise AgentActionError("生成草稿需要 topic")
        return f"用「生成方 × 评审方」双模型讨论生成一篇关于《{topic[:40]}》的脚本草稿（约 3–5 分钟，完成后通知你）"
    if action == "rework_draft":
        did = int(payload.get("draft_id") or 0)
        return f"把草稿《{_draft_label(db, did)}》按原选题重新跑一遍双模型讨论（保留该稿的反馈与讨论留痕）"
    if action == "set_draft_status":
        did = int(payload.get("draft_id") or 0)
        status = str(payload.get("status") or "")
        if status not in WRITABLE_STATUSES:
            raise AgentActionError(f"状态只能是：{'、'.join(WRITABLE_STATUSES)}")
        tail = "（软删：数据仍在库里，可在工作台恢复）" if status == "deleted" else ""
        return f"把草稿《{_draft_label(db, did)}》标记为「{DRAFT_STATUS_LABELS[status]}」{tail}"
    raise AgentActionError(f"不支持的动作：{action}")


def propose(
    db: Session,
    *,
    action: str,
    payload: dict,
    conversation_id: int | None = None,
    message_id: int | None = None,
) -> AgentAction:
    """登记一条写操作。

    R-208：安全操作（generate_draft / rework_draft / 可逆的 set_draft_status）**免确认直接执行**，
    审计照记（status=done + result）；危险操作（删除等）仍落 `pending` 等作者确认。
    """
    if action not in ACTION_LABELS:
        raise AgentActionError(f"不支持的动作：{action}")
    preview = build_preview(db, action, payload)
    row = AgentAction(
        conversation_id=conversation_id,
        message_id=message_id,
        action=action,
        payload=json.dumps(payload, ensure_ascii=False),
        preview=preview,
        status="pending",
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    if is_safe_action(action, payload):
        log.info("安全操作自动执行 #%s：%s（%s）", row.id, action, preview[:60])
        return _auto_execute(db, row)
    log.info("登记待确认的 agent 操作 #%s：%s（%s）", row.id, action, preview[:60])
    return row


def _auto_execute(db: Session, row: AgentAction) -> AgentAction:
    """免确认执行：成功写 done、失败写 failed（审计照记，不抛给上层）。"""
    payload = json.loads(row.payload or "{}")
    try:
        task_id, result = _execute(db, row, payload)
    except Exception as exc:  # noqa: BLE001 失败留痕给作者看
        db.rollback()
        fresh = get(db, row.id)
        if fresh is not None:
            fresh.status = "failed"
            fresh.error = f"{type(exc).__name__}: {str(exc)[:300]}"
            fresh.decided_at = _app_now()
            db.commit()
            db.refresh(fresh)
        log.exception("安全操作自动执行失败 #%s", row.id)
        return fresh  # type: ignore[return-value]
    row.status = "done"
    row.result = result
    row.task_id = task_id
    row.decided_at = _app_now()
    db.commit()
    db.refresh(row)
    return row


def get(db: Session, action_id: int) -> AgentAction | None:
    return db.get(AgentAction, action_id)


def list_actions(db: Session, conversation_id: int | None = None, status: str = "") -> list[AgentAction]:
    q = db.query(AgentAction)
    if conversation_id is not None:
        q = q.filter(AgentAction.conversation_id == conversation_id)
    if status:
        q = q.filter(AgentAction.status == status)
    return q.order_by(AgentAction.id.desc()).limit(100).all()


def to_dict(row: AgentAction) -> dict:
    return {
        "id": row.id,
        "conversation_id": row.conversation_id,
        "message_id": row.message_id,
        "action": row.action,
        "label": ACTION_LABELS.get(row.action, row.action),
        "payload": json.loads(row.payload or "{}"),
        "preview": row.preview,
        "status": row.status,
        "result": row.result,
        "error": row.error,
        "task_id": row.task_id,
        "created_at": str(row.created_at),
        "decided_at": str(row.decided_at) if row.decided_at else "",
    }


def cancel(db: Session, action_id: int) -> AgentAction:
    row = get(db, action_id)
    if row is None:
        raise AgentActionError("该操作不存在")
    if row.status != "pending":
        raise AgentActionError(f"该操作已经是「{row.status}」，无法取消")
    row.status = "cancelled"
    row.decided_at = _app_now()
    db.commit()
    db.refresh(row)
    return row


def _execute(db: Session, row: AgentAction, payload: dict) -> tuple[int | None, str]:
    """真正执行；返回 (task_id, 结果说明)。"""
    from . import draft_flow

    if row.action == "generate_draft":
        task_id, draft_id = draft_flow.start_generation(db, str(payload.get("topic") or ""))
        return task_id, f"已开始生成（任务 #{task_id}），完成后会通知你；草稿 id={draft_id}"
    if row.action == "rework_draft":
        task_id = draft_flow.start_rework(db, int(payload.get("draft_id") or 0))
        return task_id, f"已开始回炉（任务 #{task_id}），完成后会通知你"
    if row.action == "set_draft_status":
        draft = db.get(Draft, int(payload.get("draft_id") or 0))
        if draft is None:
            raise AgentActionError("草稿不存在")
        status = str(payload.get("status") or "")
        draft.status = status
        db.commit()
        return None, f"草稿 #{draft.id} 已标记为「{DRAFT_STATUS_LABELS.get(status, status)}」"
    raise AgentActionError(f"不支持的动作：{row.action}")


def confirm(db: Session, action_id: int) -> AgentAction:
    """作者确认后执行。失败写 failed + 可读原因（不抛给上层，让前端能看到状态）。"""
    row = get(db, action_id)
    if row is None:
        raise AgentActionError("该操作不存在")
    if row.status != "pending":
        raise AgentActionError(f"该操作已经是「{row.status}」，不能重复确认")
    payload = json.loads(row.payload or "{}")
    try:
        task_id, result = _execute(db, row, payload)
    except Exception as exc:  # noqa: BLE001 执行失败要留痕给作者看
        db.rollback()
        row = get(db, action_id)
        if row is not None:
            row.status = "failed"
            row.error = f"{type(exc).__name__}: {str(exc)[:300]}"
            row.decided_at = _app_now()
            db.commit()
            db.refresh(row)
        log.exception("agent 操作 #%s 执行失败", action_id)
        return row  # type: ignore[return-value]
    row.status = "done"
    row.result = result
    row.task_id = task_id
    row.decided_at = _app_now()
    db.commit()
    db.refresh(row)
    log.info("agent 操作 #%s 已执行：%s", row.id, result)
    return row


__all__ = [
    "ACTION_LABELS",
    "DRAFT_STATUS_LABELS",
    "WRITABLE_STATUSES",
    "SAFE_ACTIONS",
    "AgentActionError",
    "build_preview",
    "cancel",
    "confirm",
    "get",
    "is_safe_action",
    "list_actions",
    "propose",
    "to_dict",
]
