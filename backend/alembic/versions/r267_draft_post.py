"""R-267: 草稿显式绑定云端作品（post_id）。

Revision ID: r267draftpost
Revises: r266openings
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "r267draftpost"
down_revision = "r266openings"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("drafts", sa.Column("post_id", sa.Integer(), nullable=True))
    op.create_foreign_key("fk_drafts_post_id", "drafts", "platform_posts", ["post_id"], ["id"])
    op.create_index("ix_drafts_post_id", "drafts", ["post_id"])


def downgrade() -> None:
    op.drop_index("ix_drafts_post_id", table_name="drafts")
    op.drop_constraint("fk_drafts_post_id", "drafts", type_="foreignkey")
    op.drop_column("drafts", "post_id")
