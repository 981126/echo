"""草稿接口契约。"""
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator


class DraftOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    video_id: Optional[int] = None
    title: str = ""
    cover_text: str = ""
    script: str = ""
    platform_shells: dict = {}
    source: str = "manual"
    status: str = "draft"
    version: int = 1
    created_at: datetime
    updated_at: datetime

    @field_validator("platform_shells", mode="before")
    @classmethod
    def _parse_shells(cls, value):
        if isinstance(value, str):
            import json

            try:
                data = json.loads(value)
                return data if isinstance(data, dict) else {}
            except json.JSONDecodeError:
                return {}
        return value or {}


class DraftCreate(BaseModel):
    video_id: Optional[int] = None
    title: str = ""
    cover_text: str = ""
    script: str = ""
    platform_shells: dict = {}
    status: str = Field(default="draft", pattern="^(draft|used|archived)$")


class DraftUpdate(BaseModel):
    video_id: Optional[int] = None
    title: Optional[str] = None
    cover_text: Optional[str] = None
    script: Optional[str] = None
    platform_shells: Optional[dict] = None
    status: Optional[str] = Field(default=None, pattern="^(draft|used|archived)$")
