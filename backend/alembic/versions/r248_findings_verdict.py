"""R-248: video_review_findings 新增 verdict 列（归因方向，程序判定）。

背景：R-248「这条视频为什么好或差」改为 AI 归因诊断后，方向（好在哪/差在哪/
影响有限/无法判断）由程序按真实指标 state 判定，不交给 AI。历史行不回填，默认空串
（前端无徽标，兼容）。

Revision ID: r248verdict
Revises: r247dropimprove
Create Date: 2026-11-04
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "r248verdict"
down_revision = "r247dropimprove"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "video_review_findings",
        sa.Column("verdict", sa.String(10), nullable=False, server_default=""),
    )


def downgrade() -> None:
    op.drop_column("video_review_findings", "verdict")
