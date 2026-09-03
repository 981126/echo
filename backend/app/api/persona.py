"""人设档案接口：查看/手动添加/确认或拒绝 AI 建议/触发初始化。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..db import get_db
from ..models.persona import PersonaTag
from ..schemas.persona import PersonaDecision, PersonaTagCreate, PersonaTagOut
from ..services.ingest import persona_init_task
from ..tasks import start_task

router = APIRouter()


@router.get("", response_model=list[PersonaTagOut])
def list_persona(status: str = "", db: Session = Depends(get_db)):
    q = db.query(PersonaTag)
    if status:
        q = q.filter(PersonaTag.status == status)
    return q.order_by(PersonaTag.category, PersonaTag.id).all()


@router.post("/tags", response_model=PersonaTagOut)
def add_manual_tag(payload: PersonaTagCreate, db: Session = Depends(get_db)):
    tag = PersonaTag(**payload.model_dump(), source="manual", status="confirmed")
    db.add(tag)
    db.commit()
    db.refresh(tag)
    return tag


@router.post("/tags/{tag_id}/decision", response_model=PersonaTagOut)
def decide_tag(tag_id: int, payload: PersonaDecision, db: Session = Depends(get_db)):
    tag = db.get(PersonaTag, tag_id)
    if tag is None:
        raise HTTPException(status_code=404, detail="标签不存在")
    tag.status = payload.status
    db.commit()
    db.refresh(tag)
    return tag


@router.post("/init")
def init_persona(db: Session = Depends(get_db)):
    """用全部历史转写稿初始化/刷新人设档案（后台任务，建议非广告视频转写完成后调用）。"""
    task_id = start_task("persona_init", {}, persona_init_task)
    return {"task_id": task_id}
