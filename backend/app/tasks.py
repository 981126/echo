"""后台任务运行器：DB 任务表 + 后台线程；任务结束自动写入通知（R-019）。"""

from __future__ import annotations

import inspect
import json
import threading

from .db import SessionLocal
from .models.notification import Notification
from .models.task import BackgroundTask
from .services.events import publish

KIND_LABELS = {
    "import_video": "素材转写",
    "persona_init": "人设初始化",
    "daily_pipeline": "每日流水线",
    "diff_analysis": "草稿差异分析",
    "generate_draft": "AI 文案生成",
    "platform_sync": "平台数据同步",
    "platform_sync_single": "素材数据同步",
    "platform_media": "素材媒体补齐",
    "card_sync": "素材同步",
    "benchmark_rerun": "重新对标",
    "benchmark_analyze": "AI 分析",
    "benchmark_rewrite": "洗稿",
}


def _target(kind: str, payload: dict, result) -> str:
    if kind == "import_video":
        return f"/videos?edit={payload.get('video_id', '')}"
    if kind == "platform_media":
        if isinstance(result, dict) and result.get("video_id"):
            return f"/videos?edit={result['video_id']}"
        return "/videos"
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
    if kind in ("platform_sync", "platform_sync_single"):
        return "/creators"
    if kind == "benchmark_rerun":
        return "/benchmark"
    if kind in ("benchmark_analyze", "benchmark_rewrite"):
        return "/benchmark"
    return "/home"


def _notify(db, *, kind: str, payload: dict, status: str, result=None, error: str = "") -> None:
    label = KIND_LABELS.get(kind, kind)
    if status == "done":
        title = f"{label}完成"
        message = title
        if isinstance(result, dict) and result.get("title"):
            message = f"{title}：{result['title']}"
        elif isinstance(result, dict) and result.get("message"):
            message = f"{title}：{result['message']}"
    else:
        title = f"{label}失败"
        message = f"{title}：{(error or '未知错误')[:200]}"
    nt = Notification(
        kind=kind,
        status=status,
        title=title,
        message=message,
        target=_target(kind, payload, result),
    )
    db.add(nt)
    db.commit()
    db.refresh(nt)
    publish("notification.new", {"id": nt.id, "kind": nt.kind, "status": nt.status, "title": nt.title, "message": nt.message, "target": nt.target or ""})


def push_notification(db, *, kind: str, status: str, title: str, message: str, target: str = "") -> None:
    """统一通知写入（R-061 B 二期：避免各处手拼 Notification）；写后广播（R-087）。"""
    nt = Notification(kind=kind, status=status, title=title, message=message, target=target)
    db.add(nt)
    db.commit()
    db.refresh(nt)
    publish("notification.new", {"id": nt.id, "kind": nt.kind, "status": nt.status, "title": nt.title, "message": nt.message, "target": nt.target or ""})


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

    def _update(pct: int | None = None, note: str = "") -> None:
        """任务函数（三参签名 fn(db,payload,update)）实时回写进度/阶段说明（R-081）。"""
        task = db.get(BackgroundTask, task_id)
        if task is None:
            return
        if pct is not None:
            task.progress = max(0, min(100, int(pct)))
        if note:
            task.note = note[:255]
        db.commit()
        publish("task.update", {"id": task_id, "status": task.status, "progress": task.progress, "note": task.note or "", "payload": payload})

    try:
        task = db.get(BackgroundTask, task_id)
        if task is None:
            return
        task.status = "running"
        task.progress = 5
        db.commit()
        params = inspect.signature(fn).parameters
        if len(params) >= 3:
            result = fn(db, payload, _update)
        else:
            result = fn(db, payload)
        task = db.get(BackgroundTask, task_id)
        if task is not None:
            task.status = "done"
            task.progress = 100
            task.note = "完成"
            if result is not None:
                try:
                    task.result = json.dumps(result, ensure_ascii=False)
                except (TypeError, ValueError):
                    task.result = str(result)
            db.commit()
            publish("task.update", {"id": task_id, "status": "done", "progress": 100, "note": "完成", "payload": payload})
        _notify(db, kind=kind, payload=payload, status="done", result=result)
        if kind == "import_video":
            _maybe_optimize_prompt(db, payload)
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        task = db.get(BackgroundTask, task_id)
        if task is not None:
            task.status = "failed"
            task.error = str(exc)[:2000]
            db.commit()
            publish("task.update", {"id": task_id, "status": "failed", "progress": task.progress, "note": task.note or "", "error": task.error[:500], "payload": payload})
        _notify(db, kind=kind, payload=payload, status="failed", error=str(exc))
    finally:
        db.close()


def _maybe_optimize_prompt(db, payload: dict) -> None:
    """每次导入新视频后，基于当前全部素材+人设自动产出候选新版（不启用）+ 通知。"""
    from .models.video import Video
    from .services.prompt_service import auto_optimize_generation

    try:
        video = db.get(Video, int(payload.get("video_id") or 0))
        if video is None or not video.transcript:
            return
        text = video.transcript.corrected_text or video.transcript.transcript_text
        if not text:
            return
        # R-022：每累计 3 条新素材才产一个候选（防过拟合单条）；语料=全部 ASR 文案按点赞率加权
        candidate = auto_optimize_generation(db)
        if candidate is None:
            return
        db.add(
            Notification(
                kind="prompt_candidate",
                status="done",
                title="生成提示词有新候选",
                message=f"基于新素材自动优化了生成提示词 v{candidate.version}，待你启用",
                target="/prompts?key=generation",
            )
        )
        db.commit()
    except Exception:  # noqa: BLE001 自动优化失败不影响导入主流程
        db.rollback()


def mark_interrupted_tasks_on_startup() -> int:
    """服务重启时，把遗留的 pending/running 任务标记为失败（线程已随进程消失）。"""
    db = SessionLocal()
    try:
        n = db.query(BackgroundTask).filter(BackgroundTask.status.in_(["pending", "running"])).update(
            {"status": "failed", "error": "服务重启，任务中断", "note": "任务中断"}, synchronize_session=False
        )
        db.commit()
        return int(n or 0)
    finally:
        db.close()
