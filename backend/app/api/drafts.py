"""脚本草稿接口：工作台创建/改写/保存。"""
import json

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..db import get_db
from ..models.draft import Draft
from ..schemas.draft import DraftCreate, DraftOut, DraftUpdate
from ..services.generation import generate_draft

router = APIRouter()


class GenerateIn(BaseModel):
    topic: str


@router.post("/generate", response_model=DraftOut)
def generate(payload: GenerateIn, db: Session = Depends(get_db)):
    """根据选题生成三件套（标题/封面字/脚本）+ 平台外壳。"""
    return generate_draft(db, payload.topic)


@router.get("", response_model=list[DraftOut])
def list_drafts(status: str = "", limit: int = 100, db: Session = Depends(get_db)):
    q = db.query(Draft)
    if status:
        q = q.filter(Draft.status == status)
    return q.order_by(Draft.updated_at.desc()).limit(limit).all()


@router.post("", response_model=DraftOut)
def create_draft(payload: DraftCreate, db: Session = Depends(get_db)):
    data = payload.model_dump()
    data["platform_shells"] = json.dumps(data.get("platform_shells") or {}, ensure_ascii=False)
    draft = Draft(**data)
    db.add(draft)
    db.commit()
    db.refresh(draft)
    return draft


@router.get("/{draft_id}", response_model=DraftOut)
def get_draft(draft_id: int, db: Session = Depends(get_db)):
    draft = db.get(Draft, draft_id)
    if draft is None:
        raise HTTPException(status_code=404, detail="草稿不存在")
    return draft


@router.patch("/{draft_id}", response_model=DraftOut)
def update_draft(draft_id: int, payload: DraftUpdate, db: Session = Depends(get_db)):
    draft = db.get(Draft, draft_id)
    if draft is None:
        raise HTTPException(status_code=404, detail="草稿不存在")
    data = payload.model_dump(exclude_unset=True)
    if "platform_shells" in data:
        data["platform_shells"] = json.dumps(data["platform_shells"] or {}, ensure_ascii=False)
    for field, value in data.items():
        setattr(draft, field, value)
    db.commit()
    db.refresh(draft)
    return draft
