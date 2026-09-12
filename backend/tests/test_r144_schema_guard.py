"""R-144 上线部署加固测试：镜像契约 / 结构自检 / 老库升级兼容性 / 迁移记账。

四件事各自治一个已查证的问题：
- A 镜像契约：`scripts/` 必须进镜像（否则容器里 `scheduler._backup_job` 每晚报「备份脚本不存在」）；
  构建上下文必须排除宿主机的 `node_modules`（否则覆盖镜像内的 Linux 版 esbuild → 前端构建失败）；
  健康检查不能依赖 `curl`（python:3.12-slim 没有）。
- B 启动结构自检：模型声明了列、库里没有 → 必须能检出并留下可读告警，且**绝不影响启动**。
- C 老库升级：用生产库结构快照模拟老库，跑 `init_db()` 后断言模型每一张表、每一列都存在
  —— 这是治「加了字段忘了写迁移，而本地测试全用全新库所以 100% 绿」的唯一办法。
- D 迁移记账：`schema_migrations` 幂等写入 + 能读出库结构版本。
"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core import schema_guard
from app.db import Base
from app.models.kv import Kv
from app.models.notification import Notification

REPO_ROOT = Path(__file__).resolve().parents[2]
BASELINE_SQL = Path(__file__).resolve().parent / "fixtures" / "schema_baseline.sql"


@pytest.fixture()
def engine(tmp_path):
    eng = create_engine(f"sqlite:///{tmp_path}/guard.db", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=eng)
    yield eng
    eng.dispose()


# ---------- A：镜像与构建契约 ----------


def test_dockerfile_ships_scripts():
    """镜像必须带 scripts/ —— 备份脚本在容器里不存在 = 每日备份永不执行 = 没有回滚预案。"""
    dockerfile = (REPO_ROOT / "Dockerfile").read_text(encoding="utf-8")
    assert "COPY scripts/" in dockerfile, "Dockerfile 必须把 scripts/ 打进镜像（R-144 A）"
    assert (REPO_ROOT / "scripts" / "backup.sh").exists()


def test_dockerignore_excludes_host_artifacts():
    """构建上下文必须排除 node_modules / .venv / data —— 既省上传，也避免覆盖镜像内依赖。"""
    ignore = (REPO_ROOT / ".dockerignore").read_text(encoding="utf-8")
    for pattern in ("node_modules/", ".venv/", "data/", ".git/"):
        assert pattern in ignore, f".dockerignore 应排除 {pattern}"


def test_compose_healthcheck_does_not_need_curl():
    """python:3.12-slim 没有 curl，健康检查必须用镜像里必然存在的东西（python urllib）。"""
    compose = (REPO_ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    # 只看非注释行，避免注释里提到 curl 就误判
    body = "\n".join(ln for ln in compose.splitlines() if not ln.strip().startswith("#"))
    health = body.split("healthcheck")[1].split("volumes")[0]
    assert "curl" not in health, "健康检查不要用 curl（slim 镜像里没有），用 python urllib"
    assert "urllib" in health


def test_backup_script_honours_env_vars():
    """容器里没有 .env 文件，只有注入的环境变量 —— 备份脚本必须优先读环境变量。"""
    script = (REPO_ROOT / "scripts" / "backup.sh").read_text(encoding="utf-8")
    assert "${ECHO_DB_PATH:-" in script and "${ECHO_DATA_DIR:-" in script


# ---------- B：结构自检 ----------


def test_missing_schema_detects_missing_column_and_table(engine):
    with engine.begin() as conn:
        conn.exec_driver_sql("ALTER TABLE drafts DROP COLUMN tags")
        conn.exec_driver_sql("DROP TABLE feedback")
    report = schema_guard.missing_schema(engine)
    assert report["ok"] is False
    assert "drafts.tags" in report["missing_columns"]
    assert "feedback" in report["missing_tables"]


def test_missing_schema_ok_on_current_schema(engine):
    assert schema_guard.missing_schema(engine) == {"missing_tables": [], "missing_columns": [], "ok": True}


def test_startup_check_alerts_without_blocking(engine, tmp_path, monkeypatch):
    """缺列时：返回 ok=False、写 app_kv + 站内通知，且**不抛异常**（绝不阻塞启动）。"""
    with engine.begin() as conn:
        conn.exec_driver_sql("ALTER TABLE drafts DROP COLUMN tags")
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    report = schema_guard.run_startup_check(engine, session_factory=factory)
    assert report["ok"] is False and "drafts.tags" in report["missing_columns"]

    session = factory()
    try:
        assert session.get(Kv, schema_guard.SCHEMA_CHECK_KV) is not None, "自检结果应落 app_kv"
        notes = session.query(Notification).filter(Notification.kind == "schema_check").all()
        assert notes, "结构自检发现问题必须写站内通知"
        assert "drafts.tags" in notes[0].message
    finally:
        session.close()


def test_startup_check_never_raises_on_broken_bind():
    """自检自己出问题（bind 不可用）也不能影响启动。"""
    class _Broken:
        def connect(self):
            raise RuntimeError("boom")

    report = schema_guard.run_startup_check(_Broken())  # type: ignore[arg-type]
    assert report["ok"] is False and "error" in report


# ---------- C：老库升级（核心） ----------


def test_upgrade_from_prod_snapshot_adds_everything(tmp_path, monkeypatch):
    """用生产库结构快照模拟「老库」→ 跑 init_db() → 模型声明的表/列必须全都在。

    若以后往模型加了字段却忘了写 `_migrate_*`，这个测试会失败 —— 这正是它的存在意义。
    """
    from app import db as db_mod

    old_db = tmp_path / "old_prod.db"
    con = sqlite3.connect(old_db)
    try:
        con.executescript(BASELINE_SQL.read_text(encoding="utf-8"))
        con.commit()
    finally:
        con.close()

    eng = create_engine(f"sqlite:///{old_db}", connect_args={"check_same_thread": False})
    monkeypatch.setattr(db_mod, "engine", eng)
    monkeypatch.setattr(db_mod, "SessionLocal", sessionmaker(bind=eng, autoflush=False, autocommit=False))
    db_mod.init_db()

    report = schema_guard.missing_schema(eng)
    assert report["ok"] is True, f"老库升级后仍缺表/列：{report}"
    # 新表也建出来了
    tables = {row[0] for row in eng.connect().exec_driver_sql("SELECT name FROM sqlite_master WHERE type='table'")}
    assert "schema_migrations" in tables
    eng.dispose()


def test_baseline_snapshot_is_schema_only():
    """快照只含结构、不含数据 —— 别把生产数据误提交进仓库。"""
    text = BASELINE_SQL.read_text(encoding="utf-8")
    assert "CREATE TABLE" in text
    assert "INSERT INTO" not in text.upper()
    assert text.count("CREATE TABLE") == 27, "快照应记录 27 张表（R-143 时点的生产结构）"


# ---------- D：迁移记账 ----------


def test_record_migration_is_idempotent(engine):
    assert schema_guard.record_migration(engine, "r145_add_xxx") is True
    assert schema_guard.record_migration(engine, "r145_add_xxx") is False
    assert schema_guard.applied_migrations(engine) == ["r145_add_xxx"]


def test_ensure_baseline_once(engine):
    assert schema_guard.ensure_baseline(engine) is True
    assert schema_guard.ensure_baseline(engine) is False
    status = schema_guard.migration_status(engine)
    assert status["has_baseline"] is True
    assert status["applied"] == 1
    assert status["latest"] == schema_guard.BASELINE_MIGRATION
