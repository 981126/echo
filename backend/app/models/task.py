"""后台任务模型：长任务状态跟踪（批量转写/人设分析等）。"""

from __future__ import annotations

import json
from datetime import datetime

from sqlalchemy import DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from ..db import Base
from ..core.timeutil import now as _app_now


class BackgroundTask(Base):
    __tablename__ = "background_tasks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    kind: Mapped[str] = mapped_column(String(50), index=True)  # import_video | persona_init
    status: Mapped[str] = mapped_column(String(20), default="pending")  # pending|running|done|failed
    progress: Mapped[int] = mapped_column(Integer, default=0)  # 0-100
    note: Mapped[str] = mapped_column(String(255), default="")  # 阶段说明（R-081：下载中/转写中等）
    payload: Mapped[str] = mapped_column(Text, default="{}")
    error: Mapped[str] = mapped_column(Text, default="")
    result: Mapped[str] = mapped_column(Text, default="")  # 任务结果 JSON（R-116）
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_app_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=_app_now, onupdate=_app_now
    )

    def payload_dict(self) -> dict:
        try:
            return json.loads(self.payload or "{}")
        except json.JSONDecodeError:
            return {}
