"""R-263: 作者内容资产与普通生成运行记录。

Revision ID: r263authorgen
Revises: r255promptdefs
"""

from __future__ import annotations

import json

import sqlalchemy as sa
from alembic import op

from app.services.prompt_catalog import PROMPT_SPECS, default_content

revision = "r263authorgen"
down_revision = "r255promptdefs"
branch_labels = None
depends_on = None


def _legacy_run(draft_id: int, creator_id: int | None, topic: str, rows: list[dict]) -> dict:
    return {
        "creator_id": creator_id,
        "draft_id": draft_id,
        "topic": topic,
        "input_context": "{}",
        "status": "legacy",
        "stage": "done",
        "angles_json": "[]",
        "selected_angle_json": "{}",
        "blueprint_json": "{}",
        "evidence_json": "{}",
        "draft_json": "{}",
        "reviews_json": "[]",
        "attempts_json": json.dumps({"legacy_discussions": rows}, ensure_ascii=False),
        "model_trace_json": "{}",
        "final_script_hash": "",
        "quality_passed": False,
        "error": "旧版结果，未按新质量门禁验证",
    }


def upgrade() -> None:
    op.create_table(
        "author_assets",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("creator_id", sa.Integer(), sa.ForeignKey("creators.id"), nullable=False),
        sa.Column("asset_kind", sa.String(20), nullable=False),
        sa.Column("source_kind", sa.String(20), nullable=False),
        sa.Column("source_id", sa.String(80), nullable=False, server_default=""),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("context_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("evidence_refs", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("quality_score", sa.Float(), nullable=False, server_default="0"),
        sa.Column("usage_stats", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("status", sa.String(20), nullable=False, server_default="candidate"),
        sa.Column("last_used_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("creator_id", "asset_kind", "content_hash", name="uq_author_asset_hash"),
    )
    op.create_index("ix_author_assets_creator_id", "author_assets", ["creator_id"])
    op.create_index("ix_author_assets_asset_kind", "author_assets", ["asset_kind"])
    op.create_index(
        "ix_author_assets_creator_kind_status",
        "author_assets",
        ["creator_id", "asset_kind", "status"],
    )
    op.create_index("ix_author_assets_creator_status", "author_assets", ["creator_id", "status"])
    op.create_table(
        "generation_runs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("creator_id", sa.Integer(), sa.ForeignKey("creators.id"), nullable=False),
        sa.Column("draft_id", sa.Integer(), sa.ForeignKey("drafts.id"), nullable=True),
        sa.Column("topic", sa.Text(), nullable=False),
        sa.Column("input_context", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("stage", sa.String(20), nullable=False, server_default="queued"),
        sa.Column("angles_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("selected_angle_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("blueprint_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("evidence_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("draft_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("reviews_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("attempts_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("model_trace_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("final_script_hash", sa.String(64), nullable=False, server_default=""),
        sa.Column("quality_passed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("error", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_generation_runs_creator_id", "generation_runs", ["creator_id"])
    op.create_index("ix_generation_runs_draft_id", "generation_runs", ["draft_id"])
    op.create_index("ix_generation_runs_status", "generation_runs", ["status"])
    op.create_index("ix_generation_runs_draft_id_id", "generation_runs", ["draft_id", "id"])
    op.create_index("ix_generation_runs_creator_status", "generation_runs", ["creator_id", "status"])
    op.add_column("persona_tags", sa.Column("evidence_refs", sa.Text(), nullable=False, server_default="[]"))
    op.add_column("persona_tags", sa.Column("conditions_json", sa.Text(), nullable=False, server_default="{}"))

    bind = op.get_bind()
    for spec in PROMPT_SPECS:
        exists = bind.execute(
            sa.text("SELECT id FROM ai_prompt_defs WHERE key = :key"), {"key": spec.key}
        ).first()
        content = default_content(spec.key)
        if exists is None:
            bind.execute(
                sa.text(
                    "INSERT INTO ai_prompt_defs (key, title, module, module_label, purpose, category, editable, "
                    "optimizable, llm_feature, entry, default_content, code_ref, sort_order, is_active, created_at, updated_at) "
                    "VALUES (:key, :title, :module, :module_label, :purpose, :category, :editable, :optimizable, "
                    ":llm_feature, :entry, :default_content, :code_ref, :sort_order, true, now(), now())"
                ),
                {
                    "key": spec.key,
                    "title": spec.title,
                    "module": spec.module,
                    "module_label": spec.module_label,
                    "purpose": spec.purpose,
                    "category": spec.category,
                    "editable": spec.editable,
                    "optimizable": spec.optimizable,
                    "llm_feature": spec.llm_feature,
                    "entry": spec.entry,
                    "default_content": content,
                    "code_ref": spec.code_ref,
                    "sort_order": spec.sort_order,
                },
            )
        if spec.category in ("system", "probe") and content.strip():
            has_version = bind.execute(
                sa.text("SELECT id FROM ai_prompts WHERE key = :key LIMIT 1"), {"key": spec.key}
            ).first()
            if has_version is None:
                bind.execute(
                    sa.text(
                        "INSERT INTO ai_prompts (key, version, content, status, note, created_at) "
                        "VALUES (:key, 1, :content, 'enabled', 'R-263 作者生成链路', now())"
                    ),
                    {"key": spec.key, "content": content},
                )
    old_keys_sql = "'generation', 'generation.contract', 'debate_critic_generate', 'debate_revise_generate', 'ideas_angles'"
    bind.execute(sa.text(f"UPDATE ai_prompt_defs SET is_active = false, updated_at = now() WHERE key IN ({old_keys_sql})"))
    bind.execute(sa.text(f"UPDATE ai_prompts SET status = 'archived' WHERE key IN ({old_keys_sql})"))
    bind.execute(sa.text("DELETE FROM app_kv WHERE key IN ('generation_import_count', 'r254_generation_prompt_patched')"))
    drafts = bind.execute(
        sa.text(
            "SELECT id, creator_id, title, source, original_script, script, source_ref "
            "FROM drafts WHERE id IN (SELECT DISTINCT draft_id FROM draft_discussions)"
        )
    ).mappings().all()
    for draft in drafts:
        try:
            source_ref = json.loads(draft["source_ref"] or "{}")
        except (TypeError, ValueError):
            source_ref = {}
        if isinstance(source_ref, dict) and source_ref.get("kind") == "benchmark":
            continue
        is_clear_legacy = (
            draft["source"] == "ai"
            and (not (draft["original_script"] or "").strip()
                 or draft["original_script"] == draft["script"])
        )
        if not is_clear_legacy or draft["creator_id"] is None:
            continue
        rows = bind.execute(
            sa.text(
                "SELECT id, round, actor, kind, content, used_slot, vendor, model_id, created_at "
                "FROM draft_discussions WHERE draft_id = :draft_id ORDER BY id"
            ),
            {"draft_id": draft["id"]},
        ).mappings().all()
        if not rows:
            continue
        serialized = [
            {**dict(row), "created_at": row["created_at"].isoformat() if row["created_at"] else None}
            for row in rows
        ]
        bind.execute(
            sa.text(
                "INSERT INTO generation_runs (creator_id, draft_id, topic, input_context, status, stage, "
                "angles_json, selected_angle_json, blueprint_json, evidence_json, draft_json, reviews_json, "
                "attempts_json, model_trace_json, final_script_hash, quality_passed, error, created_at, updated_at) "
                "VALUES (:creator_id, :draft_id, :topic, :input_context, :status, :stage, :angles_json, "
                ":selected_angle_json, :blueprint_json, :evidence_json, :draft_json, :reviews_json, "
                ":attempts_json, :model_trace_json, :final_script_hash, :quality_passed, :error, now(), now())"
            ),
            _legacy_run(draft["id"], draft["creator_id"], draft["title"] or "", serialized),
        )
        migrated = bind.execute(
            sa.text(
                "SELECT attempts_json FROM generation_runs "
                "WHERE draft_id = :draft_id AND status = 'legacy' ORDER BY id DESC LIMIT 1"
            ),
            {"draft_id": draft["id"]},
        ).scalar()
        try:
            checked = json.loads(migrated or "{}").get("legacy_discussions") or []
        except (TypeError, ValueError, AttributeError):
            checked = []
        if len(checked) != len(rows):
            raise RuntimeError(f"R-263 历史讨论迁移计数不一致：draft_id={draft['id']}")
        bind.execute(
            sa.text("DELETE FROM draft_discussions WHERE draft_id = :draft_id"),
            {"draft_id": draft["id"]},
        )


def downgrade() -> None:
    op.drop_column("persona_tags", "conditions_json")
    op.drop_column("persona_tags", "evidence_refs")
    op.drop_index("ix_generation_runs_creator_status", table_name="generation_runs")
    op.drop_index("ix_generation_runs_draft_id_id", table_name="generation_runs")
    op.drop_index("ix_generation_runs_status", table_name="generation_runs")
    op.drop_index("ix_generation_runs_draft_id", table_name="generation_runs")
    op.drop_index("ix_generation_runs_creator_id", table_name="generation_runs")
    op.drop_table("generation_runs")
    op.drop_index("ix_author_assets_creator_status", table_name="author_assets")
    op.drop_index("ix_author_assets_creator_kind_status", table_name="author_assets")
    op.drop_index("ix_author_assets_asset_kind", table_name="author_assets")
    op.drop_index("ix_author_assets_creator_id", table_name="author_assets")
    op.drop_table("author_assets")
