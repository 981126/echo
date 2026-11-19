"""R-265: 转写分句时间轴 + 作品时长列（并回填存量时长）。

Revision ID: r265timeline
Revises: r263authorprompt2
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

from app.services.post_meta import parse_duration_seconds

revision = "r265timeline"
down_revision = "r263authorprompt2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("transcripts", sa.Column("sentences", sa.Text(), nullable=False, server_default="[]"))
    op.add_column("transcripts", sa.Column("timeline_source", sa.String(20), nullable=False, server_default=""))
    op.add_column(
        "transcripts", sa.Column("timeline_precision", sa.String(20), nullable=False, server_default="none")
    )
    op.add_column("platform_posts", sa.Column("duration_seconds", sa.Integer(), nullable=True))

    # 存量回填：raw 里都有 duration（毫秒），解析失败保持 NULL（复盘显示「时长未知」）。
    conn = op.get_bind()
    rows = conn.execute(sa.text("SELECT id, raw FROM platform_posts")).fetchall()
    updates: list[dict] = []
    for post_id, raw in rows:
        seconds = parse_duration_seconds(raw)
        if seconds is not None:
            updates.append({"id": int(post_id), "seconds": int(seconds)})
    if updates:
        conn.execute(
            sa.text("UPDATE platform_posts SET duration_seconds = :seconds WHERE id = :id"),
            updates,
        )


def downgrade() -> None:
    op.drop_column("platform_posts", "duration_seconds")
    op.drop_column("transcripts", "timeline_precision")
    op.drop_column("transcripts", "timeline_source")
    op.drop_column("transcripts", "sentences")
