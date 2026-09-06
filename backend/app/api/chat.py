"""AI 对话接口：多会话管理 + SSE 流式（R-017）。

权限边界保留：写操作（生成/修改/删除）由 ChatService 内部校验作者明确同意。
"""

from __future__ import annotations

import json
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
from ..services.chat_service import ChatService

router = APIRouter()


def _last_history(db: Session, conversation_id: int | None, limit: int = 40) -> list[dict]:
    q = db.query(ChatMessage)
    if conversation_id is not None:
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
    history = _last_history(db, None)
    service = ChatService()
    reply = service.reply(db, user_msg, history)
    db.add(ChatMessage(role="user", content=user_msg))
    db.add(ChatMessage(role="assistant", content=reply))
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
        db = SessionLocal()
        try:
            conversation_id = payload.conversation_id
            if conversation_id is not None and db.get(ChatConversation, conversation_id) is None:
                yield f"event: error\ndata: {json.dumps({'message': '会话不存在'}, ensure_ascii=False)}\n\n"
                return
            history = _last_history(db, conversation_id)
            db.add(
                ChatMessage(conversation_id=conversation_id, role="user", content=user_msg)
            )
            db.commit()

            reply = ChatService().reply(db, user_msg, history)
            msg = ChatMessage(conversation_id=conversation_id, role="assistant", content=reply)
            db.add(msg)
            db.commit()
            db.refresh(msg)
            if conversation_id is not None:
                conv = db.get(ChatConversation, conversation_id)
                if conv:
                    conv.updated_at = _app_now()
                    db.commit()

            yield f"event: start\ndata: {json.dumps({'message_id': msg.id}, ensure_ascii=False)}\n\n"
            step = 12
            for i in range(0, len(reply), step):
                chunk = reply[i : i + step]
                yield f"data: {json.dumps({'delta': chunk}, ensure_ascii=False)}\n\n"
                time.sleep(0.015)
            yield f"event: done\ndata: {json.dumps({'done': True, 'message_id': msg.id}, ensure_ascii=False)}\n\n"
        except Exception as exc:  # noqa: BLE001
            yield f"event: error\ndata: {json.dumps({'message': str(exc)}, ensure_ascii=False)}\n\n"
        finally:
            db.close()

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
