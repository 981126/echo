"""R-222 回归：并发补全作品指标时不得覆盖 sync_account 的累计 stats。

旧实现用 `for pd, stats, error in ...` 复用了外层 `stats` 变量名；当末条补全结果
为 None 时，外层累计字典被覆盖为 None，随后 `stats["posts"] += 1` 抛
`'NoneType' object does not support item assignment`，导致整个账号回滚、0 条作品入库
（B站列表常缺 like 字段，故 B站同步首当其冲）。
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest
from conftest import ensure_schema, fresh_engine
from sqlalchemy.orm import sessionmaker

from app.models.platform import Creator, CreatorAccount, PlatformPost
from app.services.platform.base import PostData, ProfileData
from app.services.platform_sync import sync_account


@pytest.fixture()
def db(tmp_path):
    eng = fresh_engine()
    ensure_schema(eng)
    session = sessionmaker(bind=eng, autoflush=False, autocommit=False)()
    yield session
    session.close()


class _FakeClient:
    def fetch_profile(self, platform, user_id, account=None):
        return ProfileData(nickname="B", raw={})

    def fetch_user_posts(self, platform, user_id, count=20, cursor="", account=None):
        return [
            PostData(platform_post_id="aid:1", title="t1", raw={}),
            PostData(platform_post_id="aid:2", title="t2", raw={}),
        ]

    def fetch_post_stats(self, platform, post_id, account=None):
        return {"plays": 1, "likes": 1, "favorites": 0, "shares": 0, "comments": 0, "extra": {}}


def _stats():
    return {"plays": 1, "likes": 1, "favorites": 0, "shares": 0, "comments": 0, "extra": {}}


def test_bilibili_sync_keeps_stats_accumulator_when_backfill_returns_none(db, monkeypatch):
    owner = Creator(kind="owner", name="我", is_current=True)
    db.add(owner)
    db.flush()
    acc = CreatorAccount(
        creator_id=owner.id,
        platform="bilibili",
        nickname="B站",
        platform_user_id="uid",
        enabled=True,
    )
    db.add(acc)
    db.commit()

    monkeypatch.setattr("app.services.platform_sync.make_source", lambda platform=None, mode="": _FakeClient())
    # 末条补全返回 None（真实场景：单条详情失败），旧实现会把外层 stats 覆盖成 None
    monkeypatch.setattr(
        "app.services.platform_sync._fetch_post_stats_parallel",
        lambda account, client, posts, platform=None: [
            (posts[0], _stats(), None),
            (posts[1], None, RuntimeError("detail failed")),
        ],
    )
    monkeypatch.setattr("app.services.platform_sync._backfill_bili_stats", lambda *a, **k: 0)

    res = sync_account(db, acc, scope="daily", top_n=15, with_comments=False)

    assert res["posts"] == 2
    assert res["comments"] == 0
    assert db.query(PlatformPost).filter(PlatformPost.account_id == acc.id).count() == 2
