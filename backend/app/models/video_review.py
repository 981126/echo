from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from ..core.timeutil import now as _app_now
from ..db import Base


class DouyinCreatorCredential(Base):
    __tablename__ = "douyin_creator_credentials"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("creator_accounts.id"), unique=True, index=True)
    cookie_value: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(20), default="missing")
    last_validated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_error: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_app_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_app_now, onupdate=_app_now)


class DouyinPostMetric(Base):
    __tablename__ = "douyin_post_metrics"
    __table_args__ = (UniqueConstraint("post_id", "snapshot_date", name="uq_douyin_post_metric_day"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    post_id: Mapped[int] = mapped_column(ForeignKey("platform_posts.id"), index=True)
    snapshot_date: Mapped[str] = mapped_column(String(10), index=True)
    captured_at: Mapped[datetime] = mapped_column(DateTime, default=_app_now)
    bounce_2s_rate: Mapped[float | None] = mapped_column(Float, nullable=True)
    finish_5s_rate: Mapped[float | None] = mapped_column(Float, nullable=True)
    finish_rate: Mapped[float | None] = mapped_column(Float, nullable=True)
    avg_play_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)
    cover_click_rate: Mapped[float | None] = mapped_column(Float, nullable=True)
    profile_visits: Mapped[int | None] = mapped_column(Integer, nullable=True)
    follower_gain: Mapped[int | None] = mapped_column(Integer, nullable=True)
    traffic_sources: Mapped[str] = mapped_column(Text, default="{}")
    search_terms: Mapped[str] = mapped_column(Text, default="[]")
    retention_trend: Mapped[str] = mapped_column(Text, default="[]")
    like_trend: Mapped[str] = mapped_column(Text, default="[]")
    bounce_trend: Mapped[str] = mapped_column(Text, default="[]")
    similar_author_trend: Mapped[str] = mapped_column(Text, default="{}")
    trend_reliable: Mapped[bool] = mapped_column(Boolean, default=False)
    raw: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_app_now)


class DouyinReferenceVideo(Base):
    __tablename__ = "douyin_reference_videos"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    external_post_id: Mapped[str] = mapped_column(String(200), unique=True, index=True)
    source: Mapped[str] = mapped_column(String(30), default="low_fan_billboard")
    source_label: Mapped[str] = mapped_column(String(30), default="")
    author_id: Mapped[str] = mapped_column(String(200), default="", index=True)
    author_nickname: Mapped[str] = mapped_column(String(100), default="")
    author_followers: Mapped[int | None] = mapped_column(Integer, nullable=True)
    title: Mapped[str] = mapped_column(String(500), default="")
    cover_url: Mapped[str] = mapped_column(String(1000), default="")
    video_url: Mapped[str] = mapped_column(String(1000), default="")
    publish_time: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    duration_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    plays: Mapped[int | None] = mapped_column(Integer, nullable=True)
    likes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    comments: Mapped[int | None] = mapped_column(Integer, nullable=True)
    shares: Mapped[int | None] = mapped_column(Integer, nullable=True)
    category_id: Mapped[str] = mapped_column(String(40), default="")
    keyword: Mapped[str] = mapped_column(String(200), default="")
    top_comments: Mapped[str] = mapped_column(Text, default="[]")
    analysis: Mapped[str] = mapped_column(Text, default="{}")
    analyzed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    raw: Mapped[str] = mapped_column(Text, default="{}")
    first_seen_at: Mapped[datetime] = mapped_column(DateTime, default=_app_now)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime, default=_app_now, onupdate=_app_now)


