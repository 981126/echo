"""APScheduler 定时任务：每日流水线 / 每日指标与留存 / 每日备份。"""

from __future__ import annotations

import subprocess
from pathlib import Path

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from sqlalchemy import text

from .config import get_settings
from .core.log import get_logger, setup_logging
from .db import SessionLocal
from .services.metrics import apply_retention
from .services.pipeline import run_daily_pipeline

_scheduler: BackgroundScheduler | None = None
log = get_logger("scheduler")


def _alert(kind: str, title: str, detail: str) -> None:
    """定时任务失败统一处理（R-133）：日志 + 站内通知 + 邮件告警（邮件未配置时自动跳过）。"""
    log.error("%s：%s", title, detail)
    db = SessionLocal()
    try:
        from .tasks import push_notification

        push_notification(db, kind=kind, status="failed", title=title, message=detail[:200], target="/home")
    except Exception:  # noqa: BLE001 通知失败不能影响主流程
        db.rollback()
        log.exception("定时任务失败通知写入失败")
    finally:
        db.close()
    try:
        from .services.notify import send_alert

        send_alert(title, detail)
    except Exception:  # noqa: BLE001
        log.exception("定时任务失败邮件告警发送失败")


def _daily_pipeline_job() -> None:
    db = SessionLocal()
    try:
        run_daily_pipeline(db)
    except Exception as exc:  # noqa: BLE001 定时触发没有 BackgroundTask，必须自己告警（R-133）
        _alert("daily_pipeline", "每日流水线失败", str(exc))
    finally:
        db.close()


def _daily_metrics_job() -> None:
    db = SessionLocal()
    try:
        # cookie 指标抓取为占位通道（需 NAS 联调），未启用前不执行，避免误导；只做留存清理
        apply_retention(db, hot_days=30)
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        _alert("daily_metrics", "每日留存清理失败", str(exc))
    finally:
        db.close()


def _platform_sync_job() -> None:
    """每日两轮平台数据同步（06:00/17:00，配置 ECHO_PLATFORM_SYNC_TIMES；R-109）。

    主博主 + 全部对标博主统一同步（每账号最新 15 条 + 下载视频 + 自动转写），
    同步完成后自动触发一次「重新对标」（refetch=False，不重复拉取 TikHub）。
    """
    from .tasks import start_task
    from .services.platform_sync import run_daily_sync_all

    def fn(db, payload):
        return run_daily_sync_all(db)

    try:
        start_task("platform_sync", {"scope": "daily", "source": "scheduler"}, fn)
    except Exception as exc:  # noqa: BLE001 入队失败要告警（R-133）
        _alert("platform_sync", "定时平台同步入队失败", str(exc))


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
    except Exception as exc:  # noqa: BLE001 清理失败要留痕（R-133）
        db.rollback()
        _alert("daily_housekeep", "每日清理失败", str(exc))
    finally:
        db.close()


def _publish_backfill_job() -> None:
    """每日 05:00：刷新已发布草稿的表现回填（R-189）。"""
    db = SessionLocal()
    try:
        from .services.draft_performance import refresh_published_performance

        n = refresh_published_performance(db)
        if n:
            log.info("发布表现回填：更新 %d 篇", n)
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        _alert("publish_backfill", "发布表现回填失败", str(exc))
    finally:
        db.close()


def _weekly_ideas_job() -> None:
    """每周一 08:30：生成「本周灵感补给」并推送（R-188）。

    缺口选题（AI，失败降级）+ 每周灵感包（本地统计）→ 站内通知（深链主页）+ best-effort 邮件。
    """
    db = SessionLocal()
    try:
        from .services import opportunity

        # R-192：预热「模型1 语义聚类」缓存（每周一次，之后界面点开即得，不必现场等）
        try:
            opportunity.comment_clusters(db, limit=15, use_llm=True)
        except Exception:  # noqa: BLE001 预热失败不影响推送
            pass
        pack = opportunity.weekly_pack(db, limit=8)
        gap = opportunity.gap_suggestions(db, limit=5)
        message, total = opportunity.digest_message(pack.get("items") or [], gap.get("items") or [])
        if total == 0:
            return
        from .tasks import push_notification

        push_notification(
            db,
            kind="weekly_ideas",
            status="done",
            title=f"本周灵感补给：{total} 个选题",
            message=message,
            target="/home",
        )
        try:
            from .services import notify

            notify.send_alert("echo 本周灵感补给", message + "\n\n去「主页 → 内容机会」一键生成。")
        except Exception:  # noqa: BLE001 邮件是次要通道
            pass
    except Exception as exc:  # noqa: BLE001 周任务失败留痕（R-133）
        db.rollback()
        _alert("weekly_ideas", "每周灵感补给失败", str(exc))
    finally:
        db.close()


def _backup_job() -> None:
    """每日备份（R-133）：检查退出码，失败写站内通知 + 邮件告警（原来 check=False + pass 全程无感）。"""
    script = Path(__file__).resolve().parents[2] / "scripts" / "backup.sh"
    if not script.exists():
        _alert("daily_backup", "每日备份失败", f"备份脚本不存在：{script}")
        return
    ok = False
    detail = ""
    try:
        proc = subprocess.run(["bash", str(script)], capture_output=True, text=True, timeout=600)
        ok = proc.returncode == 0
        stdout = (proc.stdout or "").strip()
        stderr = (proc.stderr or "").strip()
        detail = stderr or stdout or f"exit={proc.returncode}"
    except Exception as exc:  # noqa: BLE001
        detail = f"执行备份脚本异常：{exc}"
    if ok:
        log.info("每日备份完成：%s", (detail.splitlines() or [""])[-1])
    else:
        _alert("daily_backup", "每日备份失败", detail)


def setup_scheduler() -> None:
    setup_logging()
    global _scheduler
    if _scheduler is not None:
        return
    settings = get_settings()
    hour, minute = (int(x) for x in settings.daily_push_time.split(":"))
    _scheduler = BackgroundScheduler(timezone=settings.tz)
    # M13（R-027）/R-109：每日平台数据同步两轮（默认 06:00/17:00，含对标）
    for time_str in (settings.platform_sync_times or "06:00,17:00").split(","):
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
    # R-057/R-131/R-208：原「每周提示重跑提示词候选」定时任务已删除——
    # 提示词优化改为素材到量自动触发（prompt_service.maybe_auto_optimize_prompt）。
    # R-188：每周一 08:30 主动推送本周灵感补给（缺口 + 热/评论）
    _scheduler.add_job(
        _weekly_ideas_job,
        CronTrigger(day_of_week="mon", hour=8, minute=30, timezone=settings.tz),
        id="weekly_ideas",
        misfire_grace_time=3600,
        coalesce=True,
    )
    # R-189：每日 05:00 回填已发布稿件的表现
    _scheduler.add_job(
        _publish_backfill_job,
        CronTrigger(hour=5, minute=0, timezone=settings.tz),
        id="publish_backfill",
        misfire_grace_time=3600,
        coalesce=True,
    )
    _scheduler.start()
