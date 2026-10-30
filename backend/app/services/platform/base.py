"""平台数据源适配器（R-062）。

TikHub 只是“默认数据源”；通过统一接口（DataSource Protocol），任何第三方平台
都可以整体或按平台注册替换，业务层（platform_sync / API）不感知具体来源。

- 整体替换默认源：`register_platform_source("default", factory)`（工厂返回 DataSource）
- 按平台替换：`register_platform_source("douyin", factory)` 只换抖音
- 运行期取源：`make_source(platform)` —— 有 override 用之，否则回落到 TikHub
  （R-241：回落路径的 `tikhub.make_client` 为进程级复用，同一 (mode, base_url, api_key)
  只建一次；`requests_used` 是**线程内累计值**，计费方用「同一线程调用前后差值」，
  `douyin_creator_sync._charge_requests` / `douyin_references` 已按该口径实现）
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Protocol, cast


@dataclass
class PostData:
    platform_post_id: str
    title: str = ""
    desc: str = ""
    tags: list[str] = field(default_factory=list)
    cover_url: str = ""
    video_url: str = ""
    publish_time: datetime | None = None
    stats: dict[str, Any] = field(default_factory=dict)  # plays/likes/favorites/shares/comments/extra
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass
class ProfileData:
    nickname: str = ""
    avatar_url: str = ""
    followers: int = 0
    likes_total: int = 0
    posts_total: int = 0
    following: int = 0
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass
class CommentData:
    """平台评论（R-067：入库需带点赞数，才能按“每平台点赞 Top50”筛选展示）。"""

    text: str
    likes: int = 0
    user_nick: str = ""


class DataSource(Protocol):
    """平台数据源统一接口（每个实现需满足；TikHubClient 即默认实现）。"""

    requests_used: int

    def fetch_profile(self, platform: str, user_id: str, account=None) -> ProfileData: ...

    def fetch_user_posts(
        self, platform: str, user_id: str, count: int = 20, cursor: str = "", account=None
    ) -> list[PostData]: ...

    def fetch_post_stats(self, platform: str, post_id: str, account=None) -> dict: ...

    def fetch_comments(
        self, platform: str, post_id: str, count: int = 20, account=None, raw: dict | None = None
    ) -> list[CommentData]: ...

    def get_balance(self) -> dict: ...


_OVERRIDES: dict[str, Callable[[], DataSource]] = {}


def register_platform_source(platform: str, factory: Callable[[], DataSource]) -> None:
    """注册数据源工厂：platform 为 douyin/bilibili/xiaohongshu 或 default（整体替换）。"""
    _OVERRIDES[platform or "default"] = factory


def clear_platform_sources() -> None:
    _OVERRIDES.clear()


def make_source(platform: str | None = None, mode: str = "") -> DataSource:
    """取数据源：优先 per-platform override → default override → TikHub。"""
    key = platform or "default"
    factory = _OVERRIDES.get(key) or _OVERRIDES.get("default")
    if factory is not None:
        return factory()
    from .tikhub import make_client  # 延迟导入避免循环

    return cast(DataSource, make_client(mode=mode))
