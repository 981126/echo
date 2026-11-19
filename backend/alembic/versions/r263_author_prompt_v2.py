"""R-263: 写作保留适用边界，评审硬问题必须引用正文原句。

Revision ID: r263authorprompt2
Revises: r263authorgen
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

from app.services.generation_pipeline import AUTHOR_REVIEW_SYSTEM, AUTHOR_REVISE_SYSTEM, AUTHOR_WRITE_SYSTEM

revision = "r263authorprompt2"
down_revision = "r263authorgen"
branch_labels = None
depends_on = None

CONTENTS = {
    "author_write": AUTHOR_WRITE_SYSTEM,
    "author_review": AUTHOR_REVIEW_SYSTEM,
    "author_revise": AUTHOR_REVISE_SYSTEM,
}


def upgrade() -> None:
    bind = op.get_bind()
    for key, content in CONTENTS.items():
        bind.execute(sa.text("UPDATE ai_prompts SET status = 'archived' WHERE key = :key AND status = 'enabled'"), {"key": key})
        version = bind.execute(
            sa.text("SELECT COALESCE(MAX(version), 0) + 1 FROM ai_prompts WHERE key = :key"),
            {"key": key},
        ).scalar_one()
        bind.execute(
            sa.text(
                "INSERT INTO ai_prompts (key, version, content, status, note, created_at) "
                "VALUES (:key, :version, :content, 'enabled', "
                "'R-263 写作保留适用边界，评审硬问题引用正文原句', now())"
            ),
            {"key": key, "version": version, "content": content},
        )
        bind.execute(
            sa.text("UPDATE ai_prompt_defs SET default_content = :content, updated_at = now() WHERE key = :key"),
            {"key": key, "content": content},
        )


def downgrade() -> None:
    bind = op.get_bind()
    for key in CONTENTS:
        bind.execute(sa.text("DELETE FROM ai_prompts WHERE key = :key AND status = 'enabled'"), {"key": key})
        bind.execute(
            sa.text(
                "UPDATE ai_prompts SET status = 'enabled' WHERE key = :key "
                "AND version = (SELECT MAX(version) FROM ai_prompts WHERE key = :key)"
            ),
            {"key": key},
        )
