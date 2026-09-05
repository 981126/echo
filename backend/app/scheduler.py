"""APScheduler 定时任务：每日流水线 / 每日指标与留存 / 每日备份。"""

from __future__ import annotations

import subprocess
from pathlib import Path

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from .config import get_settings
from .db import SessionLocal
from .services.metrics import apply_retention, fetch_daily
from .services.pipeline import run_daily_pipeline

_scheduler: BackgroundScheduler | None = None


def _daily_pipeline_job() -> None:
    db = SessionLocal()
    try:
        run_daily_pipeline(db)
    finally:
        db.close()


def _daily_metrics_job() -> None:
    db = SessionLocal()
    try:
        fetch_daily(db)  # cookie 抓取 best-effort（mock 模式 no-op）
        apply_retention(db, hot_days=30)
    finally:
        db.close()


def _platform_sync_job() -> None:
    """每日两轮平台数据同步（07:30/18:00，配置 ECHO_PLATFORM_SYNC_TIMES）。"""
    from .tasks import start_task
    from .services.platform_sync import run_sync

    def fn(db, payload):
        return run_sync(db, scope="daily")

    try:
        start_task("platform_sync", {"scope": "daily", "source": "scheduler"}, fn)
    except Exception:  # noqa: BLE001  定时失败不拖垮进程（预算/无账号时静默）
        pass


def _backup_job() -> None:
    script = Path(__file__).resolve().parents[2] / "scripts" / "backup.sh"
    if script.exists():
        try:
            subprocess.run(["bash", str(script)], check=False, timeout=600)
        except Exception:  # noqa: BLE001
            pass


def setup_scheduler() -> None:
    global _scheduler
    if _scheduler is not None:
        return
    settings = get_settings()
    hour, minute = (int(x) for x in settings.daily_push_time.split(":"))
    _scheduler = BackgroundScheduler(timezone=settings.tz)
    # M13（R-027）：每日平台数据同步两轮（默认 07:30/18:00）
    for time_str in (settings.platform_sync_times or "07:30,18:00").split(","):
        time_str = time_str.strip()
        if ":" not in time_str:
            continue
        try:
            sh, sm = (int(x) for x in time_str.split(":"))
        except ValueError:
            continue
        _scheduler.add_job(
            _platform_sync_job,
            CronTrigger(hour=sh, minute=sm, timezone=settings.tz),
            id=f"platform_sync_{time_str}",
            misfire_grace_time=3600,
            coalesce=True,
        )
    _scheduler.add_job(
        _daily_pipeline_job,
        CronTrigger(hour=hour, minute=minute, timezone=settings.tz),
        id="daily_pipeline",
        misfire_grace_time=3600,
        coalesce=True,
    )
    _scheduler.add_job(
        _daily_metrics_job,
        CronTrigger(hour=hour + 1, minute=0, timezone=settings.tz),
        id="daily_metrics",
        misfire_grace_time=3600,
        coalesce=True,
    )
    _scheduler.add_job(
        _backup_job,
        CronTrigger(hour=2, minute=30, timezone=settings.tz),
        id="daily_backup",
        misfire_grace_time=3600,
        coalesce=True,
    )
    _scheduler.start()
