"""灵感随手记（R-186）：一句观察/截图/经历进原料库，可一键发展成选题初稿。"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from ..db import Base
from ..core.timeutil import now as _app_now


class InspirationNote(Base):
    __tablename__ = "inspiration_notes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    creator_id: Mapped[int | None] = mapped_column(ForeignKey("creators.id"), nullable=True, index=True)
    text: Mapped[str] = mapped_column(Text, default="")  # 随手记正文（一句观察/经历）
    image_url: Mapped[str] = mapped_column(String(500), default="")  # 可选配图/聊天截图
    source: Mapped[str] = mapped_column(String(20), default="text")  # text | image | voice
    status: Mapped[str] = mapped_column(String(20), default="new", index=True)  # new | used | archived
    draft_id: Mapped[int | None] = mapped_column(ForeignKey("drafts.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_app_now)
