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
