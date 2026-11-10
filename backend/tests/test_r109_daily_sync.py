"""R-109 每日统一同步测试：主博主+对标一起进每日两轮，同步后自动触发重新对标（mock 离线）。"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest
from conftest import ensure_schema, fresh_engine
from sqlalchemy.orm import sessionmaker

from app.models.platform import Creator, CreatorAccount
from app.services.platform_sync import run_daily_sync_all


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
    db.add(
        CreatorAccount(
            creator_id=owner.id, platform="douyin", nickname="我",
            platform_user_id="owner_uid", enabled=True, sync_frequency="daily",
        )
    )
    bm = Creator(kind="benchmark", parent_id=owner.id, name="对标A")
    db.add(bm)
    db.commit()
    db.add(
        CreatorAccount(
            creator_id=bm.id, platform="douyin", nickname="对标A",
            platform_user_id="bm_uid", enabled=True, sync_frequency="daily",
        )
    )
    db.commit()
    return owner, bm


def test_daily_sync_all_covers_owner_and_benchmarks(db, monkeypatch):
    owner, bm = _seed(db)
    calls: list[dict] = []

    def fake_run_sync(_db, **kw):
        calls.append(kw)
        return {"job_id": len(calls), "message": "ok", "accounts": [{"account_id": 1}], "posts": 3, "comments": 0}

    monkeypatch.setattr("app.services.platform_sync.run_sync", fake_run_sync)
    started: list = []
    monkeypatch.setattr(
        "app.services.benchmark.maybe_start_benchmark_rerun",
        lambda _db, refetch=True: started.append(refetch) or "started:1",
    )

    res = run_daily_sync_all(db)

    assert len(calls) == 2  # 主博主 + 1 个对标
    # R-163：改为并发同步，完成顺序不保证；主博主仍为 creator_id=None（当前主博主语义）
    by_creator = {c.get("creator_id"): c for c in calls}
    assert set(by_creator) == {None, bm.id}
    assert all(c["scope"] == "daily" for c in calls)
    assert all(c["with_media"] is True for c in calls)  # 对标同样下载视频+转写
    assert started == [False]  # 同步完成后自动触发重新对标（不重捞）
    assert "对标" in res["message"]


def test_daily_sync_all_no_owner_raises(db):
    with pytest.raises(ValueError):
        run_daily_sync_all(db)


# ---------- R-262：每日同步通知按账号真实成功/失败统计 ----------


def test_daily_sync_all_reports_ok_and_failed_accounts(db, monkeypatch):
    """部分账号失败：日更 message 明确写「成功 X、失败 Y 个账号」，并附失败原因。"""
    _seed(db)

    def fake_run_sync(_db, **kw):
        return {
            "job_id": 1,
            "message": "ok",
            "accounts": [
                {"account_id": 1, "platform": "douyin", "posts": 1},
                {"account_id": 2, "platform": "bilibili", "error": "TikHub 请求失败: HTTP 402"},
            ],
            "posts": 1,
            "comments": 0,
        }

    monkeypatch.setattr("app.services.platform_sync.run_sync", fake_run_sync)
    monkeypatch.setattr("app.services.benchmark.maybe_start_benchmark_rerun", lambda _db, refetch=True: "started:1")

    res = run_daily_sync_all(db)

    # 主博主 + 1 个对标，各返回 1 成功 1 失败 → 成功 2、失败 2
    assert res["ok_accounts"] == 2 and res["failed_accounts"] == 2
    assert res["accounts"]  # 保留账号明细
    assert "每日同步完成" in res["message"] and "成功 2、失败 2 个账号" in res["message"]
    assert "失败账号：" in res["message"] and "HTTP 402" in res["message"]
    assert res["rerun"] == "started:1"


def test_daily_sync_all_all_accounts_failed_raises(db, monkeypatch):
    """全部账号失败（如 TikHub 402）：不再报「每日同步完成」，任务按失败上报且不触发重新对标。"""
    _seed(db)

    def fake_run_sync(_db, **kw):
        return {
            "job_id": 1,
            "message": "fail",
            "accounts": [{"account_id": 1, "platform": "douyin", "error": "TikHub 请求失败: HTTP 402"}],
            "posts": 0,
            "comments": 0,
        }

    monkeypatch.setattr("app.services.platform_sync.run_sync", fake_run_sync)
    started: list[bool] = []
    monkeypatch.setattr(
        "app.services.benchmark.maybe_start_benchmark_rerun",
        lambda _db, refetch=True: started.append(refetch) or "started:1",
    )

    with pytest.raises(RuntimeError) as exc_info:
        run_daily_sync_all(db)

    assert "每日同步失败" in str(exc_info.value) and "全部同步失败" in str(exc_info.value)
    assert started == []  # 没有任何同步成功 → 不触发「重新对标」


def test_start_sync_raises_when_all_accounts_failed(db, monkeypatch):
    """手动单账号/单博主同步：全部账号失败时任务抛错（通知显示「同步失败」而非「同步完成」）。"""
    from app.api import platform as platform_api

    captured: dict = {}
    monkeypatch.setattr("app.api.platform.start_task", lambda kind, payload, fn: captured.update({"fn": fn, "kind": kind}) or 1)
    platform_api._start_sync({"scope": "daily", "creator_id": 1})

    def fake_run_sync(_db, **_kw):
        return {
            "accounts": [{"account_id": 1, "platform": "douyin", "error": "TikHub 请求失败: HTTP 402"}],
            "message": "同步 1 个账号，更新作品 0；失败账号：douyin(TikHub 请求失败: HTTP 402)",
        }

    monkeypatch.setattr("app.api.platform.run_sync", fake_run_sync)
    assert captured["kind"] == "platform_sync"
    with pytest.raises(RuntimeError, match="失败账号"):
        captured["fn"](db, {"scope": "daily", "creator_id": 1})
