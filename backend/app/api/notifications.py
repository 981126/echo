"""通知接口：列表 / 已读 / 清空（R-019）。"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..db import get_db
from ..models.notification import Notification
from ..schemas.notification import NotificationOut, NotificationReadIn

router = APIRouter()


@router.get("", response_model=list[NotificationOut])
def list_notifications(limit: int = 50, db: Session = Depends(get_db)):
    return (
        db.query(Notification)
        .order_by(Notification.id.desc())
        .limit(min(int(limit), 100))
        .all()
    )


@router.get("/unread-count", response_model=dict)
def unread_count(db: Session = Depends(get_db)):
    return {"unread": db.query(Notification).filter(Notification.read.is_(False)).count()}


@router.post("/read", response_model=dict)
def mark_read(payload: NotificationReadIn, db: Session = Depends(get_db)):
    q = db.query(Notification)
    if payload.ids:
        q = q.filter(Notification.id.in_(payload.ids))
    q.filter(Notification.read.is_(False)).update({"read": True}, synchronize_session=False)
    db.commit()
    return {"ok": True}


@router.post("/clear", response_model=dict)
def clear_notifications(db: Session = Depends(get_db)):
    db.query(Notification).delete()
    db.commit()
    return {"ok": True}
