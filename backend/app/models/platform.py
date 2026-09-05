"""平台数据与博主管理模型（M13，R-027/R-029）。

链路：creators(博主) → creator_accounts(博主×平台账号) → platform_posts(云端作品)
      → platform_post_stats(作品指标按天快照)；另有 creator_account_snapshots(主页按天)
      与 sync_jobs(同步任务留痕)。
设计约束（D-027）：云端作品与本地素材(videos)分离建模；视频默认不下载。
"""

from __future__ import annotations

import json
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from ..db import Base


class Creator(Base):
    """博主：主博主(kind=owner) 或 对标博主(kind=benchmark，挂在 owner 下)。"""

    __tablename__ = "creators"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    kind: Mapped[str] = mapped_column(String(10), default="owner")  # owner | benchmark
    parent_id: Mapped[int | None] = mapped_column(
        ForeignKey("creators.id"), nullable=True, index=True
    )  # benchmark 所属的主博主
    name: Mapped[str] = mapped_column(String(100), default="")
    note: Mapped[str] = mapped_column(Text, default="")  # 风格备注（对标风格卡也存这里，作者手写部分）
    is_current: Mapped[bool] = mapped_column(default=False, index=True)  # 仅 owner 可为当前
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class CreatorAccount(Base):
    """博主在某个平台的账号配置。"""

    __tablename__ = "creator_accounts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    creator_id: Mapped[int] = mapped_column(ForeignKey("creators.id"), index=True)
    platform: Mapped[str] = mapped_column(String(20), index=True)  # douyin|xiaohongshu|bilibili
    nickname: Mapped[str] = mapped_column(String(100), default="")
    home_link: Mapped[str] = mapped_column(String(500), default="")  # 主页分享链接
    platform_user_id: Mapped[str] = mapped_column(String(200), default="")  # 解析出的 sec_user_id/user_id/uid
    avatar_path: Mapped[str] = mapped_column(String(255), default="")  # 本地头像文件名（手动上传或自动同步，存 covers/）
    avatar_url: Mapped[str] = mapped_column(String(1000), default="")  # 远端头像 URL（自动同步来源，本地缺失时兜底）
    extra_config: Mapped[str] = mapped_column(Text, default="{}")  # JSON：cookie/share_text 等增强字段
    enabled: Mapped[bool] = mapped_column(default=True)
    sync_frequency: Mapped[str] = mapped_column(String(10), default="daily")  # daily|weekly|manual
    last_sync_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    sync_status: Mapped[str] = mapped_column(String(20), default="idle")  # idle|running|done|failed
    sync_message: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    @property
    def avatar(self) -> str | None:
        """本地头像优先，否则回退远端。"""
        if self.avatar_path:
            return f"/covers/{self.avatar_path}"
        return self.avatar_url or None

    def extra(self) -> dict:
        try:
            data = json.loads(self.extra_config or "{}")
            return data if isinstance(data, dict) else {}
        except json.JSONDecodeError:
            return {}


