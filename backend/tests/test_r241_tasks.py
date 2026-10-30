"""R-241：后台任务去重 + 全局并发上限回归。"""

from __future__ import annotations

import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from conftest import ensure_schema, fresh_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

from app.models.task import BackgroundTask  # noqa: E402
from app.tasks import start_task  # noqa: E402


def _fresh_sessionmaker():
    eng = fresh_engine()
    ensure_schema(eng)
    return sessionmaker(bind=eng, autoflush=False, autocommit=False)


def _wait_status(S, task_id: int, statuses: set[str], timeout: float = 10.0) -> str:
    deadline = time.monotonic() + timeout
    last = ""
    while time.monotonic() < deadline:
        s = S()
        try:
            row = s.get(BackgroundTask, task_id)
            last = row.status if row is not None else ""
        finally:
            s.close()
        if last in statuses:
            return last
        time.sleep(0.05)
    return last


def test_start_task_dedupes_same_kind_and_payload() -> None:
    """同 kind+payload 运行中重复触发 → 复用已有 task_id；完成后允许再建新任务。"""
    S = _fresh_sessionmaker()
    started: list[int] = []
    release = threading.Event()
    done = threading.Event()

    def _fn(db, payload):  # noqa: ANN001
        started.append(int(payload["n"]))
        release.wait(5)
        done.set()

    payload = {"n": 1, "case": "dedupe"}
    tid1 = start_task("r241_dedupe", payload, _fn)
    tid2 = start_task("r241_dedupe", payload, _fn)
    assert tid2 == tid1, f"同 payload 运行中应复用 task_id：{tid1} != {tid2}"
    assert _wait_status(S, tid1, {"running", "done"}) in {"running", "done"}

    release.set()
    assert done.wait(5)
    assert _wait_status(S, tid1, {"done"}) == "done"

    # 完成后允许再建新任务（不被历史任务去重）
    tid3 = start_task("r241_dedupe", payload, _fn)
    assert tid3 != tid1
    release.set()
    _wait_status(S, tid3, {"done"})


def test_start_task_respects_global_concurrency_limit(monkeypatch) -> None:
    """全局信号量为 1 时，第二个任务必须等第一个结束后才开始（等待期间保持 pending）。"""
    import app.tasks as tasks_mod

    S = _fresh_sessionmaker()
    monkeypatch.setattr(tasks_mod, "_TASK_SLOTS", threading.BoundedSemaphore(1))

    started1 = threading.Event()
    release1 = threading.Event()
    started2 = threading.Event()
    finished = threading.Event()

    def _fn_slow(db, payload):  # noqa: ANN001
        started1.set()
        release1.wait(10)

    def _fn_second(db, payload):  # noqa: ANN001
        started2.set()
        finished.set()

    tid1 = start_task("r241_cap_1", {"case": "cap1"}, _fn_slow)
    tid2 = start_task("r241_cap_2", {"case": "cap2"}, _fn_second)
    assert started1.wait(5), "第一个任务应开始执行"
    assert not started2.wait(0.3), "全局并发为 1 时第二个任务不应并发开始"
    assert _wait_status(S, tid2, {"pending"}, timeout=0.2) == "pending"

    release1.set()
    assert started2.wait(5), "第一个任务结束后第二个任务应开始"
    assert finished.wait(5)
    assert _wait_status(S, tid1, {"done"}) == "done"
    assert _wait_status(S, tid2, {"done"}) == "done"
