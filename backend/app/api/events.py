"""SSE 事件推送接口（R-087）：GET /api/events。

前端用 fetch + ReadableStream 携带 X-Access-Token 连接；
服务端推送 task.update（任务进度/完成）与 notification.new（新通知）等事件。
"""

from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from ..services.events import event_generator

router = APIRouter()


@router.get("/events")
def sse_events():
    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
