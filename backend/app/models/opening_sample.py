"""R-266：开头样本（首句 × 真实指标），用于生成时参考与程序化开头检查。"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from ..core.timeutil import now as _app_now
from ..db import Base


class OpeningSample(Base):
    __tablename__ = "opening_samples"
    __table_args__ = (
        UniqueConstraint("video_id", "source_kind", name="uq_opening_sample_video"),
        Index("ix_opening_samples_creator_polarity", "creator_id", "source_kind", "polarity"),
        Index("ix_opening_samples_source_score", "source_kind", "rank_score"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    creator_id: Mapped[int] = mapped_column(ForeignKey("creators.id"), nullable=False, index=True)
    source_kind: Mapped[str] = mapped_column(String(20), nullable=False)  # own | peer
    video_id: Mapped[int] = mapped_column(ForeignKey("videos.id"), nullable=False)
    post_id: Mapped[int | None] = mapped_column(ForeignKey("platform_posts.id"), nullable=True)
    platform: Mapped[str] = mapped_column(String(20), nullable=False, default="douyin")
    text: Mapped[str] = mapped_column(Text, nullable=False)
    chars: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    hook_type: Mapped[str] = mapped_column(String(20), nullable=False, default="statement")
    finish_5s_rate: Mapped[float | None] = mapped_column(Float, nullable=True)
    bounce_2s_rate: Mapped[float | None] = mapped_column(Float, nullable=True)
    plays: Mapped[int | None] = mapped_column(Integer, nullable=True)
    likes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    duration_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    rank_score: Mapped[float] = mapped_column(Float, nullable=False, default=0)
    polarity: Mapped[str] = mapped_column(String(20), nullable=False, default="")
    baseline_note: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    negative_reason: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_app_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=_app_now, onupdate=_app_now
    )
