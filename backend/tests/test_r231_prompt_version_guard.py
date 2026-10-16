"""R-231：提示词无启用版兜底——启动时无 enabled 的 key 自动另存启用代码默认。

背景：generation v1~v10 曾被提示词页面操作/自动优化链路搅成全 archived，运行时
静默回退代码默认、界面却显示「无启用版本」，作者无法判断当前生效的是哪一版。
幂等：已有 enabled 的 key 不动；重复执行不翻倍版本号。
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import Base
from app.models.prompt import AiPrompt
from app.services.prompt_service import (
    default_content,
    ensure_enabled_fallback,
    get_prompt,
    save_new_version,
)


@pytest.fixture()
def db(tmp_path):
    eng = create_engine(f"sqlite:///{tmp_path}/t.db", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=eng)
    session = sessionmaker(bind=eng, autoflush=False, autocommit=False)()
    yield session
    session.close()
    eng.dispose()


def _enabled(db, key):
    return (
        db.query(AiPrompt)
        .filter(AiPrompt.key == key, AiPrompt.status == "enabled")
        .order_by(AiPrompt.version.desc())
        .first()
    )


def test_fallback_enables_code_default_when_all_archived(db):
    """generation 全 archived（复刻线上状态）→ 兜底另存一版并启用代码默认。"""
    row = AiPrompt(key="generation", version=10, content="旧内容", status="archived", note="历史")
    db.add(row)
    db.commit()

    ensure_enabled_fallback(db)

    enabled = _enabled(db, "generation")
    assert enabled is not None
    assert enabled.content == default_content("generation")
    assert enabled.content != "旧内容"
    assert "兜底启用代码默认" in enabled.note
    # 历史版本留痕不删（1 条历史 + 1 条兜底）
    assert db.query(AiPrompt).filter(AiPrompt.key == "generation").count() == 2


def test_fallback_idempotent_when_enabled_exists(db):
    """已有 enabled 的 key 不被改动、不新增版本。"""
    save_new_version(db, "generation", default_content("generation"), note="手动启用")
    before = db.query(AiPrompt).filter(AiPrompt.key == "generation").count()
    before_version = _enabled(db, "generation").version

    ensure_enabled_fallback(db)

    assert db.query(AiPrompt).filter(AiPrompt.key == "generation").count() == before
    assert _enabled(db, "generation").version == before_version


def test_fallback_idempotent_on_second_run(db):
    """连续跑两次：第二次不再新增版本（启动幂等）。"""
    db.add(AiPrompt(key="generation", version=1, content="x", status="archived"))
    db.commit()

    ensure_enabled_fallback(db)
    ensure_enabled_fallback(db)

    versions = db.query(AiPrompt).filter(AiPrompt.key == "generation").all()
    assert len(versions) == 2  # 1 历史 + 1 兜底
    assert get_prompt("generation", db) == default_content("generation")


def test_fallback_covers_all_meta_keys(db):
    """空库（无 seed）下兜底为每个 PROMPT_META key 建 enabled = 代码默认。"""
    from app.services.prompt_service import PROMPT_META

    ensure_enabled_fallback(db)

    for key in PROMPT_META:
        enabled = _enabled(db, key)
        assert enabled is not None, key
        assert enabled.content == default_content(key)
