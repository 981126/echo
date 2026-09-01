"""视频相关接口契约（Pydantic v2）。"""
import json
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator


class VideoOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    filename: str
    platform: str = ""
    status: str = "planned"
    planned_publish_at: Optional[datetime] = None
    published_at: Optional[datetime] = None
    is_ad: bool = False
    main_topic: str = ""
    tags: list[str] = []
    tags_confirmed: bool = False
    created_at: datetime

    @field_validator("tags", mode="before")
    @classmethod
    def _parse_tags(cls, value):
        if isinstance(value, str):
            try:
                data = json.loads(value)
                return [str(t) for t in data] if isinstance(data, list) else []
            except json.JSONDecodeError:
                return []
        return value or []


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
    platform: Optional[str] = None
    status: Optional[str] = Field(default=None, pattern="^(planned|published)$")
    planned_publish_at: Optional[datetime] = None
    published_at: Optional[datetime] = None
    is_ad: Optional[bool] = None
    main_topic: Optional[str] = None
    tags: Optional[list[str]] = None
    source_text: Optional[str] = None


class TagConfirmIn(BaseModel):
    tags_confirmed: bool = True


class VideoListOut(BaseModel):
    total: int
    items: list[VideoOut]
