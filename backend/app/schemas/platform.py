"""博主/平台数据接口契约（M13，R-027/R-029）。"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


def _parse_json_field(value, fallback=None):
    if isinstance(value, (dict, list)):
        return value
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return fallback if fallback is not None else {}
    return fallback if fallback is not None else {}


class CreatorIn(BaseModel):
    kind: str = Field(default="owner", pattern="^(owner|benchmark)$")
    parent_id: Optional[int] = None
    name: str = ""
    note: str = ""


class CreatorOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    kind: str
    parent_id: Optional[int] = None
    name: str
    note: str = ""
    is_current: bool = False
    created_at: datetime


class AccountIn(BaseModel):
    platform: str = Field(pattern="^(douyin|xiaohongshu|bilibili)$")
    nickname: str = ""
    home_link: str = ""
    platform_user_id: str = ""
    extra_config: dict = Field(default_factory=dict)
    enabled: bool = True
    sync_frequency: str = Field(default="daily", pattern="^(daily|weekly|manual)$")


class AccountOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    creator_id: int
    platform: str
    nickname: str = ""
    home_link: str = ""
    platform_user_id: str = ""
    extra_config: dict = Field(default_factory=dict)
    enabled: bool = True
    sync_frequency: str = "daily"
    last_sync_at: Optional[datetime] = None
    sync_status: str = "idle"
    sync_message: str = ""
    created_at: datetime


class LinkParseOut(BaseModel):
    platform: str
    platform_user_id: str
    nickname: str = ""


class PlatformPostOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    account_id: int
    platform: str
    platform_post_id: str
    title: str = ""
    desc: str = ""
    cover_url: str = ""
    cover_path: str = ""
    cover: Optional[str] = None
    video_url: str = ""
    publish_time: Optional[datetime] = None
    local_video_id: Optional[int] = None
    raw: dict = Field(default_factory=dict)
    created_at: datetime


class PostStatOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    post_id: int
    stat_date: str
    plays: int = 0
    likes: int = 0
    favorites: int = 0
    shares: int = 0
    comments: int = 0
    extra: dict = Field(default_factory=dict)
    source: str = "tikhub"


class SyncJobOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    job_type: str
    scope: str = ""
    creator_id: Optional[int] = None
    account_id: Optional[int] = None
    post_id: Optional[int] = None
    status: str = "running"
    message: str = ""
    stats: dict = Field(default_factory=dict)
    started_at: datetime
    finished_at: Optional[datetime] = None


class SyncRequest(BaseModel):
    scope: str = Field(default="daily", pattern="^(initial|daily|weekly)$")
    account_id: Optional[int] = None  # 为空 = 当前主博主全部启用账号
    creator_id: Optional[int] = None
    top_n: Optional[int] = None
