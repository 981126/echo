"""人设档案模型：标签+描述，版本化。"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from ..db import Base


class PersonaTag(Base):
    __tablename__ = "persona_tags"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    creator_id: Mapped[int | None] = mapped_column(ForeignKey("creators.id"), nullable=True, index=True)  # 归属主博主（M13，R-029）
    label: Mapped[str] = mapped_column(String(100), index=True)  # 标签，如"犀利敢说"
    description: Mapped[str] = mapped_column(Text, default="")  # 描述
    category: Mapped[str] = mapped_column(String(20), default="style")  # style | topic | redline
    source: Mapped[str] = mapped_column(String(20), default="ai")  # ai | manual
    status: Mapped[str] = mapped_column(String(20), default="suggested")  # suggested|confirmed|rejected
    version: Mapped[int] = mapped_column(Integer, default=1)  # 档案版本
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
