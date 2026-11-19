"""R-266：开头样本接口（覆盖统计 + 重建任务）。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..db import get_db
from ..services import opening_sample as service
from ..services.creator_service import get_current_creator
from ..tasks import find_running_task, start_task

router = APIRouter()


class RebuildIn(BaseModel):
    """R-266：重建范围；Phase A 只支持 all（own/peer 一起）。"""

    scope: str = "all"


def _owner(db: Session):
    owner = get_current_creator(db)
    if owner is None:
        raise HTTPException(status_code=400, detail="请先创建并切换到主博主")
    return owner


@router.get("/coverage", response_model=dict)
def coverage(db: Session = Depends(get_db)):
    return service.coverage(db, _owner(db).id)


@router.post("/rebuild")
def rebuild(payload: RebuildIn | None = None, db: Session = Depends(get_db)):
    owner = _owner(db)
    running = find_running_task("opening_samples")
    if running:
        return JSONResponse(status_code=202, content={"task_id": running, "reused": True})
    task_id = start_task("opening_samples", {"owner_id": owner.id}, service.opening_samples_task)
    return JSONResponse(status_code=202, content={"task_id": task_id, "reused": False})
