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
