"""模型（公告表结构）：agent 写操作提案与审计（R-147 P2）。

写操作**不再由模型直接执行**：模型的写工具只在这里落一条 `pending` 提案，
作者在对话里点「确认执行」后，服务端才真正执行（入队后台任务或改状态），
并把结果写回本表 —— 这样既有审计，也杜绝"模型自作主张改数据"。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from ..core.timeutil import now as _app_now
from ..db import Base

STATUSES = ("pending", "confirmed", "cancelled", "done", "failed")


class AgentAction(Base):
    __tablename__ = "agent_actions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    conversation_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    message_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    action: Mapped[str] = mapped_column(String(50), index=True)
    payload: Mapped[str] = mapped_column(Text, default="{}")
    preview: Mapped[str] = mapped_column(String(500), default="")
    status: Mapped[str] = mapped_column(String(20), default="pending", index=True)
    result: Mapped[str] = mapped_column(Text, default="")
    error: Mapped[str] = mapped_column(Text, default="")
    task_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_app_now)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
