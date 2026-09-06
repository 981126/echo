"""通知模型：异步任务完成/失败提醒（R-019）。"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from ..db import Base
from ..core.timeutil import now as _app_now


class Notification(Base):
    __tablename__ = "notifications"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    kind: Mapped[str] = mapped_column(String(30), index=True)  # import_video | persona_init | daily_pipeline | diff_analysis | generate_draft
    status: Mapped[str] = mapped_column(String(10), default="done")  # done | failed
    title: Mapped[str] = mapped_column(String(200), default="")
    message: Mapped[str] = mapped_column(Text, default="")
    target: Mapped[str] = mapped_column(String(255), default="/home")  # 前端 hash 路径
    read: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_app_now)
