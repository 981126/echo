"""R-163：同步并发消费者基础设施（进程内，无外部消息队列）。

- 队列载体复用 `background_tasks` 表：一行 pending 即一个待消费工作项（与 R-162 的博主级队列一致）。
- **原子认领**：`UPDATE ... WHERE id=? AND status='pending'`，`rowcount==1` 才算拿到，避免重复消费。
- **线程池**：博主级 `ECHO_SYNC_CONCURRENCY`（默认 4）、素材级 `ECHO_SYNC_MEDIA_CONCURRENCY`（默认 2）。
- 每个消费者线程使用**自己的 Session**（SQLAlchemy Session 非线程安全），由调用方负责开启/关闭。
"""

from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Callable, Iterable

from sqlalchemy import update
from sqlalchemy.orm import Session, sessionmaker

from ..config import get_settings
from ..models.task import BackgroundTask


def session_factory(db: Session):
    """基于给定 Session 的 bind 生成新会话工厂（线程安全的消费者各自取一个）。"""
    return sessionmaker(bind=db.get_bind(), autoflush=False, autocommit=False)


def claim_task(db: Session, task_id: int) -> bool:
    """原子把 pending 任务置为 running；成功返回 True（别人已认领则 False）。"""
    res = db.execute(
        update(BackgroundTask)
        .where(BackgroundTask.id == task_id, BackgroundTask.status == "pending")
        .values(status="running")
    )
    db.commit()
    return int(getattr(res, "rowcount", 0) or 0) == 1


def pool_size(kind: str = "creator") -> int:
    """消费者池大小（kind=creator|media）。"""
    settings = get_settings()
    raw = settings.sync_media_concurrency if kind == "media" else settings.sync_concurrency
    return max(1, int(raw or 1))


def gather(
    fn: Callable[[Any], Any],
    items: Iterable[Any],
    *,
    workers: int,
    on_result: Callable[[Any, Any], None] | None = None,
) -> list[tuple[Any, Any]]:
    """并发对 items 执行 fn(item)，返回按完成顺序的 `[(item, result)]`。

    - 每个任务在独立线程执行（调用方在 fn 内自建 Session）；
    - 单个任务抛出的异常会被收集为该任务的 result（不中断其它任务）；
    - `on_result(item, result)` 在对应用户线程（主线程）完成时回调，便于聚合进度。
    """
    items = list(items)
    results: list[tuple[Any, Any]] = []
    if not items:
        return results
    with ThreadPoolExecutor(max_workers=max(1, min(int(workers), len(items))), thread_name_prefix="echo-sync") as ex:
        future_map = {ex.submit(fn, it): it for it in items}
        for fut in as_completed(future_map):
            item = future_map[fut]
            try:
                res: Any = fut.result()
            except Exception as exc:  # noqa: BLE001 单任务异常收集，不拖垮整批
                res = exc
            results.append((item, res))
            if on_result is not None:
                on_result(item, res)
    return results


def new_cancel() -> threading.Event:
    return threading.Event()
