"""APScheduler 定时任务：每日流水线 / 每日指标与留存 / 每日备份。"""
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
