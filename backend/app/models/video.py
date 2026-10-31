"""视频与转写稿模型。"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..db import Base
from ..core.timeutil import now as _app_now


class Video(Base):
    __tablename__ = "videos"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    filename: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    title: Mapped[str] = mapped_column(String(255), default="")  # 视频标题（选题标题）
    cover_path: Mapped[str] = mapped_column(String(255), default="")  # data/covers 下的封面文件名
    platforms: Mapped[str] = mapped_column(Text, default="[]")  # JSON 数组 douyin/bilibili/xiaohongshu
    creator_id: Mapped[int | None] = mapped_column(ForeignKey("creators.id"), nullable=True, index=True)  # 归属主博主（M13，R-029）
    platform_post_id: Mapped[str] = mapped_column(String(200), default="")  # 绑定的云端作品 "platform:external_id"（M13，R-027）
    work_id: Mapped[int | None] = mapped_column(ForeignKey("works.id"), nullable=True, index=True)  # 跨平台同作品合并（M13+）
    status: Mapped[str] = mapped_column(String(20), default="planned")  # planned | published
    planned_publish_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    is_ad: Mapped[bool] = mapped_column(Boolean, default=False)  # 商务广告（不参与人设学习）
    ad_price: Mapped[int | None] = mapped_column(Integer, nullable=True)  # 广告合作价格（元，可空）
    main_topics: Mapped[str] = mapped_column(Text, default="[]")  # JSON 数组 求职/面试/赚钱/知识/其他
    tags: Mapped[str] = mapped_column(Text, default="[]")  # JSON 数组（自定义标签）
    tags_confirmed: Mapped[bool] = mapped_column(Boolean, default=False)  # AI 预打标签是否经作者确认
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_app_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=_app_now,
        onupdate=_app_now,
        # R-241：与 migration r241perftz 的库默认值保持一致（北京时间表达式，避免 autogenerate 漂移）
        server_default=text("(now() AT TIME ZONE 'Asia/Shanghai')"),
    )  # R-241：卡片缓存版本键（感知视频标题/标签/状态等原地编辑）

    @property
    def cover_url(self) -> str | None:
        """封面静态地址（data/covers 由 main.py 挂载到 /covers）。"""
        return f"/covers/{self.cover_path}" if self.cover_path else None

    transcript: Mapped["Transcript | None"] = relationship(
        back_populates="video", uselist=False, cascade="all, delete-orphan"
    )


class Transcript(Base):
    __tablename__ = "transcripts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    video_id: Mapped[int] = mapped_column(ForeignKey("videos.id"), unique=True, index=True)  # R-242：一视频一条转写
    source_text: Mapped[str] = mapped_column(Text, default="")  # 原始文案（可能与口播不一致）
    transcript_text: Mapped[str] = mapped_column(Text, default="")  # ASR 转写稿
    corrected_text: Mapped[str] = mapped_column(Text, default="")  # AI 校对后（分析以此为准）
    asr_status: Mapped[str] = mapped_column(String(20), default="pending")  # pending|done|failed
    asr_provider: Mapped[str] = mapped_column(String(20), default="")  # mock|aliyun|siliconflow（转写来源，R-112）
    asr_model: Mapped[str] = mapped_column(String(100), default="")  # 硅基流动模型名；阿里云未知为空
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_app_now)

    video: Mapped[Video] = relationship(back_populates="transcript")
