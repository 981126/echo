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
    payload: str = "{}"  # R-088/R-089：任务关联的 work/post/video，前端切页回来按此认领到卡片
    created_at: datetime
    updated_at: datetime
