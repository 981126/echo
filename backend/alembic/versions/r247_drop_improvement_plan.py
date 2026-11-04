"""R-247: 删除改进计划（video_improvement_plans 表 + video_topic_recommendations.adopted_at 列）。

背景：R-247 视频复盘页删除「改进计划/修改效果」功能（作者确认），主题「采用」改为直接生成草稿，
不再记录采用状态。线上 0 条计划、0 条 adopted_at，无数据迁移。

Revision ID: r247dropimprove
Revises: r244dashboard
Create Date: 2026-11-04
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "r247dropimprove"
down_revision = "r244dashboard"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # PG 删表自动删除该表的索引与 FK 约束
    op.drop_table("video_improvement_plans")
    op.drop_column("video_topic_recommendations", "adopted_at")


def downgrade() -> None:
    # 结构与 b237a9c4e801（R-237 初建）保持一致
    op.add_column("video_topic_recommendations", sa.Column("adopted_at", sa.DateTime(), nullable=True))
    op.create_table(
        "video_improvement_plans",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("review_id", sa.Integer(), sa.ForeignKey("video_reviews.id"), nullable=False),
        sa.Column("source_post_id", sa.Integer(), sa.ForeignKey("platform_posts.id"), nullable=False),
        sa.Column("recommendation_id", sa.Integer(), sa.ForeignKey("video_topic_recommendations.id"), nullable=True),
        sa.Column("kept_text", sa.Text(), nullable=False),
        sa.Column("changes", sa.Text(), nullable=False),
        sa.Column("target_metrics", sa.Text(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("published_post_id", sa.Integer(), sa.ForeignKey("platform_posts.id"), nullable=True),
        sa.Column("check_result", sa.Text(), nullable=False),
        sa.Column("checked_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_video_improvement_source", "video_improvement_plans", ["source_post_id", "created_at"])
    op.create_index("ix_video_improvement_published", "video_improvement_plans", ["published_post_id"])
