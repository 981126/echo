"""后台任务运行器：DB 任务表 + 后台线程；任务结束自动写入通知（R-019）。"""

from __future__ import annotations

import json
import threading

from .db import SessionLocal
from .models.notification import Notification
from .models.task import BackgroundTask

KIND_LABELS = {
    "import_video": "素材转写",
    "persona_init": "人设初始化",
    "daily_pipeline": "每日流水线",
    "diff_analysis": "草稿差异分析",
    "generate_draft": "AI 文案生成",
}


def _target(kind: str, payload: dict, result) -> str:
    if kind == "import_video":
        return f"/videos?edit={payload.get('video_id', '')}"
    if kind == "persona_init":
        return "/persona"
    if kind == "daily_pipeline":
        return "/home"
    if kind == "diff_analysis":
        return f"/drafts?id={payload.get('draft_id', '')}"
    if kind == "generate_draft":
        if isinstance(result, dict) and result.get("draft_id"):
            return f"/drafts?id={result['draft_id']}"
        return "/drafts"
    return "/home"


def _notify(db, *, kind: str, payload: dict, status: str, result=None, error: str = "") -> None:
    label = KIND_LABELS.get(kind, kind)
    if status == "done":
        title = f"{label}完成"
        message = title
        if isinstance(result, dict) and result.get("title"):
            message = f"{title}：{result['title']}"
    else:
        title = f"{label}失败"
        message = f"{title}：{(error or '未知错误')[:200]}"
    db.add(
        Notification(
            kind=kind,
            status=status,
            title=title,
            message=message,
            target=_target(kind, payload, result),
        )
    )
    db.commit()


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
        result = fn(db, payload)
        task = db.get(BackgroundTask, task_id)
        if task is not None:
            task.status = "done"
            task.progress = 100
            db.commit()
        _notify(db, kind=kind, payload=payload, status="done", result=result)
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        task = db.get(BackgroundTask, task_id)
        if task is not None:
            task.status = "failed"
            task.error = str(exc)[:2000]
            db.commit()
        _notify(db, kind=kind, payload=payload, status="failed", error=str(exc))
    finally:
        db.close()
