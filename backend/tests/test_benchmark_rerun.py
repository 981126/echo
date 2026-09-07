"""R-102 再次对标服务测试：重跑汇总/空对标报错/单对标失败不阻断（mock 离线）。"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import Base
from app.models.platform import Creator, CreatorAccount
from app.services.benchmark import rerun_benchmarks


@pytest.fixture()
def db(tmp_path):
    eng = create_engine(f"sqlite:///{tmp_path}/t.db", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=eng)
    session = sessionmaker(bind=eng, autoflush=False, autocommit=False)()
    yield session
    session.close()
    eng.dispose()


def _owner(db):
    c = Creator(kind="owner", name="我", is_current=True)
    db.add(c)
    db.commit()
    return c


def _benchmark(db, owner, name="对标A"):
    bm = Creator(kind="benchmark", parent_id=owner.id, name=name)
    db.add(bm)
    db.commit()
    acc = CreatorAccount(creator_id=bm.id, platform="douyin", nickname=name, enabled=True)
    db.add(acc)
    db.commit()
    return bm


def test_rerun_no_benchmarks_raises(db):
    owner = _owner(db)
    with pytest.raises(ValueError):
        rerun_benchmarks(db, owner)


def test_rerun_ok_with_mock_sync(db, monkeypatch):
    owner = _owner(db)
    _benchmark(db, owner, "对标A")
    monkeypatch.setattr("app.services.platform_sync.sync_account", lambda *a, **k: {"posts": 0})
    updates: list[tuple[int, str]] = []

    def _up(pct, note=""):
        updates.append((pct, note))

    result = rerun_benchmarks(db, owner, update=_up)
    assert result["benchmark_count"] == 1
    assert result["ok_count"] == 1
    assert result["summary"][0]["name"] == "对标A"
    assert result["summary"][0]["top3_with_text"] == 0
    assert updates and updates[-1][0] == 99  # 留给 worker 收尾置 100


def test_rerun_single_benchmark_failure_does_not_block_others(db, monkeypatch):
    owner = _owner(db)
    _benchmark(db, owner, "会失败")
    _benchmark(db, owner, "会成功")
    monkeypatch.setattr("app.services.platform_sync.sync_account", lambda *a, **k: {"posts": 0})

    def _fake_ensure(db, bm, limit_candidates=10):
        if bm.name == "会失败":
            raise RuntimeError("mock 失败")
        return []

    monkeypatch.setattr("app.services.benchmark.ensure_top3_with_text", _fake_ensure)
    result = rerun_benchmarks(db, owner)
    assert result["benchmark_count"] == 2
    assert result["ok_count"] == 1
    by_name = {r["name"]: r for r in result["summary"]}
    assert by_name["会失败"]["error"]
    assert by_name["会成功"]["error"] == ""


def _mk_task(db, status="running"):
    from app.models.task import BackgroundTask

    t = BackgroundTask(kind="benchmark_rerun", status=status)
    db.add(t)
    db.commit()
    return t


def test_maybe_start_no_owner_skips(db):
    from app.services.benchmark import maybe_start_benchmark_rerun

    assert maybe_start_benchmark_rerun(db) == "no_owner"


def test_maybe_start_no_benchmark_skips(db):
    from app.services.benchmark import maybe_start_benchmark_rerun

    _owner(db)
    assert maybe_start_benchmark_rerun(db) == "no_benchmark"


def test_maybe_start_skips_when_running(db):
    from app.services.benchmark import maybe_start_benchmark_rerun

    owner = _owner(db)
    _benchmark(db, owner, "对标A")
    _mk_task(db, "running")
    assert maybe_start_benchmark_rerun(db) == "already_running"


def test_maybe_start_ok(db, monkeypatch):
    from app.services.benchmark import maybe_start_benchmark_rerun

    owner = _owner(db)
    _benchmark(db, owner, "对标A")
    captured = {}

    def fake_start(kind, payload, fn):
        captured["kind"] = kind
        captured["payload"] = payload
        captured["fn"] = fn
        return 88

    monkeypatch.setattr("app.tasks.start_task", fake_start)
    assert maybe_start_benchmark_rerun(db) == "started:88"
    assert captured["kind"] == "benchmark_rerun"
    assert captured["payload"] == {"owner_id": owner.id, "refetch": True}


def test_rerun_refetch_false_skips_sync(db, monkeypatch):
    """R-109：每日同步后自动触发「重新对标」用 refetch=False——不重复拉取 TikHub。"""
    owner = _owner(db)
    _benchmark(db, owner, "对标A")
    sync_calls = {"n": 0}

    def _sync(*_a, **_k):
        sync_calls["n"] += 1
        return {"posts": 0}

    monkeypatch.setattr("app.services.platform_sync.sync_account", _sync)
    result = rerun_benchmarks(db, owner, refetch=False)
    assert sync_calls["n"] == 0
    assert result["ok_count"] == 1


def test_rerun_refetch_true_syncs_top15(db, monkeypatch):
    """R-109：手动「重新对标」refetch=True——每账号重捞最新 15 条（原 10 → 15）。"""
    owner = _owner(db)
    _benchmark(db, owner, "对标A")
    captured: dict = {}

    def _sync(_db, _acc, **kw):
        captured.update(kw)
        return {"posts": 0}

    monkeypatch.setattr("app.services.platform_sync.sync_account", _sync)
    rerun_benchmarks(db, owner)
    assert captured.get("scope") == "benchmark"
    assert captured.get("top_n") == 15
