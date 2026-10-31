"""R-242: transcripts.video_id 唯一化（清理历史重复 + 唯一索引）。

背景：`Video.transcript` 是 uselist=False、DATABASE.md 写「video_id 唯一」，但 DB 只有普通索引，
历史数据已有 5 个视频各 2 条转写 → 读取哪条不确定。本迁移按「有正文优先 → done 优先 → 最新 id」
每视频保留 1 条，其余删除；随后把普通索引改唯一索引。

Revision ID: r242transcriptuniq
Revises: r241perftz
Create Date: 2026-10-31
"""

from __future__ import annotations

from alembic import op

revision = "r242transcriptuniq"
down_revision = "r241perftz"
branch_labels = None
depends_on = None

# 保留顺序：有正文（corrected/transcript 任一非空）优先 → asr_status=done 优先 → id 最大（最新写入）
_DEDUP_SQL = """
DELETE FROM transcripts t
USING (
    SELECT id,
           row_number() OVER (
               PARTITION BY video_id
               ORDER BY
                   (CASE WHEN coalesce(corrected_text, '') <> ''
                              OR coalesce(transcript_text, '') <> '' THEN 1 ELSE 0 END) DESC,
                   (CASE WHEN asr_status = 'done' THEN 1 ELSE 0 END) DESC,
                   id DESC
           ) AS rn
    FROM transcripts
) ranked
WHERE t.id = ranked.id AND ranked.rn > 1
"""


def upgrade() -> None:
    op.execute(_DEDUP_SQL)
    op.drop_index("ix_transcripts_video_id", table_name="transcripts")
    op.create_index(
        "ix_transcripts_video_id", "transcripts", ["video_id"], unique=True
    )


def downgrade() -> None:
    # 数据清理不可逆；仅恢复非唯一索引结构
    op.drop_index("ix_transcripts_video_id", table_name="transcripts")
    op.create_index("ix_transcripts_video_id", "transcripts", ["video_id"], unique=False)