class VideoReview(Base):
    __tablename__ = "video_reviews"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("creator_accounts.id"), index=True)
    post_id: Mapped[int] = mapped_column(ForeignKey("platform_posts.id"), index=True)
    task_id: Mapped[int | None] = mapped_column(ForeignKey("background_tasks.id"), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="running")
    input_fingerprint: Mapped[str] = mapped_column(String(64), default="", index=True)
    rule_version: Mapped[str] = mapped_column(String(20), default="1")
    comparison_count: Mapped[int] = mapped_column(Integer, default=0)
    comparison_post_ids: Mapped[str] = mapped_column(Text, default="[]")
    summary: Mapped[str] = mapped_column(Text, default="")
    overall_result: Mapped[str] = mapped_column(String(30), default="unknown")
    metrics_snapshot: Mapped[str] = mapped_column(Text, default="{}")
    homepage_analysis: Mapped[str] = mapped_column(Text, default="{}")
    new_topics: Mapped[str] = mapped_column(Text, default="[]")
    warnings: Mapped[str] = mapped_column(Text, default="[]")
    model_name: Mapped[str] = mapped_column(String(120), default="")
    prompt_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_app_now)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class VideoReviewFinding(Base):
    __tablename__ = "video_review_findings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    review_id: Mapped[int] = mapped_column(ForeignKey("video_reviews.id"), index=True)
    dimension: Mapped[str] = mapped_column(String(20), default="plays")
    rule_key: Mapped[str] = mapped_column(String(60), default="")
    title: Mapped[str] = mapped_column(String(300), default="")
    judgement_type: Mapped[str] = mapped_column(String(20), default="fact")
    conclusion: Mapped[str] = mapped_column(Text, default="")
    metric_evidence: Mapped[str] = mapped_column(Text, default="[]")
    content_evidence: Mapped[str] = mapped_column(Text, default="[]")
    comparison_post_ids: Mapped[str] = mapped_column(Text, default="[]")
    suggestion: Mapped[str] = mapped_column(Text, default="")
    target_metric: Mapped[str] = mapped_column(String(30), default="")
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_app_now)


class VideoTopicRecommendation(Base):
    __tablename__ = "video_topic_recommendations"
    __table_args__ = (UniqueConstraint("review_id", "role", "rank", name="uq_video_topic_position"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    review_id: Mapped[int] = mapped_column(ForeignKey("video_reviews.id"), index=True)
    parent_id: Mapped[int | None] = mapped_column(ForeignKey("video_topic_recommendations.id"), nullable=True)
    role: Mapped[str] = mapped_column(String(20), default="backup")
    rank: Mapped[int] = mapped_column(Integer, default=1)
    topic: Mapped[str] = mapped_column(String(500), default="")
    reason: Mapped[str] = mapped_column(Text, default="")
    fit_reason: Mapped[str] = mapped_column(Text, default="")
    evidence: Mapped[str] = mapped_column(Text, default="[]")
    outline: Mapped[str] = mapped_column(Text, default="[]")
    opening_line: Mapped[str] = mapped_column(Text, default="")
    target_metric: Mapped[str] = mapped_column(String(30), default="plays")
    follow_up_role: Mapped[str] = mapped_column(String(40), default="")
    source_types: Mapped[str] = mapped_column(Text, default="[]")
    score: Mapped[float] = mapped_column(Float, default=0)
    score_detail: Mapped[str] = mapped_column(Text, default="{}")
    adopted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_app_now)


class VideoImprovementPlan(Base):
    __tablename__ = "video_improvement_plans"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    review_id: Mapped[int] = mapped_column(ForeignKey("video_reviews.id"), index=True)
    source_post_id: Mapped[int] = mapped_column(ForeignKey("platform_posts.id"), index=True)
    recommendation_id: Mapped[int | None] = mapped_column(ForeignKey("video_topic_recommendations.id"), nullable=True)
    kept_text: Mapped[str] = mapped_column(Text, default="")
    changes: Mapped[str] = mapped_column(Text, default="[]")
    target_metrics: Mapped[str] = mapped_column(Text, default="[]")
    status: Mapped[str] = mapped_column(String(20), default="recorded")
    published_post_id: Mapped[int | None] = mapped_column(ForeignKey("platform_posts.id"), nullable=True, index=True)
    check_result: Mapped[str] = mapped_column(Text, default="{}")
    checked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_app_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_app_now, onupdate=_app_now)
