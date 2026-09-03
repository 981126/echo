"""AI 提示词版本模型（R-021）。"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from ..db import Base


class AiPrompt(Base):
    __tablename__ = "ai_prompts"
    __table_args__ = (UniqueConstraint("key", "version", name="uq_prompt_version"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    key: Mapped[str] = mapped_column(String(40), index=True)  # generation / persona_init / video_tags / persona_updates / review / diff / chat / correct
    version: Mapped[int] = mapped_column(Integer, default=1)
    content: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(20), default="enabled")  # enabled | candidate | archived
    note: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
