"""后台任务运行器：DB 任务表 + 后台线程；任务结束自动写入通知（R-019）。"""

from __future__ import annotations

import inspect
import json
import threading

from .db import SessionLocal
from .core.log import get_logger
from .models.notification import Notification
from .models.task import BackgroundTask
from .services.events import publish

log = get_logger("tasks")

KIND_LABELS = {
    "import_video": "素材转写",
    "persona_init": "人设初始化",
    "persona_incremental": "人设增量校验",
    "prompt_eval": "提示词候选评测",
    "prompt_rule_optimize": "规则型提示词优化",
    "prompt_refresh_hint": "提示词优化提醒",
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
    "llm_fallback": "模型降级",
    "model_selfcheck": "双模型兼容性自检",
    "schema_check": "库结构自检",
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
    if kind == "persona_incremental":
        return "/persona"
    if kind == "prompt_eval":
        return f"/prompts?key={payload.get('key', '')}"
    if kind == "prompt_rule_optimize":
        return "/prompts"
    if kind == "prompt_refresh_hint":
        return "/prompts?key=generation"
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
    if kind == "model_selfcheck":
        return "/prompts"
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
        log.exception("后台任务失败 kind=%s task_id=%s", kind, task_id)
        task = db.get(BackgroundTask, task_id)
        if task is not None:
            task.status = "failed"
            task.error = str(exc)[:2000]
            db.commit()
            publish("task.update", {"id": task_id, "status": "failed", "progress": task.progress, "note": task.note or "", "error": task.error[:500], "payload": payload})
        try:
            _notify(db, kind=kind, payload=payload, status="failed", error=str(exc))
        except Exception:  # noqa: BLE001 R-133：通知失败不得影响终态（否则会把已成功的任务改判 failed）
            db.rollback()
            log.exception("后台任务失败通知写入失败 task_id=%s", task_id)
    finally:
        db.close()


def _maybe_optimize_prompt(db, payload: dict) -> None:
    """素材导入后的提示词提醒（R-131）：**不再自动产出候选**，只在累计到阈值时发一条提醒。"""
    from .models.video import Video
    from .services.prompt_service import maybe_notify_prompt_refresh

    try:
        video = db.get(Video, int(payload.get("video_id") or 0))
        if video is None or not video.transcript:
            return
        text = video.transcript.corrected_text or video.transcript.transcript_text
        if not text:
            return
        maybe_notify_prompt_refresh(db)
    except Exception:  # noqa: BLE001 提醒失败不影响导入主流程
        db.rollback()


def mark_interrupted_tasks_on_startup() -> int:
    """服务重启时把遗留 pending/running 任务标记失败（线程已随进程消失）。

    R-134：改为逐条标记并写一条汇总站内通知（原来静默改判，通知中心毫无记录）；
    同时消费 `persona_incremental_pending` 补跑标记（重新入队增量校验）。
    """
    db = SessionLocal()
    try:
        rows = db.query(BackgroundTask).filter(BackgroundTask.status.in_(["pending", "running"])).all()
        kinds: dict[str, int] = {}
        for row in rows:
            row.status = "failed"
            row.error = "服务重启，任务中断"
            row.note = "任务中断"
            kinds[row.kind] = kinds.get(row.kind, 0) + 1
        db.commit()
        n = len(rows)
        if n:
            log.warning("服务重启：%d 个中断任务已标记 failed（%s）", n, kinds)
            try:
                summary = "、".join(f"{KIND_LABELS.get(k, k)}×{v}" for k, v in kinds.items())
                push_notification(
                    db,
                    kind="task_interrupted",
                    status="failed",
                    title=f"服务重启，{n} 个任务被中断",
                    message=f"这些任务已标记失败，可重新发起：{summary}",
                    target="/videos",
                )
            except Exception:  # noqa: BLE001 通知失败不影响启动
                db.rollback()
                log.exception("重启中断任务通知写入失败")
        _resume_persona_incremental_if_pending(db)
        _cleanup_stale_sync_state(db)
        _cleanup_stale_draft_ai_state(db)
        return n
    finally:
        db.close()


def _cleanup_stale_sync_state(db) -> dict:
    """R-134：清理同步侧残留 running —— `sync_jobs` 与账号 `sync_status`。

    否则同步中途重启后，博主页进度条会永久显示「同步中」（原先要等 60 天清理）。
    """
    from .core.timeutil import now as _now
    from .models.platform import CreatorAccount, SyncJob

    n_job = (
        db.query(SyncJob)
        .filter(SyncJob.status == "running")
        .update({"status": "failed", "message": "服务重启，同步中断", "finished_at": _now()}, synchronize_session=False)
    )
    n_acc = (
        db.query(CreatorAccount)
        .filter(CreatorAccount.sync_status.in_(["running", "pending"]))
        .update({"sync_status": "failed", "sync_message": "服务重启，同步中断"}, synchronize_session=False)
    )
    db.commit()
    if n_job or n_acc:
        log.warning("启动自愈：sync_jobs=%d、账号 sync_status=%d 已复位", n_job or 0, n_acc or 0)
    return {"sync_jobs": int(n_job or 0), "accounts": int(n_acc or 0)}


def _cleanup_stale_draft_ai_state(db) -> int:
    """R-173：清理草稿 AI 长任务残留状态 —— 讨论/洗稿/回炉中途重启后卡片会永久转圈。

    残留 `running` 改判为「服务重启，任务中断」（卡片显示「上次讨论中断」但不转圈），
    同时删掉 R-173 之前的旧键 `debate:{id}`。
    """
    from .services import draft_status

    n = draft_status.reset_stale_on_startup(db)
    if n:
        log.warning("启动自愈：%d 条草稿 AI 状态由 running 改判中断", n)
    return n


def _resume_persona_incremental_if_pending(db) -> bool:
    """R-134：重启后消费 `persona_incremental_pending` 标记，重新入队增量校验（提取结果有缓存，成本可控）。"""
    from .models.kv import Kv

    try:
        row = db.get(Kv, "persona_incremental_pending")
        if row is None or row.value != "1":
            return False
        _set_persona_pending(db, "0")
        from .services.creator_service import current_creator_id
        from .services.ingest import enqueue_persona_incremental

        enqueue_persona_incremental(db, creator_id=current_creator_id(db))
        log.info("重启后已重新入队人设增量校验（存在未消费的 pending 标记）")
        return True
    except Exception:  # noqa: BLE001
        db.rollback()
        log.exception("重启后补跑人设增量校验失败")
        return False


def _set_persona_pending(db, value: str) -> None:
    from .models.kv import Kv

    row = db.get(Kv, "persona_incremental_pending")
    if row is None:
        db.add(Kv(key="persona_incremental_pending", value=value))
    else:
        row.value = value
    db.commit()
