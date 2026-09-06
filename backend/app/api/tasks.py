"""后台任务状态接口。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..db import get_db
from ..models.task import BackgroundTask
from ..schemas.task import TaskOut

router = APIRouter()


@router.get("", response_model=list[TaskOut])
def list_tasks(limit: int = 50, status: str = "", kind: str = "", db: Session = Depends(get_db)):
    """后台任务列表；可按 status(running/done/failed) 与 kind 过滤（R-081：恢复卡片进度用）。"""
    q = db.query(BackgroundTask)
    if status:
        q = q.filter(BackgroundTask.status == status)
    if kind:
        q = q.filter(BackgroundTask.kind == kind)
    return q.order_by(BackgroundTask.id.desc()).limit(min(limit, 500)).all()


@router.get("/{task_id}", response_model=TaskOut)
def get_task(task_id: int, db: Session = Depends(get_db)):
    task = db.get(BackgroundTask, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="任务不存在")
    return task
