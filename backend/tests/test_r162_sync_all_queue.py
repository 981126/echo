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
from conftest import ensure_schema, fresh_engine
from sqlalchemy.orm import sessionmaker

from app.models.platform import Creator, CreatorAccount, SyncJob
from app.models.task import BackgroundTask
from app.services.platform_sync import all_top15_worker, enqueue_all_top15_sync, run_all_top15_sync


@pytest.fixture()
def db(tmp_path):
    eng = fresh_engine()
    ensure_schema(eng)
    session = sessionmaker(bind=eng, autoflush=False, autocommit=False)()
    yield session
    session.close()


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
    no_acc = Creator(kind="benchmark", parent_id=owner.id, name="对标无账号")
    db.add(no_acc)  # 无启用账号
    db.commit()

    res = enqueue_all_top15_sync(db, owner)

    assert [e["creator_id"] for e in res["entries"]] == [owner.id, bm2.id]
    # R-219：skipped 结构化 [{creator_id, name, reason}]，前端按博主展示跳过提示条
    assert {"creator_id": bm1.id, "name": "对标A", "reason": "已在运行"} in res["skipped"]
    assert {"creator_id": no_acc.id, "name": "对标无账号", "reason": "无启用账号"} in res["skipped"]


def test_consumer_reuses_precreated_jobs_and_reruns(db, monkeypatch):
    owner, bm1, bm2 = _seed(db)
    enq = enqueue_all_top15_sync(db, owner)
    job_ids = [e["job_id"] for e in enq["entries"]]

    calls: list[dict] = []

    def fake_run_sync(_db, **kw):
        # R-163：并发消费者用完即关会话，job 会 detached；在调用点取 id，避免事后访问
        calls.append({"creator_id": kw["creator_id"], "scope": kw["scope"], "with_media": kw["with_media"], "job_id": kw["job"].id})
        return {"job_id": kw["job"].id, "message": "ok", "accounts": [], "posts": 1, "comments": 0}

    monkeypatch.setattr("app.services.platform_sync.run_sync", fake_run_sync)
    started: list[bool] = []
    monkeypatch.setattr(
        "app.services.benchmark.maybe_start_benchmark_rerun",
        lambda _db, refetch=True: started.append(refetch) or "started:1",
    )

    res = run_all_top15_sync(db, owner, enq["entries"])

    # R-163：改为并发消费，完成顺序不保证；断言集合/次数
    assert sorted(c["creator_id"] for c in calls) == sorted([owner.id, bm1.id, bm2.id])
    assert len(calls) == 3
    assert all(c["scope"] == "daily" and c["with_media"] is True for c in calls)
    assert sorted(c["job_id"] for c in calls) == sorted(job_ids)  # 复用预置 SyncJob
    assert started == [False]  # 完成后自动重新对标（不重捞）
    assert res["creators"] == 3 and res["synced"] == 3 and res["failed"] == []
    assert "已自动触发" in res["message"]
    # 队列任务全部终态 done
    for entry in enq["entries"]:
        assert db.get(BackgroundTask, entry["task_id"]).status == "done"


# ---------- R-262：全量同步完成通知必须反映真实成功/失败 ----------


def test_all_accounts_failed_is_reported_as_failed(db, monkeypatch):
    """TikHub 402 等导致每个博主的账号全部失败时：不再算「已同步」，任务按失败上报、不触发重新对标。"""
    owner, _bm1, _bm2 = _seed(db)
    enq = enqueue_all_top15_sync(db, owner)
    err = "TikHub 请求失败: HTTP 402 Insufficient balance"

    def fake_run_sync(_db, **kw):
        return {
            "job_id": kw["job"].id,
            "message": "同步 1 个账号，更新作品 0",
            "accounts": [{"account_id": 1, "platform": "douyin", "error": err}],
            "posts": 0,
            "comments": 0,
        }

    monkeypatch.setattr("app.services.platform_sync.run_sync", fake_run_sync)
    started: list[bool] = []
    monkeypatch.setattr(
        "app.services.benchmark.maybe_start_benchmark_rerun",
        lambda _db, refetch=True: started.append(refetch) or "started:1",
    )

    res = run_all_top15_sync(db, owner, enq["entries"])

    assert res["synced"] == 0 and res["done"] == 0 and res["partial"] == 0
    assert len(res["failed"]) == 3
    assert "成功 0" in res["message"] and "失败 3" in res["message"]
    assert "全部同步成功" not in res["message"]
    assert started == []  # 没有任何同步成功 → 不触发「重新对标」
    for entry in enq["entries"]:
        assert db.get(BackgroundTask, entry["task_id"]).status == "failed"


def test_partial_account_failure_reported_as_partial(db, monkeypatch):
    """部分账号失败：算「部分失败」，仍有数据同步成功 → 照常触发重新对标。"""
    owner, _bm1, _bm2 = _seed(db)
    enq = enqueue_all_top15_sync(db, owner)

    def fake_run_sync(_db, **kw):
        return {
            "job_id": kw["job"].id,
            "message": "同步 2 个账号，更新作品 1",
            "accounts": [
                {"account_id": 1, "platform": "douyin", "posts": 1},
                {"account_id": 2, "platform": "bilibili", "error": "TikHub 请求失败: HTTP 402"},
            ],
            "posts": 1,
            "comments": 0,
        }

    monkeypatch.setattr("app.services.platform_sync.run_sync", fake_run_sync)
    started: list[bool] = []
    monkeypatch.setattr(
        "app.services.benchmark.maybe_start_benchmark_rerun",
        lambda _db, refetch=True: started.append(refetch) or "started:1",
    )

    res = run_all_top15_sync(db, owner, enq["entries"])

    assert res["synced"] == 3 and res["done"] == 0 and res["partial"] == 3
    assert "部分失败 3" in res["message"] and "部分失败：" in res["message"]
    assert started == [False]
    for entry in enq["entries"]:
        assert db.get(BackgroundTask, entry["task_id"]).status == "done"


def test_worker_raises_when_nothing_synced(db, monkeypatch):
    """全部博主同步失败时，后台任务抛错 → 通知标题为「平台数据同步失败」而不是「完成」。"""
    owner, _bm1, _bm2 = _seed(db)
    monkeypatch.setattr(
        "app.services.platform_sync.run_all_top15_sync",
        lambda *_a, **_k: {"message": "全量同步：共 3 个博主，成功 0、部分失败 0、失败 3", "synced": 0, "failed": ["a(402)"]},
    )
    with pytest.raises(RuntimeError, match="失败 3"):
        all_top15_worker(db, {"owner_id": owner.id, "entries": [{"task_id": 1, "creator_id": owner.id, "job_id": 1}]})
