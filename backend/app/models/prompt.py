"""AI 提示词版本模型（R-021）。"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from ..db import Base
from ..core.timeutil import now as _app_now


class AiPrompt(Base):
    __tablename__ = "ai_prompts"
    __table_args__ = (UniqueConstraint("key", "version", name="uq_prompt_version"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    key: Mapped[str] = mapped_column(String(40), index=True)  # generation / persona_init / video_tags / persona_updates / review / diff / chat / correct
    version: Mapped[int] = mapped_column(Integer, default=1)
    content: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(20), default="enabled")  # enabled | candidate | archived | rejected
    note: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_app_now)


class PromptEval(Base):
    """金样本回放评分（R-129 M115）：候选版 vs 当前版在同一批金样本上的客观得分。"""

    __tablename__ = "prompt_evals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    key: Mapped[str] = mapped_column(String(40), index=True)
    candidate_version: Mapped[int] = mapped_column(Integer, default=0)
    base_version: Mapped[int] = mapped_column(Integer, default=0)
    candidate_score: Mapped[float] = mapped_column(Float, default=0.0)
    base_score: Mapped[float] = mapped_column(Float, default=0.0)
    supported: Mapped[bool] = mapped_column(Boolean, default=True)  # False=该功能暂不支持回放评分
    reason: Mapped[str] = mapped_column(Text, default="")
    detail: Mapped[str] = mapped_column(Text, default="{}")  # 明细分项 JSON
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_app_now)
