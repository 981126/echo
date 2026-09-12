"""模型（公告表结构）：迁移记录表（R-144 D）。

轻量替代 Alembic：只记录「哪个迁移名在什么时候被应用过」，用来回答
「这个库到底升到哪一版了」。实际的结构变更仍由 `app/db.py` 里的幂等
`_migrate_*` 函数完成，本表只做记账。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from ..core.timeutil import now as _app_now
from ..db import Base


class SchemaMigration(Base):
    __tablename__ = "schema_migrations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    note: Mapped[str] = mapped_column(String(255), default="")
    applied_at: Mapped[datetime] = mapped_column(DateTime, default=_app_now)
