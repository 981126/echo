"""R-241: 卡片缓存精确版本键（videos.updated_at / platform_post_stats.updated_at）+ 任务轮询索引。

Revision ID: r241perf
Revises: r239douyincred
Create Date: 2026-10-30
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "r241perf"
down_revision = "r239douyincred"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "videos",
        sa.Column(
            "updated_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
    )
    op.add_column(
        "platform_post_stats",
        sa.Column(
            "updated_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
    )
    op.create_index(
        "ix_background_tasks_status_created",
        "background_tasks",
        ["status", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_background_tasks_status_created", table_name="background_tasks")
    op.drop_column("platform_post_stats", "updated_at")
    op.drop_column("videos", "updated_at")
