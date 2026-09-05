"""人设档案接口：查看/手动添加/确认或拒绝 AI 建议/触发初始化。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..db import get_db
from ..services.creator_service import current_creator_id
from ..models.persona import PersonaTag
from ..schemas.persona import PersonaDecision, PersonaTagCreate, PersonaTagOut, PersonaTagUpdate
from ..services.ingest import persona_init_task
from ..tasks import start_task

router = APIRouter()


@router.get("", response_model=list[PersonaTagOut])
def list_persona(status: str = "", db: Session = Depends(get_db)):
    q = db.query(PersonaTag)
    cid = current_creator_id(db)
    if cid:
        q = q.filter(PersonaTag.creator_id == cid)
    if status:
        q = q.filter(PersonaTag.status == status)
    return q.order_by(PersonaTag.category, PersonaTag.id).all()


@router.post("/tags", response_model=PersonaTagOut)
def add_manual_tag(payload: PersonaTagCreate, db: Session = Depends(get_db)):
    data = {k: v for k, v in payload.model_dump().items() if k != "source"}
    tag = PersonaTag(**data, source="manual", status="confirmed", creator_id=current_creator_id(db))
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


@router.patch("/tags/{tag_id}", response_model=PersonaTagOut)
def update_tag(tag_id: int, payload: PersonaTagUpdate, db: Session = Depends(get_db)):
    """编辑人设标签（标签/描述/类别）。"""
    tag = db.get(PersonaTag, tag_id)
    if tag is None:
        raise HTTPException(status_code=404, detail="标签不存在")
    if payload.label.strip():
        tag.label = payload.label.strip()
    tag.description = payload.description
    tag.category = payload.category
    db.commit()
    db.refresh(tag)
    return tag


@router.delete("/tags/{tag_id}", response_model=dict)
def delete_tag(tag_id: int, db: Session = Depends(get_db)):
    """删除人设标签。"""
    tag = db.get(PersonaTag, tag_id)
    if tag is None:
        raise HTTPException(status_code=404, detail="标签不存在")
    db.delete(tag)
    db.commit()
    return {"ok": True}


@router.post("/init")
def init_persona(db: Session = Depends(get_db)):
    """用全部历史转写稿初始化/刷新人设档案（后台任务，建议非广告视频转写完成后调用）。"""
    task_id = start_task("persona_init", {"creator_id": current_creator_id(db)}, persona_init_task)
    return {"task_id": task_id}
