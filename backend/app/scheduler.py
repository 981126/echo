"""APScheduler 定时任务：每日流水线。"""
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from .config import get_settings
from .db import SessionLocal
from .services.pipeline import run_daily_pipeline

_scheduler: BackgroundScheduler | None = None


def _daily_job() -> None:
    db = SessionLocal()
    try:
        run_daily_pipeline(db)
    finally:
        db.close()


def setup_scheduler() -> None:
    global _scheduler
    if _scheduler is not None:
        return
    settings = get_settings()
    hour, minute = (int(x) for x in settings.daily_push_time.split(":"))
    _scheduler = BackgroundScheduler(timezone=settings.tz)
    _scheduler.add_job(
        _daily_job,
        CronTrigger(hour=hour, minute=minute, timezone=settings.tz),
        id="daily_pipeline",
        misfire_grace_time=3600,
        coalesce=True,
    )
    _scheduler.start()
