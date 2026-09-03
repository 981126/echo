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
    error: str = ""
    created_at: datetime
    updated_at: datetime
