"""APScheduler 定时任务。

M1 仅初始化；M3 在此注册每日选题流水线与指标流水线。
"""
from apscheduler.schedulers.background import BackgroundScheduler

_scheduler: BackgroundScheduler | None = None


def setup_scheduler() -> None:
    global _scheduler
    if _scheduler is not None:
        return
    _scheduler = BackgroundScheduler(timezone="Asia/Shanghai")
    # M3: add_job(每日选题流水线, CronTrigger(hour=7, minute=0))
    # M4: add_job(每日指标流水线, CronTrigger(hour=8, minute=0))
    _scheduler.start()
