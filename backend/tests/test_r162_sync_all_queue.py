"""R-162 「同步所有博主前15条」队列化测试（mock 离线）。

覆盖：入队顺序（主博主 + 全部对标）、预置 running SyncJob（排队中…）、跳过运行中博主、
无账号博主跳过、消费者逐个复用预置 job、完成后自动重新对标。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import Base
from app.models.platform import Creator, CreatorAccount, SyncJob
from app.models.task import BackgroundTask
from app.services.platform_sync import enqueue_all_top15_sync, run_all_top15_sync


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


def test_enqueue_all_creates_queue_and_running_jobs(db):
    owner, bm1, bm2 = _seed(db)

    res = enqueue_all_top15_sync(db, owner)

    assert res["total"] == 3
    assert [e["creator_id"] for e in res["entries"]] == [owner.id, bm1.id, bm2.id]
    assert res["skipped"] == []
    # 每个博主预置一条 running 的同步记录（阶段「排队中…」），前端立即有动画
    for entry in res["entries"]:
        job = db.get(SyncJob, entry["job_id"])
        assert job.status == "running"
        assert job.scope == "daily"
        assert job.progress_note == "排队中…"
        task = db.get(BackgroundTask, entry["task_id"])
        assert task.kind == "platform_sync" and task.status == "pending"


def test_enqueue_skips_running_and_no_account(db):
    owner, bm1, bm2 = _seed(db)
    db.add(
        BackgroundTask(
            kind="platform_sync",
            status="running",
            payload=json.dumps({"scope": "daily", "creator_id": bm1.id}),
        )
    )
    db.add(Creator(kind="benchmark", parent_id=owner.id, name="对标无账号"))  # 无启用账号
    db.commit()

    res = enqueue_all_top15_sync(db, owner)

    assert [e["creator_id"] for e in res["entries"]] == [owner.id, bm2.id]
    assert any("对标A" in s for s in res["skipped"])
    assert any("对标无账号" in s for s in res["skipped"])


def test_consumer_reuses_precreated_jobs_and_reruns(db, monkeypatch):
    owner, bm1, bm2 = _seed(db)
    enq = enqueue_all_top15_sync(db, owner)
    job_ids = [e["job_id"] for e in enq["entries"]]

    calls: list[dict] = []

    def fake_run_sync(_db, **kw):
        calls.append(kw)
        return {"job_id": kw["job"].id, "message": "ok", "accounts": [], "posts": 1, "comments": 0}

    monkeypatch.setattr("app.services.platform_sync.run_sync", fake_run_sync)
    started: list[bool] = []
    monkeypatch.setattr(
        "app.services.benchmark.maybe_start_benchmark_rerun",
        lambda _db, refetch=True: started.append(refetch) or "started:1",
    )

    res = run_all_top15_sync(db, owner, enq["entries"])

    assert [c["creator_id"] for c in calls] == [owner.id, bm1.id, bm2.id]  # 逐个串行消费
    assert all(c["scope"] == "daily" and c["with_media"] is True for c in calls)
    assert [c["job"].id for c in calls] == job_ids  # 复用预置 SyncJob
    assert started == [False]  # 完成后自动重新对标（不重捞）
    assert res["creators"] == 3 and res["synced"] == 3 and res["failed"] == []
    assert "已自动触发" in res["message"]
    # 队列任务全部终态 done
    for entry in enq["entries"]:
        assert db.get(BackgroundTask, entry["task_id"]).status == "done"
