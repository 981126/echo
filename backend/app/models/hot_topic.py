"""热点与选题候选模型。"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from ..db import Base
from ..core.timeutil import now as _app_now


class HotTopic(Base):
    __tablename__ = "hot_topics"
    __table_args__ = (UniqueConstraint("platform", "title", "topic_date", name="uq_hot"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    platform: Mapped[str] = mapped_column(String(20), index=True)
    title: Mapped[str] = mapped_column(String(255))
    heat: Mapped[str] = mapped_column(String(50), default="")
    url: Mapped[str] = mapped_column(String(500), default="")
    raw: Mapped[str] = mapped_column(Text, default="{}")
    topic_date: Mapped[str] = mapped_column(String(10), index=True)  # YYYY-MM-DD
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_app_now)


class TopicCandidate(Base):
    __tablename__ = "topic_candidates"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_date: Mapped[str] = mapped_column(String(10), index=True)
    hot_topic_id: Mapped[int | None] = mapped_column(ForeignKey("hot_topics.id"), nullable=True)
    title: Mapped[str] = mapped_column(String(255))  # 改写后的选题
    platform: Mapped[str] = mapped_column(String(20), default="")
    score: Mapped[int] = mapped_column(Integer, default=0)
    reason: Mapped[str] = mapped_column(Text, default="")
    draft_id: Mapped[int | None] = mapped_column(ForeignKey("drafts.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_app_now)


class TopicIdea(Base):
    """选题池灵感（M13，R-028）：来自各平台热点或作品评论区，人工挑选，不自动推送。"""

    __tablename__ = "topic_ideas"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source: Mapped[str] = mapped_column(String(20), default="hot")  # hot | comment
    platform: Mapped[str] = mapped_column(String(20), index=True, default="")
    title: Mapped[str] = mapped_column(String(255))
    detail: Mapped[str] = mapped_column(Text, default="")  # 评论原文/热度说明
    post_id: Mapped[int | None] = mapped_column(ForeignKey("platform_posts.id"), nullable=True)
    post_title: Mapped[str] = mapped_column(String(500), default="")
    creator_id: Mapped[int | None] = mapped_column(ForeignKey("creators.id"), nullable=True, index=True)
    snapshot_date: Mapped[str] = mapped_column(String(10), index=True)  # YYYY-MM-DD
    used: Mapped[bool] = mapped_column(default=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_app_now)
