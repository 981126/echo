"""r255 prompt defs

R-255：AI 提示词注册表 `ai_prompt_defs`（一行一条提示词，含中文模块名与中文用途说明）。

- 建表 + key 唯一索引 + module 索引；
- 种子：遍历 `prompt_catalog.PROMPT_SPECS`（45 条 = 34 条系统提示词/探针 + 11 条程序固定契约），
  写入元数据与代码默认正文；对系统提示词/探针，若 `ai_prompts` 中该 key 完全没有行，
  再补一条 v1 enabled（note 留痕）。已有版本一律不动（不覆盖作者改过的内容）。
- 降级只删注册表，不删 `ai_prompts` 中新增的 v1 行（回滚代码后旧逻辑不读它们，删除反而有误删风险）。

Revision ID: r255promptdefs
Revises: r248verdict
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

from app.services.prompt_catalog import PROMPT_SPECS, default_content

revision = "r255promptdefs"
down_revision = "r248verdict"
branch_labels = None
depends_on = None

prompt_defs = sa.table(
    "ai_prompt_defs",
    sa.column("id", sa.Integer),
    sa.column("key", sa.String),
    sa.column("title", sa.String),
    sa.column("module", sa.String),
    sa.column("module_label", sa.String),
    sa.column("purpose", sa.Text),
    sa.column("category", sa.String),
    sa.column("editable", sa.Boolean),
    sa.column("optimizable", sa.Boolean),
    sa.column("llm_feature", sa.String),
    sa.column("entry", sa.Text),
    sa.column("default_content", sa.Text),
    sa.column("code_ref", sa.Text),
    sa.column("sort_order", sa.Integer),
    sa.column("is_active", sa.Boolean),
    sa.column("created_at", sa.DateTime),
    sa.column("updated_at", sa.DateTime),
)

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

SEED_NOTE = "系统默认（R-255 统一入库补种）"


def upgrade() -> None:
    op.create_table(
        "ai_prompt_defs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("key", sa.String(64), nullable=False),
        sa.Column("title", sa.String(80), nullable=False),
        sa.Column("module", sa.String(40), nullable=False),
        sa.Column("module_label", sa.String(40), nullable=False),
        sa.Column("purpose", sa.Text(), nullable=False),
        sa.Column("category", sa.String(20), nullable=False),
        sa.Column("editable", sa.Boolean(), nullable=False),
        sa.Column("optimizable", sa.Boolean(), nullable=False),
        sa.Column("llm_feature", sa.String(40), nullable=False),
        sa.Column("entry", sa.Text(), nullable=False),
        sa.Column("default_content", sa.Text(), nullable=False),
        sa.Column("code_ref", sa.Text(), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    # 模型里 key/module 是 index=True（key 唯一），这里显式建同名索引，保证 ORM 与迁移一致
    op.create_index("ix_ai_prompt_defs_key", "ai_prompt_defs", ["key"], unique=True)
    op.create_index("ix_ai_prompt_defs_module", "ai_prompt_defs", ["module"], unique=False)

    connection = op.get_bind()
    for spec in PROMPT_SPECS:
        exists = connection.execute(
            sa.select(prompt_defs.c.id).where(prompt_defs.c.key == spec.key).limit(1)
        ).first()
        if exists is not None:
            continue
        content = default_content(spec.key)
        connection.execute(
            prompt_defs.insert().values(
                key=spec.key,
                title=spec.title,
                module=spec.module,
                module_label=spec.module_label,
                purpose=spec.purpose,
                category=spec.category,
                editable=spec.editable,
                optimizable=spec.optimizable,
                llm_feature=spec.llm_feature,
                entry=spec.entry,
                default_content=content,
                code_ref=spec.code_ref,
                sort_order=spec.sort_order,
                is_active=True,
                created_at=sa.func.now(),
                updated_at=sa.func.now(),
            )
        )
        if spec.category not in ("system", "probe") or not content.strip():
            continue
        has_version = connection.execute(
            sa.select(prompts.c.id).where(prompts.c.key == spec.key).limit(1)
        ).first()
        if has_version is None:
            connection.execute(
                prompts.insert().values(
                    key=spec.key,
                    version=1,
                    content=content,
                    status="enabled",
                    note=SEED_NOTE,
                    created_at=sa.func.now(),
                )
            )


def downgrade() -> None:
    op.drop_index("ix_ai_prompt_defs_module", table_name="ai_prompt_defs")
    op.drop_index("ix_ai_prompt_defs_key", table_name="ai_prompt_defs")
    op.drop_table("ai_prompt_defs")
