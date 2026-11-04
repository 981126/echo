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


class AiPromptDef(Base):
    """AI 提示词注册表（R-255）：一行一条提示词，含中文模块名与中文用途说明。

    与 `AiPrompt` 分工：本表管「有哪些提示词、叫什么、给哪个模块用、干什么用的、默认正文是什么」，
    `AiPrompt` 继续管「某条提示词第几版正文、当前启用哪版」。运行时 `get_prompt` 先读
    `ai_prompts` 的 enabled 版本，缺失时回退本表 `default_content`，再回退代码常量。
    """

    __tablename__ = "ai_prompt_defs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    key: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    title: Mapped[str] = mapped_column(String(80), default="")  # 中文名
    module: Mapped[str] = mapped_column(String(40), default="", index=True)  # 模块 code
    module_label: Mapped[str] = mapped_column(String(40), default="")  # 中文模块名
    purpose: Mapped[str] = mapped_column(Text, default="")  # 中文用途说明：用于哪个功能、干什么用的
    category: Mapped[str] = mapped_column(String(20), default="system")  # system | contract | probe
    editable: Mapped[bool] = mapped_column(Boolean, default=True)  # 页面可编辑
    optimizable: Mapped[bool] = mapped_column(Boolean, default=False)  # 可 AI 优化/评测
    llm_feature: Mapped[str] = mapped_column(String(40), default="")  # llm_router 功能名
    entry: Mapped[str] = mapped_column(Text, default="")  # 触发入口说明
    default_content: Mapped[str] = mapped_column(Text, default="")  # 代码默认正文（种子/兜底基准）
    code_ref: Mapped[str] = mapped_column(Text, default="")  # 代码位置
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_app_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_app_now)


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
