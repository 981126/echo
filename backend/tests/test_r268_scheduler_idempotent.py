"""R-268 定时同步跨进程幂等：app_kv 唯一键抢占 + 任务体跳过。"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest
from conftest import ensure_schema, fresh_engine
from sqlalchemy.orm import sessionmaker

from app.models.task import BackgroundTask
from app.services.platform_sync import claim_daily_sync_slot, release_daily_sync_slot


@pytest.fixture()
def db():
    eng = fresh_engine()
    ensure_schema(eng)
    session = sessionmaker(bind=eng, autoflush=False, autocommit=False)()
    yield session
    session.close()


def test_claim_once(db):
    assert claim_daily_sync_slot(db, "06:00") is True
    assert claim_daily_sync_slot(db, "06:00") is False


def test_two_sessions_same_slot(fresh_engine_factory):
    session_a = fresh_engine_factory()
    session_b = fresh_engine_factory()
    try:
        assert claim_daily_sync_slot(session_a, "06:00") is True
        assert claim_daily_sync_slot(session_b, "06:00") is False
    finally:
        session_a.close()
        session_b.close()


def test_concurrent_threads(fresh_engine_factory):
    from concurrent.futures import ThreadPoolExecutor

    def _claim(_i: int) -> bool:
        session = fresh_engine_factory()
        try:
            return claim_daily_sync_slot(session, "17:00")
        finally:
            session.close()

    with ThreadPoolExecutor(max_workers=10) as pool:
        results = list(pool.map(_claim, range(10)))
    assert results.count(True) == 1


def test_release_allows_retry(db):
    assert claim_daily_sync_slot(db, "06:00") is True
    release_daily_sync_slot(db, "06:00")
    assert claim_daily_sync_slot(db, "06:00") is True


def test_slot_isolation(db):
    assert claim_daily_sync_slot(db, "06:00") is True
    assert claim_daily_sync_slot(db, "17:00") is True


def test_next_day_new_key(db, monkeypatch):
    import app.services.platform_sync as sync_mod

    assert claim_daily_sync_slot(db, "06:00") is True
    monkeypatch.setattr(sync_mod, "today_key", lambda: "2099-01-01")
    assert claim_daily_sync_slot(db, "06:00") is True


def test_job_skips_when_claimed(db, monkeypatch):
    import app.tasks as tasks_mod
    from app.scheduler import _platform_sync_job

    calls: list[dict] = []
    monkeypatch.setattr(tasks_mod, "start_task", lambda *args, **kwargs: calls.append({"args": args}) or 1)
    assert claim_daily_sync_slot(db, "06:00") is True
    _platform_sync_job("06:00")
    assert calls == []


def test_job_claims_and_enqueues(db, monkeypatch):
    import app.tasks as tasks_mod
    from app.scheduler import _platform_sync_job

    calls: list[dict] = []

    def _fake_start(kind, payload, fn, **kwargs):
        calls.append({"kind": kind, "payload": payload})
        return 42

    monkeypatch.setattr(tasks_mod, "start_task", _fake_start)
    _platform_sync_job("06:00")
    assert len(calls) == 1
    assert calls[0]["kind"] == "platform_sync"
    assert calls[0]["payload"]["slot"] == "06:00"
    assert calls[0]["payload"]["source"] == "scheduler"
    # 同一时段第二次触发：占位已存在 → 跳过
    _platform_sync_job("06:00")
    assert len(calls) == 1


def test_job_skips_other_instance_task(db, monkeypatch):
    """模拟另一实例已经跑过（占位存在但本进程没有任何任务）。"""
    import app.tasks as tasks_mod
    from app.scheduler import _platform_sync_job

    calls: list[str] = []
    monkeypatch.setattr(tasks_mod, "start_task", lambda *args, **kwargs: calls.append("x") or 1)
    assert claim_daily_sync_slot(db, "17:00") is True
    _platform_sync_job("17:00")
    assert calls == []
    assert db.query(BackgroundTask).count() == 0


@pytest.fixture()
def fresh_engine_factory():
    eng = fresh_engine()
    ensure_schema(eng)
    maker = sessionmaker(bind=eng, autoflush=False, autocommit=False)

    def _make():
        return maker()

    yield _make
