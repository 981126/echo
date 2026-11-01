"""R-244: douyin_post_metrics 新增观众画像/受众兴趣两列（数据看板）。

背景：数据看板「观众分析」需要 TikHub creator_v2 的
`fetch_item_audience_portrait`（性别/年龄/活跃/地域）与
`fetch_item_audience_others`（受众兴趣/关注热词）的原始数据。
为复用现有按天快照表，直接在 `douyin_post_metrics` 上加两个 TEXT JSON 列，
不新增表（表数量仍 38 张）。

Revision ID: r244dashboard
Revises: r242transcriptuniq
Create Date: 2026-11-01
"""

from __future__ import annotations

from alembic import op

revision = "r244dashboard"
down_revision = "r242transcriptuniq"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE douyin_post_metrics ADD COLUMN audience_portrait TEXT NOT NULL DEFAULT '{}'"
    )
    op.execute(
        "ALTER TABLE douyin_post_metrics ADD COLUMN audience_others TEXT NOT NULL DEFAULT '{}'"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE douyin_post_metrics DROP COLUMN audience_others")
    op.execute("ALTER TABLE douyin_post_metrics DROP COLUMN audience_portrait")
