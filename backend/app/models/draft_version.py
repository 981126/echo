"""草稿版本留痕模型（R-156）：每次定稿保存一条当前稿快照（正文/标题/封面字/标签）。"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from ..core.timeutil import now as _app_now
from ..db import Base


class DraftVersion(Base):
    __tablename__ = "draft_versions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    draft_id: Mapped[int] = mapped_column(ForeignKey("drafts.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(255), default="")
    cover_text: Mapped[str] = mapped_column(String(100), default="")
    script: Mapped[str] = mapped_column(Text, default="")
    tags: Mapped[str] = mapped_column(Text, default="[]")  # JSON 数组
    source: Mapped[str] = mapped_column(String(20), default="manual")  # manual=手动定稿 | ai_discuss=AI讨论定稿
    note: Mapped[str] = mapped_column(String(200), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_app_now)
