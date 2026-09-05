"""APScheduler 定时任务：每日流水线 / 每日指标与留存 / 每日备份。"""

from __future__ import annotations

import subprocess
from pathlib import Path

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from sqlalchemy import text

from .config import get_settings
from .db import SessionLocal
from .services.metrics import apply_retention
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
        # cookie 指标抓取为占位通道（需 NAS 联调），未启用前不执行，避免误导；只做留存清理
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


def _housekeep_job() -> None:
    """每日清理（R-061）：通知/任务/同步记录/平台统计按保留期删除，防库无限膨胀。"""
    db = SessionLocal()
    try:
        rules = [
            ("DELETE FROM notifications WHERE created_at < datetime('now','-90 days')",),
            ("DELETE FROM background_tasks WHERE created_at < datetime('now','-30 days')",),
            ("DELETE FROM sync_jobs WHERE started_at IS NOT NULL AND started_at < datetime('now','-60 days')",),
            ("DELETE FROM platform_post_stats WHERE stat_date < date('now','-400 days')",),
        ]
        for (sql,) in rules:
            db.execute(text(sql))
        db.commit()
    except Exception:  # noqa: BLE001  清理失败不拖垮主服务
        db.rollback()
    finally:
        db.close()


def _weekly_style_job() -> None:
    """每周日 03:20 风格重建（R-057）：基于全部素材画像 + 表现最好样本，
    自动产出一版新的生成提示词候选（不启用）并通知作者。"""
    db = SessionLocal()
    try:
        from .core.style_profile import build_style_profile, format_style_profile
        from .services.generation import _all_texts, _weight
        from .services.prompt_service import optimize

        rows = _all_texts(db)
        if len(rows) < 5:
            return  # 语料太少不值得每周重建
        texts = [t for _, t in rows]
        profile = format_style_profile(build_style_profile(texts))
        top = sorted(rows, key=lambda vt: _weight(db, vt[0]), reverse=True)[:3]
        snippets = "\n".join(f"- {text[:300]}" for _, text in top)
        material = f"{profile}\n\n表现最好的素材节选（学习腔调）：\n{snippets}"
        candidate = optimize(db, "generation", material)
        if candidate is not None:
            from .tasks import push_notification

            push_notification(
                db,
                kind="prompt_candidate",
                status="done",
                title="每周风格重建：生成提示词新候选",
                message=f"基于全部素材风格画像与高分节选自动优化了 v{candidate.version}，待你启用",
                target="/prompts?key=generation",
            )
    except Exception:  # noqa: BLE001 周任务失败不影响主服务
        db.rollback()
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
    # R-061：每日清理 04:00
    _scheduler.add_job(
        _housekeep_job,
        CronTrigger(hour=4, minute=0, timezone=settings.tz),
        id="daily_housekeep",
        misfire_grace_time=3600,
        coalesce=True,
    )
    # R-057：每周风格重建（周日 03:20）
    _scheduler.add_job(
        _weekly_style_job,
        CronTrigger(day_of_week="sun", hour=3, minute=20, timezone=settings.tz),
        id="weekly_style_rebuild",
        misfire_grace_time=3600,
        coalesce=True,
    )
    _scheduler.start()
