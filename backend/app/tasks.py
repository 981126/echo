"""后台任务运行器：DB 任务表 + 后台线程（不引入 Redis/队列）。"""

from __future__ import annotations

import json
import threading

from .db import SessionLocal
from .models.task import BackgroundTask


def start_task(kind: str, payload: dict, fn) -> int:
    db = SessionLocal()
    try:
        task = BackgroundTask(kind=kind, payload=json.dumps(payload, ensure_ascii=False))
        db.add(task)
        db.commit()
        db.refresh(task)
        task_id = task.id
    finally:
        db.close()
    threading.Thread(target=_run_worker, args=(task_id, kind, payload, fn), daemon=True).start()
    return task_id


def _run_worker(task_id: int, kind: str, payload: dict, fn) -> None:
    db = SessionLocal()
    try:
        task = db.get(BackgroundTask, task_id)
        if task is None:
            return
        task.status = "running"
        task.progress = 10
        db.commit()
        fn(db, payload)
        task = db.get(BackgroundTask, task_id)
        if task is not None:
            task.status = "done"
            task.progress = 100
            db.commit()
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        task = db.get(BackgroundTask, task_id)
        if task is not None:
            task.status = "failed"
            task.error = str(exc)[:2000]
            db.commit()
    finally:
        db.close()
