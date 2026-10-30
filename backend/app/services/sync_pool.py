"""R-163：同步并发消费者基础设施（进程内，无外部消息队列）。

- 队列载体复用 `background_tasks` 表：一行 pending 即一个待消费工作项（与 R-162 的博主级队列一致）。
- **原子认领**：`UPDATE ... WHERE id=? AND status='pending'`，`rowcount==1` 才算拿到，避免重复消费。
- **线程池**：博主级 `ECHO_SYNC_CONCURRENCY`（默认 4）；媒体级（R-240 M8）改为**进程级共享**执行器，
  `ECHO_SYNC_MEDIA_CONCURRENCY` 的语义由「每博主并发」改为「全局媒体并发」（默认 6），
  多博主同时导航时共享同一个池，避免媒体队列尾部只剩「每博主 2 个」worker。
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
    """消费者池大小（kind=creator|media）。

    R-240 M8：media 返回的是**进程全局**媒体并发数（由 `gather_media` 的共享执行器使用）。
    """
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


# R-240 M8：进程级共享媒体执行器（跨博主复用；daemon 线程随进程退出回收）
_MEDIA_EXECUTOR: ThreadPoolExecutor | None = None
_MEDIA_EXECUTOR_LOCK = threading.Lock()


def media_workers() -> int:
    """全局媒体并发数（ECHO_SYNC_MEDIA_CONCURRENCY，R-240 起语义=进程全局）。"""
    return max(1, int(get_settings().sync_media_concurrency or 1))


def _media_executor() -> ThreadPoolExecutor:
    global _MEDIA_EXECUTOR
    if _MEDIA_EXECUTOR is None:
        with _MEDIA_EXECUTOR_LOCK:
            if _MEDIA_EXECUTOR is None:
                _MEDIA_EXECUTOR = ThreadPoolExecutor(
                    max_workers=media_workers(), thread_name_prefix="echo-media"
                )
    return _MEDIA_EXECUTOR


def _reset_media_executor() -> None:
    """测试用：丢弃共享媒体执行器（生产不调用；调用前须确保没有在跑的任务）。"""
    global _MEDIA_EXECUTOR
    with _MEDIA_EXECUTOR_LOCK:
        _MEDIA_EXECUTOR = None


def gather_media(
    fn: Callable[[Any], Any],
    items: Iterable[Any],
    *,
    on_result: Callable[[Any, Any], None] | None = None,
) -> list[tuple[Any, Any]]:
    """R-240 M8：媒体任务并发（进程级共享池，总并发 ≤ ECHO_SYNC_MEDIA_CONCURRENCY）。

    与 `gather` 同语义：每任务独立线程、单任务异常收集为 result、`on_result` 在调用线程
    （主线程）回调；区别是**不**在本次调用结束时销毁线程池——多个博主的媒体队列共享同一个
    进程级池，总并发由一个配置控制（默认 6），避免「各博主各 2 个」在尾部塌成 2 个。
    降级：执行器不可用（如解释器关闭）时退化为串行执行，保证任务不丢。
    """
    items = list(items)
    results: list[tuple[Any, Any]] = []
    if not items:
        return results
    try:
        executor = _media_executor()
        future_map = {executor.submit(fn, it): it for it in items}
    except Exception:  # noqa: BLE001 执行器异常 → 退化为串行（保持既有行为，不丢任务）
        for item in items:
            try:
                res: Any = fn(item)
            except Exception as exc:  # noqa: BLE001
                res = exc
            results.append((item, res))
            if on_result is not None:
                on_result(item, res)
        return results
    for fut in as_completed(future_map):
        item = future_map[fut]
        try:
            res = fut.result()
        except Exception as exc:  # noqa: BLE001 单任务异常收集，不拖垮整批
            res = exc
        results.append((item, res))
        if on_result is not None:
            on_result(item, res)
    return results


def new_cancel() -> threading.Event:
    return threading.Event()
