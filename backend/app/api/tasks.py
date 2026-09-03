"""后台任务状态接口。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..db import get_db
from ..models.task import BackgroundTask
from ..schemas.task import TaskOut

router = APIRouter()


@router.get("", response_model=list[TaskOut])
def list_tasks(limit: int = 50, db: Session = Depends(get_db)):
    return db.query(BackgroundTask).order_by(BackgroundTask.id.desc()).limit(limit).all()


@router.get("/{task_id}", response_model=TaskOut)
def get_task(task_id: int, db: Session = Depends(get_db)):
    task = db.get(BackgroundTask, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="任务不存在")
    return task
