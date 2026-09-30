"""后台任务接口契约。"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class TaskOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    kind: str
    status: str
    progress: int
    note: str = ""
    error: str = ""
    result: str = ""
    payload: str = "{}"  # R-088/R-089：任务关联的 work/post/video，前端切页回来按此认领到卡片
    created_at: datetime
    updated_at: datetime
    # R-202：派生展示字段，供全局「进行中」指示器直接使用（不落库）
    label: str = ""
    target: str = ""
