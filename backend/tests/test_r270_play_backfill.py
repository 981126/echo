"""R-270 抖音播放量批量补齐与历史回补：写入口径、配额、窗口、冷却与暂停。"""

from __future__ import annotations

import sys
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest
from conftest import ensure_schema, fresh_engine
from sqlalchemy.orm import sessionmaker

from app.core.pipeline import today_key
from app.core.timeutil import now as _now
from app.models.kv import Kv
from app.models.platform import Creator, CreatorAccount, PlatformPost, PlatformPostStat
from app.services.douyin_creator_sync import METRIC_BACKFILL_PAUSED_KV, backfill_peer_plays


class _FakeClient:
    mode = "real"

    def __init__(self, stats: dict[str, dict]):
        self.stats = stats
        self.calls: list[list[str]] = []

    def fetch_douyin_video_statistics(self, ids):  # noqa: ANN001
        if isinstance(ids, str):
            id_list = [item for item in ids.split(",") if item]
        else:
            id_list = list(ids)
        self.calls.append(id_list)
        return {
            "data": {
                "statistics_list": [
                    {"aweme_id": item, **self.stats.get(item, {})} for item in id_list
                ]
            }
        }


@pytest.fixture()
def db():
    eng = fresh_engine()
    ensure_schema(eng)
    session = sessionmaker(bind=eng, autoflush=False, autocommit=False)()
    yield session
    session.close()


def _seed(db, *, posts: list[dict]):
    owner = Creator(kind="owner", name="我", is_current=True)
    db.add(owner)
    db.commit()
    bench = Creator(kind="benchmark", parent_id=owner.id, name="对标A")
    db.add(bench)
    db.commit()
    account = CreatorAccount(
        creator_id=bench.id, platform="douyin", nickname="对标A", platform_user_id="uid", enabled=True
    )
    db.add(account)
    db.commit()
    created = []
    for item in posts:
        post = PlatformPost(
            account_id=account.id,
            platform="douyin",
            platform_post_id=item["id"],
            title=item["id"],
            publish_time=_now() - timedelta(days=item.get("age_days", 1)),
        )
        db.add(post)
        db.commit()
        stat = PlatformPostStat(
            post_id=post.id,
            stat_date=item.get("stat_date", today_key()),
            plays=item.get("plays", 0),
            likes=item.get("likes", 5),
            source=item.get("source", "tikhub"),
        )
        db.add(stat)
        db.commit()
        created.append((post, stat))
    return owner, created


def test_updates_latest_row_only(db, monkeypatch):
    owner, rows = _seed(db, posts=[{"id": "p1", "age_days": 10}])
    post, stat = rows[0]
    fake = _FakeClient({"p1": {"play_count": 100, "digg_count": 99, "comment_count": 3, "share_count": 2}})
    monkeypatch.setattr("app.services.douyin_creator_sync.make_client", lambda: fake)
    before = db.query(PlatformPostStat).count()
    result = backfill_peer_plays(db, owner, days=365, max_requests=10, per_account_limit=100, force=True)
    assert result["updated"] == 1
    assert db.query(PlatformPostStat).count() == before  # 不新增日期行
    db.refresh(stat)
    assert stat.plays == 100
    assert stat.likes == 5  # 已有真实值不覆盖
    assert stat.comments == 3


def test_skip_posts_with_plays(db, monkeypatch):
    owner, _rows = _seed(db, posts=[{"id": "p1", "plays": 500}, {"id": "p2"}])
    fake = _FakeClient({"p1": {"play_count": 500}, "p2": {"play_count": 20}})
    monkeypatch.setattr("app.services.douyin_creator_sync.make_client", lambda: fake)
    result = backfill_peer_plays(db, owner, days=365, max_requests=10, per_account_limit=100, force=True)
    assert result["updated"] == 1
    assert fake.calls == [["p2"]]


def test_batches_two_ids(db, monkeypatch):
    owner, _rows = _seed(db, posts=[{"id": "p1"}, {"id": "p2"}, {"id": "p3"}])
    fake = _FakeClient({"p1": {"play_count": 1}, "p2": {"play_count": 2}, "p3": {"play_count": 3}})
    monkeypatch.setattr("app.services.douyin_creator_sync.make_client", lambda: fake)
    result = backfill_peer_plays(db, owner, days=365, max_requests=10, per_account_limit=100, force=True)
    assert result["updated"] == 3
    assert [len(batch) for batch in fake.calls] == [2, 1]


def test_per_account_limit(db, monkeypatch):
    owner, _rows = _seed(db, posts=[{"id": f"p{i}"} for i in range(5)])
    fake = _FakeClient({f"p{i}": {"play_count": 1} for i in range(5)})
    monkeypatch.setattr("app.services.douyin_creator_sync.make_client", lambda: fake)
    result = backfill_peer_plays(db, owner, days=365, max_requests=10, per_account_limit=2, force=True)
    assert result["updated"] == 2
    assert result["remaining"] == 3


def test_days_zero_covers_history(db, monkeypatch):
    owner, _rows = _seed(db, posts=[{"id": "old", "age_days": 400}])
    fake = _FakeClient({"old": {"play_count": 9}})
    monkeypatch.setattr("app.services.douyin_creator_sync.make_client", lambda: fake)
    result = backfill_peer_plays(db, owner, days=0, max_requests=10, per_account_limit=100, force=True)
    assert result["updated"] == 1


def test_days_window_excludes_old(db, monkeypatch):
    owner, _rows = _seed(db, posts=[{"id": "old", "age_days": 400}])
    fake = _FakeClient({"old": {"play_count": 9}})
    monkeypatch.setattr("app.services.douyin_creator_sync.make_client", lambda: fake)
    result = backfill_peer_plays(db, owner, days=30, max_requests=10, per_account_limit=100, force=True)
    assert result["updated"] == 0


def test_paused_flag(db, monkeypatch):
    owner, _rows = _seed(db, posts=[{"id": "p1"}])
    db.add(Kv(key=METRIC_BACKFILL_PAUSED_KV, value="1"))
    db.commit()
    fake = _FakeClient({"p1": {"play_count": 1}})
    monkeypatch.setattr("app.services.douyin_creator_sync.make_client", lambda: fake)
    result = backfill_peer_plays(db, owner, days=365, max_requests=10, force=True)
    assert result.get("paused") is True
    assert fake.calls == []


def test_reuse_within_cooldown(db, monkeypatch):
    owner, _rows = _seed(db, posts=[{"id": "p1"}])
    fake = _FakeClient({"p1": {"play_count": 1}})
    monkeypatch.setattr("app.services.douyin_creator_sync.make_client", lambda: fake)
    first = backfill_peer_plays(db, owner, days=365, max_requests=10, force=True)
    assert first["updated"] == 1
    second = backfill_peer_plays(db, owner, days=365, max_requests=10)
    assert second.get("reused") is True
    assert len(fake.calls) == 1
