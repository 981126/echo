"""R-269 同步节流与增量：指标复用、评论 TTL 分档、B站补全冷却、小红书播放量映射。"""

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
from app.models.platform import Creator, CreatorAccount, PlatformPost, PlatformPostComment, PlatformPostStat
from app.services.platform.base import PostData
from app.services.platform_sync import (
    _bili_miss_in_cooldown,
    _comment_ttl_hours,
    _comments_synced_recently,
    _ensure_post,
    _in_incremental_window,
)


@pytest.fixture()
def db():
    eng = fresh_engine()
    ensure_schema(eng)
    session = sessionmaker(bind=eng, autoflush=False, autocommit=False)()
    yield session
    session.close()


def _seed_account(db) -> CreatorAccount:
    owner = Creator(kind="owner", name="我", is_current=True)
    db.add(owner)
    db.commit()
    account = CreatorAccount(
        creator_id=owner.id, platform="bilibili", nickname="我", platform_user_id="uid", enabled=True
    )
    db.add(account)
    db.commit()
    return account


def _seed_post(db, account: CreatorAccount, publish_time=None, post_id: str = "aid:1") -> PlatformPost:
    post = PlatformPost(
        account_id=account.id,
        platform=account.platform,
        platform_post_id=post_id,
        title="旧标题",
        publish_time=publish_time,
    )
    db.add(post)
    db.commit()
    return post


def test_comment_ttl_hours():
    now = _now()
    assert _comment_ttl_hours(now - timedelta(hours=2)) == 6.0
    assert _comment_ttl_hours(now - timedelta(days=3)) == 24.0
    assert _comment_ttl_hours(now - timedelta(days=30)) == float("inf")
    assert _comment_ttl_hours(None) == 24.0


def test_incremental_window():
    now = _now()
    assert _in_incremental_window(now - timedelta(hours=1)) is True
    assert _in_incremental_window(now - timedelta(days=3)) is False
    assert _in_incremental_window(None) is True


def test_bili_miss_cooldown():
    today = _now().date()
    assert _bili_miss_in_cooldown('{"backfill_miss_at": "%s"}' % today.isoformat()) is True
    old = (today - timedelta(days=8)).isoformat()
    assert _bili_miss_in_cooldown('{"backfill_miss_at": "%s"}' % old) is False
    assert _bili_miss_in_cooldown("") is False
    assert _bili_miss_in_cooldown("not-json") is False
    assert _bili_miss_in_cooldown('{"other": 1}') is False


def test_comments_ttl_by_post_age(db):
    account = _seed_account(db)
    now = _now()
    recent = _seed_post(db, account, publish_time=now - timedelta(hours=2), post_id="aid:1")
    mid = _seed_post(db, account, publish_time=now - timedelta(days=3), post_id="aid:2")
    old = _seed_post(db, account, publish_time=now - timedelta(days=30), post_id="aid:3")
    for post in (recent, mid, old):
        db.add(
            PlatformPostComment(
                post_id=post.id,
                platform="bilibili",
                text="c",
                created_at=now - timedelta(hours=7),
            )
        )
    db.commit()
    # 新帖 6h 档：7 小时前拉过 → 需要再拉
    assert _comments_synced_recently(db, recent.id, hours=_comment_ttl_hours(recent.publish_time)) is False
    # 7 天内 24h 档：7 小时前拉过 → 跳过
    assert _comments_synced_recently(db, mid.id, hours=_comment_ttl_hours(mid.publish_time)) is True
    # 超过 7 天：不主动拉
    assert _comments_synced_recently(db, old.id, hours=_comment_ttl_hours(old.publish_time)) is True


def test_comments_old_post_never_fetched(db):
    account = _seed_account(db)
    old = _seed_post(db, account, publish_time=_now() - timedelta(days=30))
    assert _comments_synced_recently(db, old.id, hours=_comment_ttl_hours(old.publish_time)) is False


class _ExplodingClient:
    requests_used = 0

    def fetch_post_stats(self, *args, **kwargs):  # noqa: ANN002, ANN003
        raise AssertionError("当天已有统计时不应请求单帖指标")


class _CountingClient:
    requests_used = 0

    def __init__(self):
        self.calls = 0

    def fetch_post_stats(self, platform: str, post_id: str, account=None):  # noqa: ANN001
        self.calls += 1
        return {"plays": 7, "likes": 1, "favorites": 1, "shares": 0, "comments": 0, "extra": {}}


def test_ensure_post_reuses_today_stat(db):
    account = _seed_account(db)
    post = _seed_post(db, account)
    stat = PlatformPostStat(post_id=post.id, stat_date=today_key(), plays=10, likes=5, source="tikhub")
    db.add(stat)
    db.commit()
    pd = PostData(platform_post_id="aid:1", title="新标题")
    row = _ensure_post(
        db,
        account,
        pd,
        _ExplodingClient(),
        commit=True,
        existing={("bilibili", "aid:1"): post},
        today_stat=stat,
    )
    assert row.id == post.id
    assert row.title == "新标题"
    assert db.query(PlatformPostStat).count() == 1
    assert db.query(PlatformPostStat).first().plays == 10


def test_ensure_post_fetches_without_today_stat(db):
    account = _seed_account(db)
    post = _seed_post(db, account)
    client = _CountingClient()
    pd = PostData(platform_post_id="aid:1", title="新标题")
    _ensure_post(db, account, pd, client, commit=True, existing={("bilibili", "aid:1"): post})
    assert client.calls == 1
    stat = db.query(PlatformPostStat).filter_by(post_id=post.id).first()
    assert stat is not None
    assert stat.plays == 7


def test_xhs_play_mapping(monkeypatch):
    from app.services.platform.tikhub import TikHubClient

    client = TikHubClient(mode="real", api_key="k", base_url="http://example.invalid")
    monkeypatch.setattr(
        client,
        "_get",
        lambda *_a, **_k: {"data": {"data": {"note": {"view_count": 1234, "likes": 9, "collected_count": 3}}}},
    )
    stats = client._real_post_stats("xiaohongshu", "note1")
    assert stats["plays"] == 1234
    assert stats["likes"] == 9
