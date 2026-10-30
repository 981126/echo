"""douyin video review

Revision ID: b237a9c4e801
Revises: 7a6f0c2d9e41
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "b237a9c4e801"
down_revision = "7a6f0c2d9e41"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "douyin_creator_credentials",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("account_id", sa.Integer(), sa.ForeignKey("creator_accounts.id"), nullable=False),
        sa.Column("cookie_value", sa.Text(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("last_validated_at", sa.DateTime(), nullable=True),
        sa.Column("last_success_at", sa.DateTime(), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("account_id", name="uq_douyin_credential_account"),
    )
    op.create_index("ix_douyin_creator_credentials_account_id", "douyin_creator_credentials", ["account_id"])
    op.create_table(
        "douyin_post_metrics",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("post_id", sa.Integer(), sa.ForeignKey("platform_posts.id"), nullable=False),
        sa.Column("snapshot_date", sa.String(10), nullable=False),
        sa.Column("captured_at", sa.DateTime(), nullable=False),
        sa.Column("bounce_2s_rate", sa.Float(), nullable=True),
        sa.Column("finish_5s_rate", sa.Float(), nullable=True),
        sa.Column("finish_rate", sa.Float(), nullable=True),
        sa.Column("avg_play_seconds", sa.Float(), nullable=True),
        sa.Column("cover_click_rate", sa.Float(), nullable=True),
        sa.Column("profile_visits", sa.Integer(), nullable=True),
        sa.Column("follower_gain", sa.Integer(), nullable=True),
        sa.Column("traffic_sources", sa.Text(), nullable=False),
        sa.Column("search_terms", sa.Text(), nullable=False),
        sa.Column("retention_trend", sa.Text(), nullable=False),
        sa.Column("like_trend", sa.Text(), nullable=False),
        sa.Column("bounce_trend", sa.Text(), nullable=False),
        sa.Column("similar_author_trend", sa.Text(), nullable=False),
        sa.Column("trend_reliable", sa.Boolean(), nullable=False),
        sa.Column("raw", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("post_id", "snapshot_date", name="uq_douyin_post_metric_day"),
    )
    op.create_index("ix_douyin_post_metrics_post_date", "douyin_post_metrics", ["post_id", "snapshot_date"])
    op.create_index("ix_douyin_post_metrics_snapshot_date", "douyin_post_metrics", ["snapshot_date"])
    op.create_table(
        "douyin_reference_videos",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("external_post_id", sa.String(200), nullable=False),
        sa.Column("source", sa.String(30), nullable=False),
        sa.Column("source_label", sa.String(30), nullable=False),
        sa.Column("author_id", sa.String(200), nullable=False),
        sa.Column("author_nickname", sa.String(100), nullable=False),
        sa.Column("author_followers", sa.Integer(), nullable=True),
        sa.Column("title", sa.String(500), nullable=False),
        sa.Column("cover_url", sa.String(1000), nullable=False),
        sa.Column("video_url", sa.String(1000), nullable=False),
        sa.Column("publish_time", sa.DateTime(), nullable=True),
        sa.Column("duration_seconds", sa.Integer(), nullable=True),
        sa.Column("plays", sa.Integer(), nullable=True),
        sa.Column("likes", sa.Integer(), nullable=True),
        sa.Column("comments", sa.Integer(), nullable=True),
        sa.Column("shares", sa.Integer(), nullable=True),
        sa.Column("category_id", sa.String(40), nullable=False),
        sa.Column("keyword", sa.String(200), nullable=False),
        sa.Column("top_comments", sa.Text(), nullable=False),
        sa.Column("analysis", sa.Text(), nullable=False),
        sa.Column("analyzed_at", sa.DateTime(), nullable=True),
        sa.Column("raw", sa.Text(), nullable=False),
        sa.Column("first_seen_at", sa.DateTime(), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("external_post_id", name="uq_douyin_reference_post"),
    )
    op.create_index("ix_douyin_reference_source_time", "douyin_reference_videos", ["source", "publish_time"])
    op.create_index("ix_douyin_reference_author", "douyin_reference_videos", ["author_id"])
    op.create_table(
        "video_reviews",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("account_id", sa.Integer(), sa.ForeignKey("creator_accounts.id"), nullable=False),
        sa.Column("post_id", sa.Integer(), sa.ForeignKey("platform_posts.id"), nullable=False),
        sa.Column("task_id", sa.Integer(), sa.ForeignKey("background_tasks.id"), nullable=True),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("input_fingerprint", sa.String(64), nullable=False),
        sa.Column("rule_version", sa.String(20), nullable=False),
        sa.Column("comparison_count", sa.Integer(), nullable=False),
        sa.Column("comparison_post_ids", sa.Text(), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("overall_result", sa.String(30), nullable=False),
        sa.Column("metrics_snapshot", sa.Text(), nullable=False),
        sa.Column("homepage_analysis", sa.Text(), nullable=False),
        sa.Column("new_topics", sa.Text(), nullable=False),
        sa.Column("warnings", sa.Text(), nullable=False),
        sa.Column("model_name", sa.String(120), nullable=False),
        sa.Column("prompt_version", sa.Integer(), nullable=True),
        sa.Column("error", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_video_reviews_post_created", "video_reviews", ["post_id", "created_at"])
    op.create_index("ix_video_reviews_account_id", "video_reviews", ["account_id"])
    op.create_index("ix_video_reviews_input_fingerprint", "video_reviews", ["input_fingerprint"])
    op.create_table(
        "video_review_findings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("review_id", sa.Integer(), sa.ForeignKey("video_reviews.id"), nullable=False),
        sa.Column("dimension", sa.String(20), nullable=False),
        sa.Column("rule_key", sa.String(60), nullable=False),
        sa.Column("title", sa.String(300), nullable=False),
        sa.Column("judgement_type", sa.String(20), nullable=False),
        sa.Column("conclusion", sa.Text(), nullable=False),
        sa.Column("metric_evidence", sa.Text(), nullable=False),
        sa.Column("content_evidence", sa.Text(), nullable=False),
        sa.Column("comparison_post_ids", sa.Text(), nullable=False),
        sa.Column("suggestion", sa.Text(), nullable=False),
        sa.Column("target_metric", sa.String(30), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_video_review_findings_review", "video_review_findings", ["review_id", "sort_order"])
    op.create_table(
        "video_topic_recommendations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("review_id", sa.Integer(), sa.ForeignKey("video_reviews.id"), nullable=False),
        sa.Column("parent_id", sa.Integer(), sa.ForeignKey("video_topic_recommendations.id"), nullable=True),
        sa.Column("role", sa.String(20), nullable=False),
        sa.Column("rank", sa.Integer(), nullable=False),
        sa.Column("topic", sa.String(500), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("fit_reason", sa.Text(), nullable=False),
        sa.Column("evidence", sa.Text(), nullable=False),
        sa.Column("outline", sa.Text(), nullable=False),
        sa.Column("opening_line", sa.Text(), nullable=False),
        sa.Column("target_metric", sa.String(30), nullable=False),
        sa.Column("follow_up_role", sa.String(40), nullable=False),
        sa.Column("source_types", sa.Text(), nullable=False),
        sa.Column("score", sa.Float(), nullable=False),
        sa.Column("score_detail", sa.Text(), nullable=False),
        sa.Column("adopted_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("review_id", "role", "rank", name="uq_video_topic_position"),
    )
    op.create_index("ix_video_topic_review", "video_topic_recommendations", ["review_id"])
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
    op.execute(
        """
        INSERT INTO ai_prompts (key, version, content, status, note, created_at)
        SELECT 'video_review', 1,
               '只能依据输入证据解释视频表现和整理主题，不得创造数字、评论、经历或证据ID。输出必须符合调用方JSON契约。',
               'enabled', 'R-237 视频复盘默认提示词', NOW()
        WHERE NOT EXISTS (SELECT 1 FROM ai_prompts WHERE key = 'video_review')
        """
    )


def downgrade() -> None:
    op.execute("DELETE FROM ai_prompts WHERE key = 'video_review'")
    for table in (
        "video_improvement_plans",
        "video_topic_recommendations",
        "video_review_findings",
        "video_reviews",
        "douyin_reference_videos",
        "douyin_post_metrics",
        "douyin_creator_credentials",
    ):
        op.drop_table(table)
