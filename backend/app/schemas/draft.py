"""草稿接口契约。"""

from __future__ import annotations

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
    original_script: str = ""
    source_ref: dict = {}
    tags: list[str] = []
    status: str = "draft"
    prompt_version: int = 0
    persona_version: int = 0
    quality: dict = {}
    version: int = 1
    # R-173：该草稿当前的 AI 长任务状态（讨论/洗稿/回炉/生成），无任务时为 None。
    # 由 list/get 接口填充，ORM 上没有该属性（默认 None）。
    debate: Optional[dict] = None
    created_at: datetime
    updated_at: datetime

    @field_validator("quality", mode="before")
    @classmethod
    def _parse_quality(cls, value):
        if isinstance(value, str):
            import json

            try:
                data = json.loads(value)
                return data if isinstance(data, dict) else {}
            except json.JSONDecodeError:
                return {}
        return value or {}

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

    @field_validator("source_ref", mode="before")
    @classmethod
    def _parse_source_ref(cls, value):
        if isinstance(value, str):
            import json

            try:
                data = json.loads(value)
                return data if isinstance(data, dict) else {}
            except json.JSONDecodeError:
                return {}
        return value or {}

    @field_validator("tags", mode="before")
    @classmethod
    def _parse_tags(cls, value):
        if isinstance(value, str):
            import json

            try:
                data = json.loads(value)
                return [str(x) for x in data] if isinstance(data, list) else []
            except json.JSONDecodeError:
                return []
        return value or []


class DraftCreate(BaseModel):
    video_id: Optional[int] = None
    title: str = ""
    cover_text: str = ""
    script: str = ""
    platform_shells: dict = {}
    tags: list[str] = []
    status: str = Field(default="draft", pattern="^(draft|used|done|archived|deleted)$")


class DraftUpdate(BaseModel):
    video_id: Optional[int] = None
    title: Optional[str] = None
    cover_text: Optional[str] = None
    script: Optional[str] = None
    platform_shells: Optional[dict] = None
    tags: Optional[list[str]] = None
    status: Optional[str] = Field(default=None, pattern="^(draft|used|done|archived|deleted)$")
