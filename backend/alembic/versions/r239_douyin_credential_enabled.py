"""R-239: douyin creator credential enabled switch

Revision ID: r239douyincred
Revises: b237a9c4e801
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "r239douyincred"
down_revision = "b237a9c4e801"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "douyin_creator_credentials",
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
    )


def downgrade() -> None:
    op.drop_column("douyin_creator_credentials", "enabled")
