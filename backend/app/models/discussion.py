"""脚本讨论留痕模型（R-023）：双模型围绕草稿的每轮讨论消息。"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from ..db import Base
from ..core.timeutil import now as _app_now


class DraftDiscussion(Base):
    __tablename__ = "draft_discussions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    draft_id: Mapped[int] = mapped_column(ForeignKey("drafts.id", ondelete="CASCADE"), index=True)
    round: Mapped[int] = mapped_column(Integer, default=0)  # 0=初稿
    actor: Mapped[str] = mapped_column(String(20))  # deepseek | kimi | system
    kind: Mapped[str] = mapped_column(String(20))  # draft | critique | revise
    content: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_app_now)
