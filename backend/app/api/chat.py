"""AI 对话接口：多会话管理 + SSE 流式（R-017）。

权限边界保留：写操作（生成/修改/删除）由 ChatService 内部校验作者明确同意。
"""

from __future__ import annotations

import json
import queue
import threading
import time

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from ..db import SessionLocal, get_db
from ..core.timeutil import now as _app_now
from ..models.chat import ChatConversation, ChatMessage
from ..schemas.chat import (
    ChatIn,
    ChatMessageOut,
    ChatOut,
    ChatStreamIn,
    ConversationCreate,
    ConversationOut,
    ConversationUpdate,
)
from ..services import agent_actions
from ..services.chat_service import ChatService

router = APIRouter()


@router.get("/actions", response_model=list[dict])
def list_agent_actions(
    conversation_id: int | None = None,
    status: str = "",
    db: Session = Depends(get_db),
):
    """列出 agent 写操作提案（R-147 P2）：前端刷新后仍能渲染待确认卡片。"""
    return [agent_actions.to_dict(r) for r in agent_actions.list_actions(db, conversation_id, status)]


@router.post("/actions/{action_id}/confirm", response_model=dict)
def confirm_agent_action(action_id: int, db: Session = Depends(get_db)):
    """作者确认后才真正执行写操作（生成/回炉/改状态）。"""
    try:
        return agent_actions.to_dict(agent_actions.confirm(db, action_id))
    except agent_actions.AgentActionError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/actions/{action_id}/cancel", response_model=dict)
def cancel_agent_action(action_id: int, db: Session = Depends(get_db)):
    """取消待确认的写操作：不动任何数据。"""
    try:
        return agent_actions.to_dict(agent_actions.cancel(db, action_id))
    except agent_actions.AgentActionError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def _last_history(db: Session, conversation_id: int | None, limit: int = 40) -> list[dict]:
    """取某会话最近 N 条历史（时间正序）。

    R-146：`conversation_id=None` 是**遗留单线程**（不带会话的旧接口），
    以前不过滤 → 会把所有会话的历史混在一起喂给模型（答非所问）。
    现在显式限定 `conversation_id IS NULL`。
    """
    q = db.query(ChatMessage)
    if conversation_id is None:
        q = q.filter(ChatMessage.conversation_id.is_(None))
    else:
        q = q.filter(ChatMessage.conversation_id == conversation_id)
    rows = q.order_by(ChatMessage.id.desc()).limit(limit).all()
    return [{"role": m.role, "content": m.content} for m in reversed(rows)]


# ---------- 会话管理 ----------


@router.get("/conversations", response_model=list[ConversationOut])
def list_conversations(db: Session = Depends(get_db)):
    return (
        db.query(ChatConversation)
        .order_by(ChatConversation.updated_at.desc(), ChatConversation.id.desc())
        .all()
    )


@router.post("/conversations", response_model=ConversationOut)
def create_conversation(payload: ConversationCreate, db: Session = Depends(get_db)):
    conv = ChatConversation(title=(payload.title or "新对话").strip() or "新对话")
    db.add(conv)
    db.commit()
    db.refresh(conv)
    return conv


@router.patch("/conversations/{conv_id}", response_model=ConversationOut)
def rename_conversation(conv_id: int, payload: ConversationUpdate, db: Session = Depends(get_db)):
    conv = db.get(ChatConversation, conv_id)
    if conv is None:
        raise HTTPException(status_code=404, detail="会话不存在")
    conv.title = (payload.title or "").strip() or "新对话"
    db.commit()
    db.refresh(conv)
    return conv


@router.delete("/conversations/{conv_id}", response_model=dict)
def delete_conversation(conv_id: int, db: Session = Depends(get_db)):
    conv = db.get(ChatConversation, conv_id)
    if conv is None:
        raise HTTPException(status_code=404, detail="会话不存在")
    db.query(ChatMessage).filter(ChatMessage.conversation_id == conv_id).delete()
    db.delete(conv)
    db.commit()
    return {"ok": True}


