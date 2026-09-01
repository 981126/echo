"""脚本草稿模型：工作台改写、AI 原稿留底（供改稿差异分析）。"""
import json
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from ..db import Base


class Draft(Base):
    __tablename__ = "drafts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    video_id: Mapped[int | None] = mapped_column(ForeignKey("videos.id"), nullable=True, index=True)
    title: Mapped[str] = mapped_column(String(255), default="")
    cover_text: Mapped[str] = mapped_column(String(100), default="")
    script: Mapped[str] = mapped_column(Text, default="")
    platform_shells: Mapped[str] = mapped_column(Text, default="{}")  # JSON：各平台外壳
    source: Mapped[str] = mapped_column(String(20), default="manual")  # manual | ai
    original_script: Mapped[str] = mapped_column(Text, default="")  # AI 原稿（改稿差异分析用）
    status: Mapped[str] = mapped_column(String(20), default="draft")  # draft|used|archived
    version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    def shells_dict(self) -> dict:
        try:
            data = json.loads(self.platform_shells or "{}")
            return data if isinstance(data, dict) else {}
        except json.JSONDecodeError:
            return {}