class CreatorAccountSnapshot(Base):
    """主页指标按天快照（粉丝/获赞/作品数等）。"""

    __tablename__ = "creator_account_snapshots"
    __table_args__ = (
        UniqueConstraint("account_id", "snapshot_date", name="uq_acct_snap"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("creator_accounts.id"), index=True)
    snapshot_date: Mapped[str] = mapped_column(String(10), index=True)  # YYYY-MM-DD
    nickname: Mapped[str] = mapped_column(String(100), default="")
    followers: Mapped[int] = mapped_column(Integer, default=0)
    likes_total: Mapped[int] = mapped_column(Integer, default=0)
    posts_total: Mapped[int] = mapped_column(Integer, default=0)
    following: Mapped[int] = mapped_column(Integer, default=0)
    raw: Mapped[str] = mapped_column(Text, default="{}")  # 原始 JSON（D-027 全存）
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class PlatformPost(Base):
    """同步回来的云端作品（默认无本地视频文件）。"""

    __tablename__ = "platform_posts"
    __table_args__ = (UniqueConstraint("platform", "platform_post_id", name="uq_platform_post"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("creator_accounts.id"), index=True)
    platform: Mapped[str] = mapped_column(String(20), index=True)
    platform_post_id: Mapped[str] = mapped_column(String(200), index=True)
    title: Mapped[str] = mapped_column(String(500), default="")
    desc: Mapped[str] = mapped_column(Text, default="")
    tags: Mapped[str] = mapped_column(Text, default="[]")  # 解析出的 #标签 JSON 数组
    is_ad: Mapped[bool] = mapped_column(default=False)
    ad_price: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cover_url: Mapped[str] = mapped_column(String(1000), default="")  # 远端封面 URL
    cover_path: Mapped[str] = mapped_column(String(255), default="")  # 本地封面缓存文件名
    video_url: Mapped[str] = mapped_column(String(1000), default="")  # 默认空：不下载视频
    publish_time: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    raw: Mapped[str] = mapped_column(Text, default="{}")  # 原始 JSON 全存
    local_video_id: Mapped[int | None] = mapped_column(
        ForeignKey("videos.id"), nullable=True
    )  # 手动"转素材/下载"后关联本地视频
    work_id: Mapped[int | None] = mapped_column(
        ForeignKey("works.id"), nullable=True, index=True
    )  # 跨平台同作品合并（M13+）
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    @property
    def cover_url_local(self) -> str | None:
        """本地封面优先，否则回退远端。"""
        return f"/covers/{self.cover_path}" if self.cover_path else (self.cover_url or None)


class PlatformPostStat(Base):
    """作品互动指标按天快照。"""

    __tablename__ = "platform_post_stats"
    __table_args__ = (UniqueConstraint("post_id", "stat_date", name="uq_post_stat"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    post_id: Mapped[int] = mapped_column(ForeignKey("platform_posts.id"), index=True)
    stat_date: Mapped[str] = mapped_column(String(10), index=True)  # YYYY-MM-DD
    plays: Mapped[int] = mapped_column(Integer, default=0)
    likes: Mapped[int] = mapped_column(Integer, default=0)
    favorites: Mapped[int] = mapped_column(Integer, default=0)
    shares: Mapped[int] = mapped_column(Integer, default=0)
    comments: Mapped[int] = mapped_column(Integer, default=0)
    extra: Mapped[str] = mapped_column(Text, default="{}")  # 平台特有字段（投币/弹幕等）JSON
    source: Mapped[str] = mapped_column(String(20), default="tikhub")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class PlatformPostComment(Base):
    """平台作品评论（入库，本地查询；同步/同步数据时写入）。"""

    __tablename__ = "platform_post_comments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    post_id: Mapped[int] = mapped_column(ForeignKey("platform_posts.id"), index=True)
    platform: Mapped[str] = mapped_column(String(20), default="")
    text: Mapped[str] = mapped_column(Text, default="")
    user_nick: Mapped[str] = mapped_column(String(100), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class SyncJob(Base):
    """同步任务留痕。"""

    __tablename__ = "sync_jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    job_type: Mapped[str] = mapped_column(String(20), index=True)  # initial|daily|weekly|single|manual
    scope: Mapped[str] = mapped_column(String(20), default="")  # profile|posts|comments|post
    creator_id: Mapped[int | None] = mapped_column(ForeignKey("creators.id"), nullable=True)
    account_id: Mapped[int | None] = mapped_column(ForeignKey("creator_accounts.id"), nullable=True)
    post_id: Mapped[int | None] = mapped_column(ForeignKey("platform_posts.id"), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="running")  # running|done|failed
    message: Mapped[str] = mapped_column(Text, default="")
    stats: Mapped[str] = mapped_column(Text, default="{}")  # 计数 JSON
    started_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
