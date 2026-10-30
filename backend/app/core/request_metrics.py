"""R-240：请求耗时与慢 SQL 观测（只读中间件，不改变业务响应）。

背景：全后端此前没有任何请求耗时/慢查询埋点，「接口慢」只能靠外部 profiling 猜。
本模块提供最小可用观测：
- 每个 HTTP 响应带 `X-Response-Time` 头（毫秒，值为响应开始写出前已耗时＝服务端处理耗时，
  流式响应如 SSE 则是首字节耗时）；
- 单请求耗时 ≥ SLOW_REQUEST_MS 时写一条 warning 日志（方法/路径/状态/耗时/本请求 SQL 条数）；
- SQL 条数用 SQLAlchemy `before_cursor_execute` 事件在 ContextVar 里累加：中间件把同一个
  可变 dict 放进 ContextVar，anyio 把 context 复制进工作线程后事件回调能读到同一个 dict，
  因此同步 def 端点里的 DB 调用也能被计入（开销只有一次 dict 自增）。
"""

from __future__ import annotations

import time
from contextvars import ContextVar
from typing import Any

from sqlalchemy import event
from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from .log import get_logger

log = get_logger("http")

# 慢请求阈值：README 的接口基线是 ms 级，≥500ms 即用户可感知
SLOW_REQUEST_MS = 500
# 静态资源/文档不统计（封面缩略图按需生成、SSE 长连接不按普通请求算）
# 注意：_SKIP_PREFIXES = 完全跳过（无 X-Response-Time、无慢日志）；
#       _SKIP_PATHS  = 仍带响应头，只是不写慢日志（/health 与 SSE 长连接/chat 流）。
_SKIP_PREFIXES = ("/covers", "/media/", "/uploads", "/docs", "/redoc", "/openapi.json")
_SKIP_PATHS = ("/health", "/api/events", "/api/chat/stream", "/favicon.ico")

_SQL_STATE: ContextVar[dict[str, int] | None] = ContextVar("echo_sql_state", default=None)
_INSTALLED = False


def install_sql_counter(engine: Any) -> None:
    """把「本请求 SQL 条数」统计挂到 SQLAlchemy 引擎（幂等）。"""
    global _INSTALLED
    if _INSTALLED:
        return

    @event.listens_for(engine, "before_cursor_execute")
    def _on_execute(conn, cursor, statement, parameters, context, executemany):  # noqa: ANN001, ARG001
        state = _SQL_STATE.get()
        if state is not None:
            state["n"] += 1

    _INSTALLED = True


class RequestTimingMiddleware:
    """纯 ASGI 中间件（不用 BaseHTTPMiddleware，避免多包一层任务与流式响应问题）。"""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        path = str(scope.get("path", ""))
        if any(path.startswith(p) for p in _SKIP_PREFIXES):
            await self.app(scope, receive, send)
            return

        state: dict[str, int] = {"n": 0}
        token = _SQL_STATE.set(state)
        started = time.perf_counter()
        status = 0

        async def send_wrapper(message: Message) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = int(message.get("status", 0))
                elapsed_ms = (time.perf_counter() - started) * 1000
                MutableHeaders(scope=message)["X-Response-Time"] = f"{elapsed_ms:.1f}"
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            _SQL_STATE.reset(token)
            elapsed_ms = (time.perf_counter() - started) * 1000
            if path not in _SKIP_PATHS and elapsed_ms >= SLOW_REQUEST_MS:
                log.warning(
                    "慢请求 %s %s status=%s %.0fms sql=%d",
                    scope.get("method", ""),
                    path,
                    status or 500,  # 未捕获异常由外层 ServerErrorMiddleware 生成 500 响应，这里兜底标注
                    elapsed_ms,
                    state["n"],
                )


__all__ = ["RequestTimingMiddleware", "install_sql_counter", "SLOW_REQUEST_MS"]
