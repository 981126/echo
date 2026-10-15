"""灵感随手记接口（R-186）：随手记 CRUD + 一键发展成选题初稿。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..db import get_db
from ..models.inspiration import InspirationNote
from ..services.creator_service import current_creator_id
from ..services.draft_flow import start_generation
from ..services.inspiration import refine_topic

router = APIRouter()


class NoteIn(BaseModel):
    text: str = ""
    image_url: str = ""
    source: str = "text"


def _out(n: InspirationNote) -> dict:
    return {
        "id": n.id,
        "text": n.text,
        "image_url": n.image_url,
        "source": n.source,
        "status": n.status,
        "draft_id": n.draft_id,
        "created_at": n.created_at.isoformat() if n.created_at else None,
    }


@router.get("", response_model=list[dict])
def list_notes(status: str = "", limit: int = 100, db: Session = Depends(get_db)):
    q = db.query(InspirationNote)
    cid = current_creator_id(db)
    if cid:
        q = q.filter(InspirationNote.creator_id == cid)
    if status:
        q = q.filter(InspirationNote.status == status)
    rows = q.order_by(InspirationNote.id.desc()).limit(max(1, min(limit, 300))).all()
    return [_out(n) for n in rows]


@router.post("", response_model=dict)
def create_note(payload: NoteIn, db: Session = Depends(get_db)):
    text = (payload.text or "").strip()
    if not text and not (payload.image_url or "").strip():
        raise HTTPException(status_code=400, detail="随手记不能为空")
    note = InspirationNote(
        creator_id=current_creator_id(db),
        text=text,
        image_url=(payload.image_url or "").strip(),
        source=(payload.source or "text")[:20],
    )
    db.add(note)
    db.commit()
    db.refresh(note)
    return _out(note)


@router.post("/{note_id}/develop", response_model=dict)
def develop_note(note_id: int, db: Session = Depends(get_db)):
    """把随手记提炼成选题并直接入队生成一篇草稿；标记该条已用。"""
    note = db.get(InspirationNote, note_id)
    if note is None:
        raise HTTPException(status_code=404, detail="随手记不存在")
    topic = refine_topic(db, note.text)
    if not topic:
        raise HTTPException(status_code=400, detail="内容为空，无法生成")
    # R-227：随手记原文作为联网检索的 query 源（比标题更具体）
    task_id, draft_id = start_generation(db, topic, query_source=note.text)
    note.status = "used"
    note.draft_id = draft_id
    db.commit()
    return {"task_id": task_id, "draft_id": draft_id, "topic": topic}


@router.delete("/{note_id}", response_model=dict)
def delete_note(note_id: int, db: Session = Depends(get_db)):
    note = db.get(InspirationNote, note_id)
    if note is None:
        raise HTTPException(status_code=404, detail="随手记不存在")
    db.delete(note)
    db.commit()
    return {"ok": True}
