"""视频相关接口契约（Pydantic v2）。"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator


def _parse_str_list(value):
    if isinstance(value, str):
        try:
            data = json.loads(value)
            return [str(x) for x in data] if isinstance(data, list) else []
        except json.JSONDecodeError:
            return []
    return value or []


class VideoOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    filename: str
    title: str = ""
    cover_url: Optional[str] = None
    platforms: list[str] = []
    status: str = "planned"
    planned_publish_at: Optional[datetime] = None
    published_at: Optional[datetime] = None
    is_ad: bool = False
    ad_price: Optional[int] = None
    main_topics: list[str] = []
    tags: list[str] = []
    tags_confirmed: bool = False
    created_at: datetime

    @field_validator("platforms", "main_topics", "tags", mode="before")
    @classmethod
    def _parse_lists(cls, value):
        return _parse_str_list(value)


class TranscriptOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    source_text: str = ""
    transcript_text: str = ""
    corrected_text: str = ""
    asr_status: str = "pending"


class VideoDetailOut(VideoOut):
    transcript: Optional[TranscriptOut] = None


class VideoUpdate(BaseModel):
    title: Optional[str] = None
    platforms: Optional[list[str]] = None
    status: Optional[str] = Field(default=None, pattern="^(planned|published)$")
    planned_publish_at: Optional[datetime] = None
    published_at: Optional[datetime] = None
    is_ad: Optional[bool] = None
    ad_price: Optional[int] = None
    main_topics: Optional[list[str]] = None
    tags: Optional[list[str]] = None
    source_text: Optional[str] = None
    corrected_text: Optional[str] = None


class TagConfirmIn(BaseModel):
    tags_confirmed: bool = True


class VideoListOut(BaseModel):
    total: int
    items: list[VideoOut]
