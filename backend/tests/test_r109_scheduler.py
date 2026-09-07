"""R-109 调度注册测试：每日两轮（配置时间）不再注册独立 06:00 自动重新对标（mock 离线）。"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def test_scheduler_registers_two_daily_syncs_no_benchmark_rerun(monkeypatch):
    import app.scheduler as sch

    jobs: list[tuple] = []

    class FakeSched:
        def add_job(self, fn, trigger, **kw):
            jobs.append((fn.__name__, trigger, kw))

        def start(self):
            pass

    monkeypatch.setattr(sch, "BackgroundScheduler", lambda *a, **k: FakeSched())
    monkeypatch.setattr(
        sch,
        "get_settings",
        lambda: SimpleNamespace(
            daily_push_time="07:00",
            tz="Asia/Shanghai",
            platform_sync_times="06:00,17:00",
        ),
    )
    sch.setup_scheduler()

    names = [j[0] for j in jobs]
    ids = [j[2].get("id") for j in jobs]
    assert names.count("_platform_sync_job") == 2  # 06:00 / 17:00 两轮
    assert "benchmark_rerun_daily" not in ids  # R-105 独立定时已取消
    assert names.count("_daily_pipeline_job") == 1
