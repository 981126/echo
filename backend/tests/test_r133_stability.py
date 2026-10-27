"""R-133：流水线失败传播与卡死自愈、超时判定测试。"""

from __future__ import annotations

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

