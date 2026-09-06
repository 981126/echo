"""进程内事件总线（R-087）：SSE 服务端→浏览器推送。

- 单进程部署（uvicorn 单 worker），后台任务跑在 daemon 线程，
  发布时用 loop.call_soon_threadsafe 投递到主事件循环。
- 每个 SSE 连接订阅一个 asyncio.Queue；无订阅者/未连接时发布为空操作。
"""

from __future__ import annotations

import asyncio
import itertools
import json
import time
from typing import Any

_subscribers: dict[int, asyncio.Queue] = {}
_counter = itertools.count(1)
_loop: asyncio.AbstractEventLoop | None = None


def publish(event_type: str, data: dict[str, Any]) -> None:
    """广播事件（线程安全）。event_type: task.update / notification.new 等。"""
    loop = _loop
    if loop is None:
        return
    payload = {"type": event_type, "data": data, "ts": time.time()}
    for sid, q in list(_subscribers.items()):
        try:
            if q.qsize() > 500:  # 慢订阅者丢最旧事件，防积压
                try:
                    q.get_nowait()
                except Exception:  # noqa: BLE001
                    pass
            loop.call_soon_threadsafe(q.put_nowait, payload)
        except RuntimeError:
            pass


async def event_generator():
    """SSE 生成器：每 15s 心跳；事件按 SSE data: 块输出。"""
    global _loop
    _loop = asyncio.get_running_loop()
    sid = next(_counter)
    q: asyncio.Queue = asyncio.Queue(maxsize=1000)
    _subscribers[sid] = q
    try:
        while True:
            try:
                ev = await asyncio.wait_for(q.get(), timeout=15)
            except asyncio.TimeoutError:
                yield ": keep-alive\n\n"
                continue
            yield f"data: {json.dumps(ev, ensure_ascii=False)}\n\n"
    finally:
        _subscribers.pop(sid, None)
