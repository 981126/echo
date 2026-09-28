"""R-163：同步并发基础设施测试（离线）。

覆盖：
- 全局令牌桶按速率发放、允许容量内突发；
- `claim_task` 原子认领（同一任务并发只成功一次）；
- `gather` 并发执行（多任务耗时接近单任务）且单任务异常被收集不拖垮整批；
- 预算计数在并发下不超发。
"""

from __future__ import annotations

import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import Base
from app.models.task import BackgroundTask
from app.services import sync_pool
from app.services.platform import tikhub
from app.services.platform.budget import _charge, get_budget, set_budget


@pytest.fixture()
def session_factory_local(tmp_path):
    eng = create_engine(f"sqlite:///{tmp_path}/p.db", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=eng)
    factory = sessionmaker(bind=eng, autoflush=False, autocommit=False)
    yield factory
    eng.dispose()


def test_token_bucket_enforces_rate_and_allows_burst():
    b = tikhub._TokenBucket(rate=100.0, capacity=1)
    start = time.monotonic()
    for _ in range(4):  # 容量 1：首 1 个即时，其后每个约 1/100s
        b.acquire()
    elapsed = time.monotonic() - start
    assert elapsed >= 0.02  # 3 个间隔 ≈ 0.03s（放宽下限避免抖动）

    burst = tikhub._TokenBucket(rate=1.0, capacity=5)
    start = time.monotonic()
    for _ in range(5):
        burst.acquire()
    assert time.monotonic() - start < 0.05  # 容量内突发不排队


def test_claim_task_is_atomic(session_factory_local):
    s = session_factory_local()
    row = BackgroundTask(kind="platform_sync", status="pending")
    s.add(row)
    s.commit()
    tid = row.id

    assert sync_pool.claim_task(s, tid) is True
    assert sync_pool.claim_task(s, tid) is False  # 已认领，不再成功
    assert s.get(BackgroundTask, tid).status == "running"
    s.close()


def test_gather_runs_concurrently_and_collects_errors():
    barrier = threading.Barrier(4)

    def work(n):
        barrier.wait(timeout=2)  # 4 个任务必须同时在跑，否则超时
        return n * 2

    start = time.monotonic()
    results = sync_pool.gather(work, [1, 2, 3, 4], workers=4)
    assert sorted(r for _, r in results) == [2, 4, 6, 8]
    assert time.monotonic() - start < 1.0

    def boom(n):
        if n == 2:
            raise ValueError("boom")
        return n

    out = dict(sync_pool.gather(boom, [1, 2, 3], workers=3))
    assert out[1] == 1 and out[3] == 3
    assert isinstance(out[2], ValueError)


def test_budget_not_oversold_under_concurrency(session_factory_local):
    seed = session_factory_local()
    set_budget(seed, 10)
    seed.close()

    ok = []
    lock = threading.Lock()

    def charge():
        s = session_factory_local()
        try:
            _charge(s)
            with lock:
                ok.append(1)
        except Exception:  # noqa: BLE001 预算耗尽属预期
            pass
        finally:
            s.close()

    threads = [threading.Thread(target=charge) for _ in range(30)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    check = session_factory_local()
    budget = get_budget(check)
    assert len(ok) == 10  # 预算 10：恰好 10 次成功
    assert budget["used"] == 10  # 不多不少
    check.close()
