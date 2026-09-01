"""AI 对话接口：只读问答；写操作不在此执行（权限边界）。"""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..db import get_db
from ..models.chat import ChatMessage
from ..schemas.chat import ChatIn, ChatMessageOut, ChatOut
from ..services.chat_service import ChatService

router = APIRouter()


@router.get("/history", response_model=list[ChatMessageOut])
def chat_history(limit: int = 50, db: Session = Depends(get_db)):
    return db.query(ChatMessage).order_by(ChatMessage.id.desc()).limit(limit).all()[::-1]


@router.post("", response_model=ChatOut)
def chat(payload: ChatIn, db: Session = Depends(get_db)):
    user_msg = payload.message.strip()
    history_rows = db.query(ChatMessage).order_by(ChatMessage.id.desc()).limit(40).all()[::-1]
    history = [{"role": m.role, "content": m.content} for m in history_rows]

    service = ChatService()
    reply = service.reply(db, user_msg, history)

    db.add(ChatMessage(role="user", content=user_msg))
    db.add(ChatMessage(role="assistant", content=reply))
    db.commit()
    last = db.query(ChatMessage).order_by(ChatMessage.id.desc()).first()
    return {"reply": reply, "message_id": last.id if last else 0}
