"""R-241 复核修复：updated_at 库列默认值改为北京时间表达式。

背景：迁移 r241perf 用 `CURRENT_TIMESTAMP` 回填，而本库 `SHOW timezone=Etc/UTC`
→ 历史回填值比 ORM `_app_now()`（北京时间 naive）早 8 小时；虽然当前 max 仍单调（后续
ORM 写入更大）不会漏失效，但与 R-066「统一北京时间」约定不一致，且若 ECHO_TIMEZONE
配置为 UTC 以西时区 / 依赖 raw insert 的库默认值时会漏失效。本迁移只规范「库默认值」，
不改写历史回填值（历史值 < 当前北京时间，单调性安全；改写会带来一次无害的全量失效）。

Revision ID: r241perftz
Revises: r241perf
Create Date: 2026-10-30
"""

from __future__ import annotations

from alembic import op

revision = "r241perftz"
down_revision = "r241perf"
branch_labels = None
depends_on = None

_BEIJING_DEFAULT = "(now() AT TIME ZONE 'Asia/Shanghai')"


def upgrade() -> None:
    op.execute(f"ALTER TABLE videos ALTER COLUMN updated_at SET DEFAULT {_BEIJING_DEFAULT}")
    op.execute(
        f"ALTER TABLE platform_post_stats ALTER COLUMN updated_at SET DEFAULT {_BEIJING_DEFAULT}"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE videos ALTER COLUMN updated_at SET DEFAULT CURRENT_TIMESTAMP")
    op.execute(
        "ALTER TABLE platform_post_stats ALTER COLUMN updated_at SET DEFAULT CURRENT_TIMESTAMP"
    )
