"""作品合并接口（M13+）：素材库云端作品合并/拆分。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..db import get_db
from ..services.creator_service import current_creator_id
from ..services.works_service import list_works, merge_manual, split_work

router = APIRouter()


class MergeIn(BaseModel):
    platform_post_ids: list[int] = []


@router.get("", response_model=dict)
def get_works(creator_id: int = 0, db: Session = Depends(get_db)):
    cid = creator_id or current_creator_id(db)
    items = list_works(db, cid)
    return {"total": len(items), "items": items}


@router.post("/merge", response_model=dict)
def merge_items(payload: MergeIn, db: Session = Depends(get_db)):
    try:
        return merge_manual(db, payload.platform_post_ids)
    except HTTPException:
        raise


@router.post("/{work_id}/split", response_model=dict)
def split_items(work_id: int, payload: MergeIn, db: Session = Depends(get_db)):
    return split_work(db, work_id, keep_ids=payload.platform_post_ids)
