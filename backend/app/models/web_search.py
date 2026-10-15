"""R-227：联网搜索留痕（豆包搜索）。

每次生成/洗稿调用联网搜索时落一行，保留 query 与**完整原始结果**，便于事后核对与额度对账。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from ..core.timeutil import now as _app_now
from ..db import Base


class WebSearchLog(Base):
    __tablename__ = "web_search_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    draft_id: Mapped[int | None] = mapped_column(ForeignKey("drafts.id"), nullable=True, index=True)
    creator_id: Mapped[int | None] = mapped_column(ForeignKey("creators.id"), nullable=True, index=True)
    query: Mapped[str] = mapped_column(String(500), default="")
    source: Mapped[str] = mapped_column(String(20), default="doubao")  # doubao（豆包搜索）
    time_range: Mapped[str] = mapped_column(String(40), default="")
    results: Mapped[str] = mapped_column(Text, default="[]")  # 完整结果 JSON（留痕）
    used: Mapped[str] = mapped_column(Text, default="[]")  # 模型实际引用到的来源 URL/标题 JSON
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_app_now)
