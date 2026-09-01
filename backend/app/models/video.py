"""视频与转写稿模型。"""
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..db import Base


class Video(Base):
    __tablename__ = "videos"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    filename: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    platform: Mapped[str] = mapped_column(String(20), default="")  # douyin/bilibili/xiaohongshu
    status: Mapped[str] = mapped_column(String(20), default="planned")  # planned | published
    planned_publish_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    is_ad: Mapped[bool] = mapped_column(Boolean, default=False)  # 商务广告（不参与人设学习）
    main_topic: Mapped[str] = mapped_column(String(50), default="")  # 求职/面试/赚钱/知识/其他
    tags: Mapped[str] = mapped_column(Text, default="[]")  # JSON 数组（自定义标签）
    tags_confirmed: Mapped[bool] = mapped_column(Boolean, default=False)  # AI 预打标签是否经作者确认
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    transcript: Mapped["Transcript | None"] = relationship(
        back_populates="video", uselist=False, cascade="all, delete-orphan"
    )


class Transcript(Base):
    __tablename__ = "transcripts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    video_id: Mapped[int] = mapped_column(ForeignKey("videos.id"), index=True)
    source_text: Mapped[str] = mapped_column(Text, default="")  # 原始文案（可能与口播不一致）
    transcript_text: Mapped[str] = mapped_column(Text, default="")  # ASR 转写稿
    corrected_text: Mapped[str] = mapped_column(Text, default="")  # AI 校对后（分析以此为准）
    asr_status: Mapped[str] = mapped_column(String(20), default="pending")  # pending|done|failed
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    video: Mapped[Video] = relationship(back_populates="transcript")
