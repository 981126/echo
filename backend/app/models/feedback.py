"""反馈模型：草稿评分/喜欢（显式信号，辅助人设学习）。"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, Text
from sqlalchemy.orm import Mapped, mapped_column

from ..db import Base


class Feedback(Base):
    __tablename__ = "feedback"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    draft_id: Mapped[int] = mapped_column(ForeignKey("drafts.id"), index=True)
    liked: Mapped[bool | None] = mapped_column(Boolean, nullable=True)  # 用/不用
    rating: Mapped[int | None] = mapped_column(Integer, nullable=True)  # 1-5 星
    comment: Mapped[str] = mapped_column(Text, default="")
    hook_score: Mapped[int | None] = mapped_column(Integer, nullable=True)  # 开头钩子 1-5（R-030②）
    pace_score: Mapped[int | None] = mapped_column(Integer, nullable=True)  # 内容节奏 1-5
    ending_score: Mapped[int | None] = mapped_column(Integer, nullable=True)  # 结尾引导 1-5
    style_score: Mapped[int | None] = mapped_column(Integer, nullable=True)  # 像不像作者 1-5
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
