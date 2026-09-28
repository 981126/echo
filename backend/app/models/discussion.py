"""脚本讨论留痕模型（R-023）：双模型围绕草稿的每轮讨论消息。

R-178：留痕要记**实际出结果**的模型（`used_slot/vendor/model_id`），否则作者切了模型后
就再也说不上来当时这条是谁写的（`actor` 只存槽位名 `model1/model2`）。
`kind='run'` 的行是**一次讨论的运行头**（`content` 为 JSON：当时配置的生成方/评审方 + 轮次 + 是否降级）。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from ..db import Base
from ..core.timeutil import now as _app_now


class DraftDiscussion(Base):
    __tablename__ = "draft_discussions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    draft_id: Mapped[int] = mapped_column(ForeignKey("drafts.id", ondelete="CASCADE"), index=True)
    round: Mapped[int] = mapped_column(Integer, default=0)  # 0=初稿
    actor: Mapped[str] = mapped_column(String(20))  # 配置槽位 model1/model2 | system
    kind: Mapped[str] = mapped_column(String(20))  # draft | critique | revise | note | run
    content: Mapped[str] = mapped_column(Text, default="")
    # R-178：实际出结果的模型（降级/兜底后以事实为准）；系统行/历史行为空
    used_slot: Mapped[str] = mapped_column(String(20), default="")
    vendor: Mapped[str] = mapped_column(String(40), default="")
    model_id: Mapped[str] = mapped_column(String(80), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_app_now)
