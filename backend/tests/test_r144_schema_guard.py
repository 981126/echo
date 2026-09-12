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


# ---------- R-145：启动即自动升级 → 升级前自动备份 / 打包部署脚本 ----------


def _make_old_db(path, *, tables: int = 0):
    """建一个「老结构」库（默认用生产结构快照；tables=1 时只建一张表以示差异）。"""
    con = sqlite3.connect(path)
    try:
        if tables == 0:
            con.executescript(BASELINE_SQL.read_text(encoding="utf-8"))
        else:
            con.execute("CREATE TABLE demo(id INTEGER)")
            con.execute("INSERT INTO demo VALUES (1)")
        con.commit()
    finally:
        con.close()


def test_pending_upgrade_detects_old_schema(tmp_path, monkeypatch):
    from app.config import get_settings

    old = tmp_path / "old.db"
    _make_old_db(old)
    monkeypatch.setattr(get_settings(), "db_path", old, raising=False)
    eng = create_engine(f"sqlite:///{old}")
    try:
        pending = schema_guard.pending_upgrade(eng, db_path=old)
        assert pending and "schema_migrations" in pending["missing_tables"]
    finally:
        eng.dispose()


def test_pending_upgrade_is_none_when_current(tmp_path, engine):
    assert schema_guard.pending_upgrade(engine) is None


def test_pending_upgrade_is_none_for_fresh_install(tmp_path):
    """全新安装（库文件不存在）→ 没什么可备份，且**不能**因为探测而建出空库。"""
    missing = tmp_path / "not_yet.db"
    eng = create_engine(f"sqlite:///{missing}")
    try:
        assert schema_guard.pending_upgrade(eng, db_path=missing) is None
    finally:
        eng.dispose()
    assert not missing.exists(), "判断待升级不应创建库文件"


def test_auto_backup_before_upgrade_creates_verifiable_copy(tmp_path, monkeypatch):
    from app.config import get_settings

    db_file = tmp_path / "echo.db"
    _make_old_db(db_file, tables=1)  # 有数据，便于校验备份可用
    monkeypatch.setattr(get_settings(), "db_path", db_file, raising=False)
    eng = create_engine(f"sqlite:///{db_file}")
    try:
        out = schema_guard.auto_backup_before_upgrade(eng, data_dir=tmp_path)
    finally:
        eng.dispose()
    assert out, "应产出备份文件"
    copy = sqlite3.connect(out)
    try:
        assert copy.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert copy.execute("SELECT count(*) FROM demo").fetchone()[0] == 1, "备份应包含真实数据"
    finally:
        copy.close()
    assert "pre_upgrade" in out


def test_auto_backup_keeps_only_recent(tmp_path, monkeypatch):
    from app.config import get_settings

    db_file = tmp_path / "echo.db"
    _make_old_db(db_file, tables=1)
    monkeypatch.setattr(get_settings(), "db_path", db_file, raising=False)
    eng = create_engine(f"sqlite:///{db_file}")
    try:
        for i in range(schema_guard.KEEP_PRE_UPGRADE + 3):
            out = schema_guard.auto_backup_before_upgrade(eng, data_dir=tmp_path)
            assert out
            # 让时间戳文件名不同（同秒会互相覆盖，所以直接改名模拟不同时刻）
            Path(out).rename(Path(out).with_name(f"2026010{i % 9}_12000{i}.db"))
    finally:
        eng.dispose()
    kept = list((tmp_path / "backups" / "pre_upgrade").glob("*.db"))
    assert len(kept) <= schema_guard.KEEP_PRE_UPGRADE, f"应只保留 {schema_guard.KEEP_PRE_UPGRADE} 份，实际 {len(kept)}"


def test_startup_upgrade_flow_backs_up_then_migrates(tmp_path, monkeypatch):
    """复现作者要的链路：老库 + 新版本代码 → 启动时自动「先备份 → 再增量升级」。"""
    from app import db as db_mod
    from app.config import get_settings

    db_file = tmp_path / "prod_like.db"
    _make_old_db(db_file)
    monkeypatch.setattr(get_settings(), "db_path", db_file, raising=False)
    monkeypatch.setattr(get_settings(), "data_dir", tmp_path, raising=False)

    eng = create_engine(f"sqlite:///{db_file}", connect_args={"check_same_thread": False})
    monkeypatch.setattr(db_mod, "engine", eng)
    monkeypatch.setattr(db_mod, "SessionLocal", sessionmaker(bind=eng, autoflush=False, autocommit=False))

    # ① 启动时先判断 + 备份（app/main.py lifespan 的顺序）
    pending = schema_guard.pending_upgrade(eng, db_path=db_file)
    assert pending, "老库应被判定为有待应用变更"
    backup = schema_guard.auto_backup_before_upgrade(eng, data_dir=tmp_path)
    assert backup and Path(backup).exists()

    # ② 再升级
    db_mod.init_db()
    assert schema_guard.missing_schema(eng)["ok"] is True

    # ③ 重复启动：不再有待应用变更 → 不会再备份（幂等）
    assert schema_guard.pending_upgrade(eng, db_path=db_file) is None
    assert len(list((tmp_path / "backups" / "pre_upgrade").glob("*.db"))) == 1
    eng.dispose()


def test_release_script_packages_without_secrets(tmp_path):
    """release.sh 用 git archive 打包：只含被跟踪文件（不含 .env/data/node_modules）。"""
    import shutil
    import subprocess as sp

    if shutil.which("git") is None or not (REPO_ROOT / ".git").exists():
        pytest.skip("需要 git 仓库")
    proc = sp.run(
        ["git", "archive", "--format=tar.gz", "-o", str(tmp_path / "pkg.tar.gz"), "--prefix=echo/", "HEAD"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stderr
    listing = sp.run(["tar", "-tzf", str(tmp_path / "pkg.tar.gz")], capture_output=True, text=True).stdout
    # 逐行精确比较：不能用子串（"echo/.env" 会匹配到 "echo/.env.example"）
    lines = {ln.strip() for ln in listing.splitlines() if ln.strip()}
    assert "echo/backend/app/db.py" in lines
    assert "echo/scripts/backup.sh" in lines
    assert "echo/backend/tests/fixtures/schema_baseline.sql" in lines
    assert "echo/.env" not in lines, "发布包绝不能带 .env（含密钥）"
    assert not any(ln.startswith("echo/data/") for ln in lines), "发布包不能带运行时数据"
    assert not any(".venv/" in ln or "node_modules/" in ln for ln in lines)

    script = (REPO_ROOT / "scripts" / "release.sh").read_text(encoding="utf-8")
    for token in ("git archive", "git status --porcelain", "echo/.env"):
        assert token in script


def test_update_script_has_backup_health_and_version_steps():
    """update.sh 必须是「先备份 → 构建 → 启动 → 健康检查 → 结构版本」且任一步失败即退出。"""
    script = (REPO_ROOT / "scripts" / "update.sh").read_text(encoding="utf-8")
    assert "set -euo pipefail" in script
    assert "scripts/backup.sh" in script
    assert "docker compose build" in script and "docker compose up -d" in script
    assert "健康检查" in script and "结构自检与库结构版本" in script
    assert script.index("scripts/backup.sh") < script.index("docker compose build"), "备份必须在构建/启动之前"
