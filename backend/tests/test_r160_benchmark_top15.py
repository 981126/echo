"""R-160 一键同步对标博主前15条测试（mock 离线）：遍历全部对标、跳过运行中、无对标报错、完成后自动重新对标。"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import Base
from app.models.platform import Creator, CreatorAccount
from app.models.task import BackgroundTask
from app.services.platform_sync import run_benchmark_top15_sync


@pytest.fixture()
def db(tmp_path):
    eng = create_engine(f"sqlite:///{tmp_path}/t.db", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=eng)
    session = sessionmaker(bind=eng, autoflush=False, autocommit=False)()
    yield session
    session.close()
    eng.dispose()


def _seed(db):
    owner = Creator(kind="owner", name="我", is_current=True)
    db.add(owner)
    db.commit()
    db.add(CreatorAccount(creator_id=owner.id, platform="douyin", nickname="我", platform_user_id="owner_uid", enabled=True))
    bm1 = Creator(kind="benchmark", parent_id=owner.id, name="对标A")
    bm2 = Creator(kind="benchmark", parent_id=owner.id, name="对标B")
    db.add_all([bm1, bm2])
    db.commit()
    for bm in (bm1, bm2):
        db.add(CreatorAccount(creator_id=bm.id, platform="douyin", nickname=bm.name, platform_user_id=f"uid{bm.id}", enabled=True))
    db.commit()
    return owner, bm1, bm2


def test_sync_all_benchmarks_and_rerun(db, monkeypatch):
    owner, bm1, bm2 = _seed(db)
    calls: list[dict] = []

    def fake_run_sync(_db, **kw):
        calls.append(kw)
        return {"job_id": len(calls), "message": "ok", "accounts": [], "posts": 1, "comments": 0}

    monkeypatch.setattr("app.services.platform_sync.run_sync", fake_run_sync)
    started: list[bool] = []
    monkeypatch.setattr(
        "app.services.benchmark.maybe_start_benchmark_rerun",
        lambda _db, refetch=True: started.append(refetch) or "started:1",
    )

    res = run_benchmark_top15_sync(db, owner)

    assert [c["creator_id"] for c in calls] == [bm1.id, bm2.id]
    assert all(c["scope"] == "daily" and c["with_media"] is True for c in calls)
    assert started == [False]  # 完成后自动重新对标（不重捞）
    assert res["benchmarks"] == 2 and res["synced"] == 2 and res["skipped"] == []
    assert "已自动触发" in res["message"]


def test_skips_running_benchmark(db, monkeypatch):
    owner, bm1, bm2 = _seed(db)
    db.add(
        BackgroundTask(
            kind="platform_sync",
            status="running",
            payload=json.dumps({"scope": "daily", "creator_id": bm1.id}),
        )
    )
    db.commit()
    calls: list[dict] = []

    monkeypatch.setattr(
        "app.services.platform_sync.run_sync",
        lambda _db, **kw: calls.append(kw) or {"job_id": 1, "message": "ok", "accounts": []},
    )
    started: list[bool] = []
    monkeypatch.setattr(
        "app.services.benchmark.maybe_start_benchmark_rerun",
        lambda _db, refetch=True: started.append(refetch) or "started:1",
    )

    res = run_benchmark_top15_sync(db, owner)

    assert [c["creator_id"] for c in calls] == [bm2.id]  # 只同步未在跑的对标
    assert res["skipped"] == ["对标A"]
    assert started == [False]


def test_no_benchmarks_raises(db):
    owner = Creator(kind="owner", name="我", is_current=True)
    db.add(owner)
    db.commit()
    with pytest.raises(ValueError):
        run_benchmark_top15_sync(db, owner)


def test_all_skipped_does_not_rerun(db, monkeypatch):
    owner, bm1, bm2 = _seed(db)
    for bm in (bm1, bm2):
        db.add(
            BackgroundTask(
                kind="platform_sync",
                status="pending",
                payload=json.dumps({"scope": "daily", "creator_id": bm.id}),
            )
        )
    db.commit()
    calls: list[dict] = []
    monkeypatch.setattr(
        "app.services.platform_sync.run_sync",
        lambda _db, **kw: calls.append(kw) or {"job_id": 1, "message": "ok"},
    )
    started: list[bool] = []
    monkeypatch.setattr(
        "app.services.benchmark.maybe_start_benchmark_rerun",
        lambda _db, refetch=True: started.append(refetch) or "started:1",
    )

    res = run_benchmark_top15_sync(db, owner)

    assert calls == []
    assert started == []  # 全跳过不触发重新对标
    assert res["rerun"] == "no_sync"
