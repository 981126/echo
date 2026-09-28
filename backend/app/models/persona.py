"""人设档案模型：标签+描述+维度，版本化；以及增量/全量对齐校验记录（R-128）。"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from ..db import Base
from ..core.timeutil import now as _app_now


class PersonaTag(Base):
    __tablename__ = "persona_tags"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    creator_id: Mapped[int | None] = mapped_column(ForeignKey("creators.id"), nullable=True, index=True)  # 归属主博主（M13，R-029）
    label: Mapped[str] = mapped_column(String(100), index=True)  # 标签，如"犀利敢说"
    description: Mapped[str] = mapped_column(Text, default="")  # 描述
    dimension: Mapped[str] = mapped_column(String(30), default="")  # AI 自定维度（语气/价值观/口头禅/选题/受众/结构/专业/其他，R-128）
    category: Mapped[str] = mapped_column(String(20), default="style")  # style | topic | redline | phrase
    layer: Mapped[str] = mapped_column(String(20), default="stance")  # R-182 四层：core_dna|stance|mode|forbidden
    evidence: Mapped[str] = mapped_column(Text, default="")  # R-182 证据原文短句
    frequency: Mapped[int] = mapped_column(Integer, default=0)  # R-182 出现频次（命中素材篇数）
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)  # R-182 最后出现时间
    confirm_strength: Mapped[int] = mapped_column(Integer, default=1)  # R-182 作者确认强度（手动=3/AI建议确认=2）
    source: Mapped[str] = mapped_column(String(20), default="ai")  # ai | manual
    status: Mapped[str] = mapped_column(String(20), default="suggested")  # suggested|confirmed|rejected
    version: Mapped[int] = mapped_column(Integer, default=1)  # 档案版本
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_app_now)


class PersonaCheck(Base):
    """增量 vs 全量 5% 对齐校验记录（R-128）：供人设页展示差异百分比与明细。"""

    __tablename__ = "persona_checks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    creator_id: Mapped[int | None] = mapped_column(ForeignKey("creators.id"), nullable=True, index=True)
    mode: Mapped[str] = mapped_column(String(20), default="increment")  # increment | manual
    source_count: Mapped[int] = mapped_column(Integer, default=0)  # 参与全量重算的素材篇数
    coverage: Mapped[float] = mapped_column(Float, default=0.0)  # 集合覆盖率（0-1）
    semantic: Mapped[float | None] = mapped_column(Float, nullable=True)  # AI 语义复核打分（0-100，None=不可用）
    passed: Mapped[bool] = mapped_column(Boolean, default=True)  # 是否达标（覆盖率与语义分都 ≥95%）
    fallback: Mapped[bool] = mapped_column(Boolean, default=False)  # 是否已自动回退为全量结果
    detail: Mapped[str] = mapped_column(Text, default="{}")  # 差异明细 JSON（missing 条目、语义理由等）
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_app_now)