# ---------- 历史与问答 ----------


@router.get("/history", response_model=list[ChatMessageOut])
def chat_history(
    conversation_id: int | None = None,
    limit: int = 200,
    db: Session = Depends(get_db),
):
    q = db.query(ChatMessage)
    if conversation_id is not None:
        q = q.filter(ChatMessage.conversation_id == conversation_id)
    return q.order_by(ChatMessage.id.desc()).limit(limit).all()[::-1]


@router.post("", response_model=ChatOut)
def chat(payload: ChatIn, db: Session = Depends(get_db)):
    """非流式问答（兼容旧调用）。"""
    user_msg = payload.message.strip()
    conv_id = getattr(payload, "conversation_id", None)
    history = _last_history(db, conv_id)
    service = ChatService(db=db)
    reply = service.reply(db, user_msg, history, conversation_id=conv_id)
    db.add(ChatMessage(conversation_id=conv_id, role="user", content=user_msg))
    db.add(ChatMessage(conversation_id=conv_id, role="assistant", content=reply))
    db.commit()
    last = db.query(ChatMessage).order_by(ChatMessage.id.desc()).first()
    return {"reply": reply, "message_id": last.id if last else 0}


@router.post("/stream")
def chat_stream(payload: ChatStreamIn):
    """SSE 流式问答：先按非流式求解（含工具调用），再逐段下发结果（打字机式流式）。"""
    user_msg = payload.message.strip()
    if not user_msg:
        raise HTTPException(status_code=400, detail="消息不能为空")

    def gen():
        """R-147 P0：agent 在后台线程里跑，每步工具调用实时下发（event: step），
        最后把整段回答按打字机节奏发出去。"""
        out: queue.Queue = queue.Queue()

        def worker() -> None:
            db = SessionLocal()
            try:
                conversation_id = payload.conversation_id
                if conversation_id is not None and db.get(ChatConversation, conversation_id) is None:
                    out.put(("error", "会话不存在"))
                    return
                history = _last_history(db, conversation_id)
                db.add(ChatMessage(conversation_id=conversation_id, role="user", content=user_msg))
                db.commit()

                def on_step(step: dict) -> None:
                    out.put(("step", step))

                reply = ChatService(db=db).reply(
                    db, user_msg, history, conversation_id=conversation_id, on_step=on_step, mode=payload.mode
                )
                msg = ChatMessage(conversation_id=conversation_id, role="assistant", content=reply)
                db.add(msg)
                db.commit()
                db.refresh(msg)
                if conversation_id is not None:
                    conv = db.get(ChatConversation, conversation_id)
                    if conv:
                        conv.updated_at = _app_now()
                        db.commit()
                out.put(("reply", (reply, msg.id)))
            except Exception as exc:  # noqa: BLE001 统一转成 error 事件
                out.put(("error", str(exc)))
            finally:
                db.close()
                out.put(("end", None))

        threading.Thread(target=worker, daemon=True).start()

        reply_text = ""
        message_id = 0
        while True:
            kind, data = out.get()
            if kind == "end":
                break
            if kind == "step":
                yield f"event: step\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"
            elif kind == "error":
                yield f"event: error\ndata: {json.dumps({'message': data}, ensure_ascii=False)}\n\n"
                return
            elif kind == "reply":
                reply_text, message_id = data
        if not reply_text:
            yield f"event: error\ndata: {json.dumps({'message': '没有拿到回答'}, ensure_ascii=False)}\n\n"
            return
        yield f"event: start\ndata: {json.dumps({'message_id': message_id}, ensure_ascii=False)}\n\n"
        step = 12
        for i in range(0, len(reply_text), step):
            chunk = reply_text[i : i + step]
            yield f"data: {json.dumps({'delta': chunk}, ensure_ascii=False)}\n\n"
            time.sleep(0.015)
        yield f"event: done\ndata: {json.dumps({'done': True, 'message_id': message_id}, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
