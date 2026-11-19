"""R-266: 开头样本表（opening_samples）。

Revision ID: r266openings
Revises: r265timeline
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "r266openings"
down_revision = "r265timeline"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "opening_samples",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("creator_id", sa.Integer(), sa.ForeignKey("creators.id"), nullable=False),
        sa.Column("source_kind", sa.String(20), nullable=False),
        sa.Column("video_id", sa.Integer(), sa.ForeignKey("videos.id"), nullable=False),
        sa.Column("post_id", sa.Integer(), sa.ForeignKey("platform_posts.id"), nullable=True),
        sa.Column("platform", sa.String(20), nullable=False, server_default="douyin"),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("chars", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("hook_type", sa.String(20), nullable=False, server_default="statement"),
        sa.Column("finish_5s_rate", sa.Float(), nullable=True),
        sa.Column("bounce_2s_rate", sa.Float(), nullable=True),
        sa.Column("plays", sa.Integer(), nullable=True),
        sa.Column("likes", sa.Integer(), nullable=True),
        sa.Column("duration_seconds", sa.Integer(), nullable=True),
        sa.Column("published_at", sa.DateTime(), nullable=True),
        sa.Column("rank_score", sa.Float(), nullable=False, server_default="0"),
        sa.Column("polarity", sa.String(20), nullable=False, server_default=""),
        sa.Column("baseline_note", sa.String(200), nullable=False, server_default=""),
        sa.Column("negative_reason", sa.String(200), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("video_id", "source_kind", name="uq_opening_sample_video"),
    )
    op.create_index("ix_opening_samples_creator_id", "opening_samples", ["creator_id"])
    op.create_index(
        "ix_opening_samples_creator_polarity",
        "opening_samples",
        ["creator_id", "source_kind", "polarity"],
    )
    op.create_index(
        "ix_opening_samples_source_score", "opening_samples", ["source_kind", "rank_score"]
    )


def downgrade() -> None:
    op.drop_table("opening_samples")
