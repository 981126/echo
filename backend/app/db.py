"""数据库：PostgreSQL + SQLAlchemy 2.x（R-235）。

R-235 起 SQLite 全面下线：R-016 以来的轻量迁移与一次性数据修复全部删除
（数据已由作者迁移至 PG，新环境靠 Base.metadata.create_all 建全量结构）。
连接串来自 .env 的 ECHO_DATABASE_URL，无默认值（config 层 fail-closed）。
"""

from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from .config import get_settings


class Base(DeclarativeBase):
    pass


def _make_engine():
    settings = get_settings()
    return create_engine(
        settings.database_url,
        pool_size=10,
        max_overflow=20,
        pool_pre_ping=True,  # 连接被 PG 端断开（重启/超时）时自动重连，避免首日连错就炸
        pool_recycle=1800,
        # R-235：远端 PG（作者 NAS，公网 IPv6）偶发握手丢包；不给超时会让请求无限期挂住
        connect_args={"connect_timeout": 10},
    )


engine = _make_engine()
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _ensure_indexes() -> None:
    """补常见查询缺的索引（PG：IF NOT EXISTS 幂等，已存在跳过）。"""
    wanted = {
        "platform_posts": {
            "ix_platform_posts_local_video_id": "local_video_id",
            "ix_platform_posts_publish_time": "publish_time",
        },
        "videos": {"ix_videos_platform_post_id": "platform_post_id"},
        "notifications": {"ix_notifications_created_at": "created_at"},
    }
    with engine.begin() as conn:
        for table, idxs in wanted.items():
            for name, col in idxs.items():
                try:
                    conn.exec_driver_sql(f"CREATE INDEX IF NOT EXISTS {name} ON {table} ({col})")
                except Exception:  # noqa: BLE001  单索引失败不阻断启动
                    pass


def _ensure_binding_unique_index() -> None:
    """R-061-D-1：平台作品↔本地素材绑定唯一部分索引（防重复绑定；PG 原生支持 WHERE 部分索引）。"""
    with engine.begin() as conn:
        conn.exec_driver_sql(
            "CREATE UNIQUE INDEX IF NOT EXISTS ux_platform_posts_local_platform "
            "ON platform_posts(local_video_id, platform) WHERE local_video_id IS NOT NULL"
        )


def init_db() -> None:
    from . import models  # noqa: F401  确保模型已注册

    Base.metadata.create_all(bind=engine)
    _ensure_indexes()
    _ensure_binding_unique_index()
    # R-021：首次启动把各功能默认提示词 seed 入库（版本 v1）
    from .services.prompt_service import (
        ensure_defaults,
        ensure_enabled_fallback,
        ensure_generation_steering_prompt,
        ensure_persona_layer_prompts,
    )

    session = SessionLocal()
    try:
        ensure_defaults(session)
        ensure_persona_layer_prompts(session)  # R-182：人设四层提示词升级
        ensure_generation_steering_prompt(session)  # R-183：生成提示词退回方向盘
        ensure_enabled_fallback(session)  # R-231：无启用版兜底启用代码默认
    finally:
        session.close()
    # R-147 P1：只读分析视图（给 AI 对话的 sql_query 用；视图即白名单）
    from .core import analytics_views

    analytics_views.ensure_views(engine)
