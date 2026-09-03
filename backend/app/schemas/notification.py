"""通知接口契约（R-019）。"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict


class NotificationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    kind: str
    status: str
    title: str = ""
    message: str = ""
    target: str = "/home"
    read: bool = False
    created_at: datetime


class NotificationReadIn(BaseModel):
    ids: Optional[list[int]] = None  # 空 = 全部已读
