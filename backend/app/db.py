"""数据库：SQLite + SQLAlchemy 2.x（含 R-016 轻量 schema 迁移）。

注：项目文档写的是 Alembic，但代码库尚未落地 Alembic 脚手架；
R-016 起先用幂等轻量迁移保证旧库可升级，后续再补 Alembic（tech-debt）。
"""

from __future__ import annotations

import json
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from .config import get_settings


class Base(DeclarativeBase):
    pass


def _make_engine():
    settings = get_settings()
    path: Path = settings.db_path
    path.parent.mkdir(parents=True, exist_ok=True)
    return create_engine(
        f"sqlite:///{path}",
        connect_args={"check_same_thread": False},
    )


engine = _make_engine()
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _migrate_videos() -> None:
    """videos 表：platform/main_topic（单值）→ platforms/main_topics（JSON 数组）+ cover_path。

    幂等：只在旧列存在/新列缺失时执行；全新库（create_all 已建新结构）自动跳过。
    """
    from sqlalchemy import text

    with engine.begin() as conn:
        cols = {row[1] for row in conn.exec_driver_sql("PRAGMA table_info(videos)").fetchall()}
        adds = []
        if "title" not in cols:
            adds.append("title VARCHAR(255) NOT NULL DEFAULT ''")
        if "platforms" not in cols:
            adds.append("platforms TEXT NOT NULL DEFAULT '[]'")
        if "main_topics" not in cols:
            adds.append("main_topics TEXT NOT NULL DEFAULT '[]'")
        if "cover_path" not in cols:
            adds.append("cover_path VARCHAR(255) NOT NULL DEFAULT ''")
        for ddl in adds:
            conn.exec_driver_sql(f"ALTER TABLE videos ADD COLUMN {ddl}")

        # 旧列存在：回填后删除
        if "platform" in cols and "main_topic" in cols:
            rows = conn.exec_driver_sql("SELECT id, platform, main_topic FROM videos").fetchall()
            for vid, platform, main_topic in rows:
                platforms = json.dumps([platform]) if platform else "[]"
                main_topics = json.dumps([main_topic]) if main_topic else "[]"
                conn.execute(
                    text("UPDATE videos SET platforms = :p, main_topics = :m WHERE id = :id"),
                    {"p": platforms, "m": main_topics, "id": vid},
                )
            try:
                conn.exec_driver_sql("ALTER TABLE videos DROP COLUMN platform")
                conn.exec_driver_sql("ALTER TABLE videos DROP COLUMN main_topic")
            except Exception:
                # SQLite 版本过低无法删列时保留旧列（新列已生效，无碍使用）
                pass


def _migrate_chat() -> None:
    """chat_messages 增加 conversation_id；存量消息归入默认会话。"""
    with engine.begin() as conn:
        cols = {row[1] for row in conn.exec_driver_sql("PRAGMA table_info(chat_messages)").fetchall()}
        if "conversation_id" not in cols:
            conn.exec_driver_sql(
                "ALTER TABLE chat_messages ADD COLUMN conversation_id INTEGER REFERENCES chat_conversations(id) ON DELETE CASCADE"
            )
        if conn.exec_driver_sql("SELECT COUNT(*) FROM chat_conversations").fetchone()[0] == 0:
            if conn.exec_driver_sql("SELECT COUNT(*) FROM chat_messages").fetchone()[0] > 0:
                conn.exec_driver_sql(
                    "INSERT INTO chat_conversations (title, created_at, updated_at) VALUES ('默认对话', datetime('now'), datetime('now'))"
                )
        first_id = conn.exec_driver_sql(
            "SELECT id FROM chat_conversations ORDER BY id LIMIT 1"
        ).fetchone()
        if first_id:
            conn.exec_driver_sql(
                "UPDATE chat_messages SET conversation_id = :cid WHERE conversation_id IS NULL",
                {"cid": first_id[0]},
            )


def init_db() -> None:
    from . import models  # noqa: F401  确保模型已注册

    Base.metadata.create_all(bind=engine)
    _migrate_videos()
    _migrate_chat()
    # R-021：首次启动把各功能默认提示词 seed 入库（版本 v1）
    from .services.prompt_service import ensure_defaults

    session = SessionLocal()
    try:
        ensure_defaults(session)
    finally:
        session.close()
