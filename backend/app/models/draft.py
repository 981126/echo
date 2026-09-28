"""脚本草稿模型：工作台改写、AI 原稿留底（供改稿差异分析）。"""

from __future__ import annotations

import json
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from ..db import Base
from ..core.timeutil import now as _app_now


class Draft(Base):
    __tablename__ = "drafts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    creator_id: Mapped[int | None] = mapped_column(ForeignKey("creators.id"), nullable=True, index=True)  # 归属主博主（M13，R-029）
    video_id: Mapped[int | None] = mapped_column(ForeignKey("videos.id"), nullable=True, index=True)
    title: Mapped[str] = mapped_column(String(255), default="")
    cover_text: Mapped[str] = mapped_column(String(100), default="")
    script: Mapped[str] = mapped_column(Text, default="")
    platform_shells: Mapped[str] = mapped_column(Text, default="{}")  # JSON：各平台外壳
    source: Mapped[str] = mapped_column(String(20), default="manual")  # manual | ai
    original_script: Mapped[str] = mapped_column(Text, default="")  # AI 原稿（改稿差异分析用）
    source_ref: Mapped[str] = mapped_column(Text, default="{}")  # 来源素材信息 JSON（对标 key/title/benchmark_name 等，R-117）
    tags: Mapped[str] = mapped_column(Text, default="[]")  # 素材标签（来自对标素材，R-120）
    status: Mapped[str] = mapped_column(String(20), default="draft")  # draft|used|done|archived|deleted
    prompt_version: Mapped[int] = mapped_column(Integer, default=0)  # 生成时启用的提示词版本（R-129 M116；0=历史/未知）
    persona_version: Mapped[int] = mapped_column(Integer, default=0)  # 生成时的人设档案版本（R-130；0=历史/未知）
    quality: Mapped[str] = mapped_column(Text, default="{}")  # 生成后自检结果 JSON（R-131）
    publish_url: Mapped[str] = mapped_column(String(500), default="")  # R-184 发布链接
    publish_platform: Mapped[str] = mapped_column(String(20), default="")  # R-184 发布平台
    published_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)  # R-184 发布时间
    version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_app_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=_app_now, onupdate=_app_now
    )

    def shells_dict(self) -> dict:
        try:
            data = json.loads(self.platform_shells or "{}")
            return data if isinstance(data, dict) else {}
        except json.JSONDecodeError:
            return {}
