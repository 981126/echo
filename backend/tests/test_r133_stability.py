"""R-133：备份真实性、流水线失败传播与卡死自愈、超时判定测试。"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest
from conftest import ensure_schema, fresh_engine
from sqlalchemy.orm import sessionmaker

from app.core.pipeline import is_stale
from app.models.pipeline import PipelineRun
from app.services import pipeline as pipeline_mod
from app.services.pipeline import PipelineError, mark_stale_pipeline_runs_on_startup, run_daily_pipeline


@pytest.fixture()
def db(tmp_path):
    eng = fresh_engine()
    ensure_schema(eng)
    session = sessionmaker(bind=eng, autoflush=False, autocommit=False)()
    yield session
    session.close()


def test_is_stale_boundaries():
    assert is_stale(None) is True
    assert is_stale(datetime.now()) is False
    assert is_stale(datetime.now() - timedelta(hours=3)) is True
    assert is_stale("not-a-date") is True


def test_mark_stale_pipeline_runs_on_startup(db):
    db.add(PipelineRun(run_date="2026-09-11", status="running"))
    db.add(PipelineRun(run_date="2026-09-10", status="done"))
    db.commit()
    n = mark_stale_pipeline_runs_on_startup(db)
    assert n == 1
    running = db.query(PipelineRun).filter(PipelineRun.status == "running").count()
    assert running == 0
    failed = db.query(PipelineRun).filter(PipelineRun.run_date == "2026-09-11").first()
    assert failed.status == "failed" and "已自动标记" in failed.error


def test_pipeline_failure_raises_and_marks_failed(db, monkeypatch):
    def _boom(_db, _settings):
        raise RuntimeError("热点源挂了")

    monkeypatch.setattr(pipeline_mod, "fetch_and_store", _boom)
    monkeypatch.setattr(pipeline_mod, "send_failure_alert", lambda *_a, **_k: False)

    with pytest.raises(PipelineError) as exc:
        run_daily_pipeline(db)
    assert "热点源挂了" in str(exc.value)
    run = db.query(PipelineRun).order_by(PipelineRun.id.desc()).first()
    assert run is not None and run.status == "failed" and "热点源挂了" in run.error


def test_pipeline_fresh_running_is_skipped(db, monkeypatch):
    db.add(PipelineRun(run_date=pipeline_mod.today_key(), status="running", created_at=datetime.now()))
    db.commit()
    called = []

    monkeypatch.setattr(pipeline_mod, "fetch_and_store", lambda *_a: called.append(1) or [])
    run = run_daily_pipeline(db)
    assert run.status == "running"  # 未超时 → 直接跳过
    assert called == []


def test_pipeline_stale_running_is_rerun(db, monkeypatch):
    db.add(
        PipelineRun(
            run_date=pipeline_mod.today_key(),
            status="running",
            created_at=datetime.now() - timedelta(hours=3),
        )
    )
    db.commit()
    monkeypatch.setattr(pipeline_mod, "fetch_and_store", lambda *_a: [])
    monkeypatch.setattr(pipeline_mod, "_compose_daily_candidates", lambda *_a, **_k: [])
    monkeypatch.setattr(pipeline_mod, "send_daily_digest", lambda *_a, **_k: True)

    run = run_daily_pipeline(db)
    assert run.status == "done"  # 超时卡死被自愈并可重跑
    assert run.generated_count == 0


# ---------- 备份脚本（R-133 核心修复，R-235 改 pg_dump） ----------


@pytest.mark.skipif(shutil.which("pg_dump") is None, reason="本机未安装 pg_dump（PG 客户端工具）")
def test_backup_script_uses_env_db_url_and_validates(tmp_path):
    repo = Path(__file__).resolve().parents[2]
    (tmp_path / "scripts").mkdir()
    shutil.copy(repo / "scripts" / "backup.sh", tmp_path / "scripts" / "backup.sh")
    (tmp_path / "docs").mkdir()
    (tmp_path / "requirements").mkdir()

    from app.config import get_settings

    db_url = get_settings().database_url  # 指向 conftest 闸门允许的 echo_test

    # backup.sh 现在「环境变量优先、其次 .env」。本用例测 .env 路径，
    # 所以显式清空继承来的 ECHO_DATABASE_URL。
    env = {**os.environ, "ECHO_DATABASE_URL": ""}
    (tmp_path / ".env").write_text(f'ECHO_DATABASE_URL="{db_url}"\n', encoding="utf-8")

    proc = subprocess.run(
        ["bash", str(tmp_path / "scripts" / "backup.sh")],
        capture_output=True,
        text=True,
        cwd=tmp_path,
        env=env,
    )
    assert proc.returncode == 0, proc.stderr + proc.stdout
    dumps = list((tmp_path / "data" / "backups").glob("*/echo.dump"))
    assert dumps, proc.stdout
    assert dumps[0].stat().st_size > 0

    # 坏连接串 → 明确失败（而不是静默产出空备份）
    (tmp_path / ".env").write_text('ECHO_DATABASE_URL="postgresql+psycopg://bad:b@d@127.0.0.1:1/none"\n', encoding="utf-8")
    proc2 = subprocess.run(
        ["bash", str(tmp_path / "scripts" / "backup.sh")],
        capture_output=True,
        text=True,
        cwd=tmp_path,
        env=env,
    )
    assert proc2.returncode != 0
    assert "备份失败" in (proc2.stderr + proc2.stdout)


def test_backup_script_fails_without_db_url(tmp_path):
    """未配置 ECHO_DATABASE_URL 时备份脚本非零退出并提示（R-235 fail-closed）。"""
    repo = Path(__file__).resolve().parents[2]
    (tmp_path / "scripts").mkdir()
    shutil.copy(repo / "scripts" / "backup.sh", tmp_path / "scripts" / "backup.sh")
    env = {**os.environ, "ECHO_DATABASE_URL": ""}
    proc = subprocess.run(
        ["bash", str(tmp_path / "scripts" / "backup.sh")],
        capture_output=True,
        text=True,
        cwd=tmp_path,
        env=env,
    )
    assert proc.returncode != 0
    assert "ECHO_DATABASE_URL" in (proc.stderr + proc.stdout)

