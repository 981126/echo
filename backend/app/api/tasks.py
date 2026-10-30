"""后台任务状态接口（R-202：同时作为全局「进行中」指示器的事实源）。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..db import get_db
from ..core.task_meta import kind_label, target as task_target
from ..models.task import BackgroundTask
from ..schemas.task import TaskOut

router = APIRouter()


def _out(task: BackgroundTask) -> TaskOut:
    payload = task.payload_dict()
    out = TaskOut.model_validate(task)
    out.label = kind_label(task.kind)
    out.target = task_target(task.kind, payload, None)
    return out


@router.get("", response_model=list[TaskOut])
def list_tasks(limit: int = 50, status: str = "", kind: str = "", db: Session = Depends(get_db)):
    """后台任务列表；`status` 支持逗号分隔多值（如 `running,pending`，R-202），`kind` 同样支持多值。

    无状态时按 id 倒序；筛「进行中」时按创建时间正序（先入队先显示）。
    """
    q = db.query(BackgroundTask)
    if status:
        statuses = [s.strip() for s in status.split(",") if s.strip()]
        if statuses:
            q = q.filter(BackgroundTask.status.in_(statuses))
    if kind:
        kinds = [k.strip() for k in kind.split(",") if k.strip()]
        if kinds:
            q = q.filter(BackgroundTask.kind.in_(kinds))
    active = any(s in ("running", "pending") for s in status.split(","))
    order = BackgroundTask.created_at.asc() if active else BackgroundTask.id.desc()
    # R-241：limit 上限收敛到 200（前端实际轮询参数；防大 limit 全表序列化）
    return [_out(t) for t in q.order_by(order).limit(max(1, min(limit, 200))).all()]


@router.get("/{task_id}", response_model=TaskOut)
def get_task(task_id: int, db: Session = Depends(get_db)):
    task = db.get(BackgroundTask, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="任务不存在")
    return _out(task)
