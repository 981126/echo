"""作者内容资产与普通生成运行记录（R-263）。"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from ..core.timeutil import now as _app_now
from ..db import Base


class AuthorAsset(Base):
    __tablename__ = "author_assets"
    __table_args__ = (
        UniqueConstraint("creator_id", "asset_kind", "content_hash", name="uq_author_asset_hash"),
        Index("ix_author_assets_creator_kind_status", "creator_id", "asset_kind", "status"),
        Index("ix_author_assets_creator_status", "creator_id", "status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    creator_id: Mapped[int] = mapped_column(ForeignKey("creators.id"), nullable=False, index=True)
    asset_kind: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    source_kind: Mapped[str] = mapped_column(String(20), nullable=False)
    source_id: Mapped[str] = mapped_column(String(80), nullable=False, default="")
    content: Mapped[str] = mapped_column(Text, nullable=False)
    context_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    evidence_refs: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    quality_score: Mapped[float] = mapped_column(Float, nullable=False, default=0)
    usage_stats: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="candidate")
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_app_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_app_now, onupdate=_app_now)


class GenerationRun(Base):
    __tablename__ = "generation_runs"
    __table_args__ = (
        Index("ix_generation_runs_draft_id_id", "draft_id", "id"),
        Index("ix_generation_runs_creator_status", "creator_id", "status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    creator_id: Mapped[int] = mapped_column(ForeignKey("creators.id"), nullable=False, index=True)
    draft_id: Mapped[int | None] = mapped_column(ForeignKey("drafts.id"), nullable=True, index=True)
    topic: Mapped[str] = mapped_column(Text, nullable=False)
    input_context: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    status: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    stage: Mapped[str] = mapped_column(String(20), nullable=False, default="queued")
    angles_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    selected_angle_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    blueprint_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    evidence_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    draft_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    reviews_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    attempts_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    model_trace_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    final_script_hash: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    quality_passed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    error: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_app_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_app_now, onupdate=_app_now)
