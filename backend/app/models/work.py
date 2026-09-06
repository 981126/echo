"""跨平台同作品合并（M13+）：同一内容发三个平台 = 一个作品。

- works：一个作品（可能挂在抖音/B站/小红书的多个 platform_posts 下）
- platform_posts.work_id / videos.work_id：归属作品
规则：自动按"同创作者 + 规范化标题相同"合并；作者也可手动把不同标题的素材合并/拆分。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from ..db import Base
from ..core.timeutil import now as _app_now


class Work(Base):
    __tablename__ = "works"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    creator_id: Mapped[int | None] = mapped_column(
        ForeignKey("creators.id"), nullable=True, index=True
    )
    title: Mapped[str] = mapped_column(String(500), default="")
    cover_path: Mapped[str] = mapped_column(String(255), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_app_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=_app_now, onupdate=_app_now
    )
