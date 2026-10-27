"""runtime assets

Revision ID: 7a6f0c2d9e41
Revises: 1657ed6f1d2e
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

from app.services.prompt_service import PROMPT_META, default_content

revision = "7a6f0c2d9e41"
down_revision = "1657ed6f1d2e"
branch_labels = None
depends_on = None

prompts = sa.table(
    "ai_prompts",
    sa.column("id", sa.Integer),
    sa.column("key", sa.String),
    sa.column("version", sa.Integer),
    sa.column("content", sa.Text),
    sa.column("status", sa.String),
    sa.column("note", sa.Text),
    sa.column("created_at", sa.DateTime),
)

VIEWS = {
    "v_videos": """SELECT id, title, filename, status, platforms, main_topics, tags,
        is_ad, tags_confirmed, published_at, planned_publish_at, created_at FROM videos""",
    "v_drafts": """SELECT id, title, cover_text, source, status, version,
        length(COALESCE(script, '')) AS script_len,
        substr(COALESCE(script, ''), 1, 120) AS script_preview,
        prompt_version, persona_version, created_at, updated_at FROM drafts""",
    "v_feedback": """SELECT id, draft_id, rating, liked, hook_score, pace_score,
        ending_score, style_score, substr(COALESCE(comment, ''), 1, 120) AS comment, created_at
        FROM feedback""",
    "v_persona_tags": """SELECT id, label, description, dimension, category, source, status,
        version, created_at FROM persona_tags""",
    "v_topics": """SELECT id, run_date, slot, title, platform, score, reason, draft_id, created_at
        FROM topic_candidates""",
    "v_ideas": """SELECT id, source, platform, title, post_title, likes, used, snapshot_date, created_at
        FROM topic_ideas""",
    "v_metrics": """SELECT m.id, m.video_id, v.title AS video_title, m.snapshot_date,
        m.plays, m.likes, m.favorites, m.comments, m.followers_gained, m.source
        FROM metrics_snapshots m LEFT JOIN videos v ON v.id = m.video_id""",
    "v_platform_posts": """SELECT p.id, p.platform, p.title, p.publish_time, p.is_ad, p.work_id,
        p.local_video_id, c.name AS creator_name, c.kind AS creator_kind
        FROM platform_posts p LEFT JOIN creator_accounts a ON a.id = p.account_id
        LEFT JOIN creators c ON c.id = a.creator_id""",
}


def enabled_prompt(key: str):
    return (
        sa.select(prompts.c.content)
        .where(prompts.c.key == key, prompts.c.status == "enabled")
        .order_by(prompts.c.version.desc())
        .limit(1)
    )


def save_default(connection, key: str, note: str) -> None:
    connection.execute(
        prompts.update().where(prompts.c.key == key, prompts.c.status == "enabled").values(status="archived")
    )
    version = connection.execute(sa.select(sa.func.max(prompts.c.version)).where(prompts.c.key == key)).scalar() or 0
    connection.execute(
        prompts.insert().values(
            key=key,
            version=version + 1,
            content=default_content(key),
            status="enabled",
            created_at=sa.func.now(),
            note=note,
        )
    )


def upgrade() -> None:
    connection = op.get_bind()
    for key in PROMPT_META:
        exists = connection.execute(sa.select(prompts.c.id).where(prompts.c.key == key).limit(1)).first()
        if exists is None:
            connection.execute(
                prompts.insert().values(
                    key=key,
                    version=1,
                    content=default_content(key),
                    status="enabled",
                    created_at=sa.func.now(),
                    note="系统默认",
                )
            )
    for key in ("persona_merge", "persona_updates"):
        content = connection.execute(enabled_prompt(key)).scalar() or ""
        if "core_dna" not in content or "发布风险" not in content:
            save_default(connection, key, "R-182 人设四层重构")
    content = connection.execute(enabled_prompt("generation")).scalar() or ""
    if "先破后立" in content or "本次创作模式" not in content:
        save_default(connection, "generation", "R-183 生成提示词退回方向盘")
    for key in PROMPT_META:
        if connection.execute(enabled_prompt(key)).first() is None:
            save_default(connection, key, "无启用版本，兜底启用代码默认")
    for name, body in VIEWS.items():
        op.execute(f"CREATE VIEW {name} AS {body}")


def downgrade() -> None:
    for name in reversed(VIEWS):
        op.execute(f"DROP VIEW IF EXISTS {name}")
    op.execute("DELETE FROM ai_prompts")
