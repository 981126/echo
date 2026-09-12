"""R-140：灵感池入池修复（队列路径）与进池限量测试。

背景（已查证的回归）：R-093（2026-09-06）把「daily + 带媒体」改成逐素材队列后，
`queue_mode = with_media and scope == "daily"` → `with_comments = False`，
而全项目只有 `_collect_comments()` 会写 `topic_ideas` → 灵感池「评论」半边自 09-06 起再无数据。
本文件同时锁住：
1. 队列模式（`with_media=True`）也会按限量把评论写进灵感池；
2. 非队列路径（全量/每周）行为不回退；
3. 限量：单帖 ≤ per_post、单博主每天 ≤ per_day；
4. 「标题 ≥4 字」过滤与按天去重、点赞取大；
5. 每日篇数口径：组候选与生成切片都用 `app_kv` 设置。
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import Base
from app.models.hot_topic import TopicIdea
from app.models.kv import Kv
from app.models.platform import Creator, CreatorAccount, PlatformPost
from unittest.mock import MagicMock

from app.services import pipeline as pipeline_mod
from app.services import platform_sync
from app.services.platform_sync import run_sync


@pytest.fixture()
def db(tmp_path):
    eng = create_engine(f"sqlite:///{tmp_path}/t.db", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=eng)
    session = sessionmaker(bind=eng, autoflush=False, autocommit=False)()
    yield session
    session.close()
    eng.dispose()


def _comments(pairs: list[tuple[str, int]]) -> list[dict]:
    """数据源返回的评论形态（dict）——`_norm_comment_items` 接受 dict/str/CommentData。"""
    return [{"text": t, "likes": n} for t, n in pairs]


def _settings(**overrides: object) -> MagicMock:
    base: dict[str, object] = dict(pool_ideas_per_post=8, pool_ideas_per_day=40)
    base.update(overrides)
    return MagicMock(**base)


def _seed(db, *, platform: str = "douyin"):
    c = Creator(kind="owner", name="我", is_current=True)
    db.add(c)
    db.commit()
    a = CreatorAccount(
        creator_id=c.id,
        platform=platform,
        nickname="我的账号",
        home_link=f"https://www.{platform}.com/user/u1",
        platform_user_id="u1",
        enabled=True,
        sync_frequency="daily",
    )
    db.add(a)
    db.commit()
    return c, a


def _post(db, account, title: str = "一条作品") -> PlatformPost:
    p = PlatformPost(
        account_id=account.id,
        platform=account.platform,
        platform_post_id=f"p{title}",
        title=title,
        is_ad=False,
    )
    db.add(p)
    db.commit()
    return p


# ---------- 队列路径（本次回归的核心） ----------


def test_queue_sync_with_media_fills_idea_pool(db):
    """daily + 带媒体 = 队列模式，也必须把评论写进灵感池（R-093 回归的正面用例）。"""
    _seed(db)
    result = run_sync(db, scope="daily", with_media=True)
    assert result["accounts"][0]["posts"] > 0
    assert db.query(TopicIdea).count() > 0, "队列模式（daily+带媒体）必须填充灵感池"
    assert result["pool_ideas"] > 0
    assert "灵感池新增" in result["message"]


def test_non_queue_sync_still_fills_pool(db):
    """全量/每周（不带媒体）走 _collect_comments，行为不回退。"""
    _seed(db)
    result = run_sync(db, scope="weekly")
    assert db.query(TopicIdea).count() > 0
    assert result["pool_ideas"] > 0


def test_sync_post_comments_writes_pool(db):
    """单帖同步（队列里也是走它）入库后要顺带进池。"""
    _c, account = _seed(db)
    post = _post(db, account)

    class _Client:
        def fetch_comments(self, *_a, **_k):
            return _comments([("面试被问到空窗期怎么解释比较好", 12), ("短", 99)])

    res = platform_sync.sync_post_comments(db, post, limit=50, client=_Client(), account=account, charge=False)
    assert res["pool_added"] == 1  # 只有 ≥4 字的那条进池
    rows = db.query(TopicIdea).all()
    assert [r.title for r in rows] == ["面试被问到空窗期怎么解释比较好"]
    assert rows[0].creator_id == account.creator_id
    assert rows[0].platform == account.platform
    assert rows[0].likes == 12


def test_pool_can_be_disabled(db):
    _c, account = _seed(db)
    post = _post(db, account)

    class _Client:
        def fetch_comments(self, *_a, **_k):
            return _comments([("这条评论足够长可以进池", 3)])

    res = platform_sync.sync_post_comments(
        db, post, limit=50, client=_Client(), account=account, charge=False, pool=False
    )
    assert "pool_added" not in res
    assert db.query(TopicIdea).count() == 0


# ---------- 限量 ----------


def test_per_post_limit(db, monkeypatch):
    monkeypatch.setattr(platform_sync, "get_settings", lambda: _settings(pool_ideas_per_post=3))
    _c, account = _seed(db)
    post = _post(db, account)

    class _Client:
        def fetch_comments(self, *_a, **_k):
            return _comments([(f"评论内容第{i}条足够长", i) for i in range(10)])

    res = platform_sync.sync_post_comments(db, post, limit=50, client=_Client(), account=account, charge=False)
    assert res["pool_added"] == 3, "单帖最多进 3 条"
    # 按点赞降序取前 3（likes 9/8/7）
    assert sorted(r.likes for r in db.query(TopicIdea).all()) == [7, 8, 9]


def test_per_day_limit(db, monkeypatch):
    monkeypatch.setattr(platform_sync, "get_settings", lambda: _settings(pool_ideas_per_post=5, pool_ideas_per_day=4))
    _c, account = _seed(db)

    class _Client:
        def fetch_comments(self, *_a, **_k):
            return _comments([(f"评论内容第{i}条足够长", i) for i in range(10)])

    total = 0
    for i in range(3):
        post = _post(db, account, title=f"作品{i}")
        res = platform_sync.sync_post_comments(
            db, post, limit=50, client=_Client(), account=account, charge=False
        )
        total += res["pool_added"]
    assert total == 4, "单博主当天最多进 4 条"
    assert db.query(TopicIdea).count() == 4


def test_daily_limit_is_per_creator(db, monkeypatch):
    """限量按博主隔离：另一个博主有自己的配额。"""
    monkeypatch.setattr(platform_sync, "get_settings", lambda: _settings(pool_ideas_per_post=5, pool_ideas_per_day=1))
    c1, a1 = _seed(db)
    c2 = Creator(kind="owner", name="马甲", is_current=False)
    db.add(c2)
    db.commit()
    a2 = CreatorAccount(
        creator_id=c2.id, platform="douyin", nickname="马甲号", home_link="https://x", platform_user_id="u2", enabled=True
    )
    db.add(a2)
    db.commit()

    class _Client:
        def fetch_comments(self, *_a, **_k):
            return _comments([(f"评论内容第{i}条足够长", i) for i in range(5)])

    r1 = platform_sync.sync_post_comments(
        db, _post(db, a1, "a"), limit=50, client=_Client(), account=a1, charge=False
    )
    r2 = platform_sync.sync_post_comments(
        db, _post(db, a2, "b"), limit=50, client=_Client(), account=a2, charge=False
    )
    assert r1["pool_added"] == 1 and r2["pool_added"] == 1
    rows = db.query(TopicIdea).all()
    assert {r.creator_id for r in rows} == {c1.id, c2.id}


def test_dedupe_and_likes_upgrade(db):
    """同一天同标题只进一条；重复出现时点赞取大。"""
    _c, account = _seed(db)
    post = _post(db, account)

    class _Low:
        def fetch_comments(self, *_a, **_k):
            return _comments([("同一句评论内容足够长", 2)])

    class _High:
        def fetch_comments(self, *_a, **_k):
            return _comments([("同一句评论内容足够长", 88)])

    platform_sync.sync_post_comments(db, post, limit=50, client=_Low(), account=account, charge=False)
    res = platform_sync.sync_post_comments(db, post, limit=50, client=_High(), account=account, charge=False)
    rows = db.query(TopicIdea).all()
    assert len(rows) == 1 and rows[0].likes == 88
    assert res["pool_added"] == 0


def test_per_day_zero_means_unlimited(db, monkeypatch):
    monkeypatch.setattr(platform_sync, "get_settings", lambda: _settings(pool_ideas_per_post=0, pool_ideas_per_day=0))
    _c, account = _seed(db)

    class _Client:
        def fetch_comments(self, *_a, **_k):
            return _comments([(f"评论内容第{i}条足够长", i) for i in range(30)])

    res = platform_sync.sync_post_comments(
        db, _post(db, account), limit=50, client=_Client(), account=account, charge=False
    )
    assert res["pool_added"] == 30, "0 表示不限量"


# ---------- 每日篇数口径 ----------


def test_compose_candidates_uses_runtime_topics_count(db, monkeypatch):
    """组候选条数与生成切片都取「AI 设置」的每日篇数（R-140 口径对齐）。"""
    _seed(db)
    _set_kv(db, "pipeline_topics_count", "1")
    monkeypatch.setattr(pipeline_mod, "fetch_and_store", lambda *_a, **_k: [])
    monkeypatch.setattr(pipeline_mod, "_ai_candidate", lambda *_a, **_k: None)

    hot = [{"platform": "douyin", "title": f"热点{i}", "heat": "1", "url": ""} for i in range(5)]
    cands = pipeline_mod._compose_daily_candidates(db, hot, platform_sync.get_settings())
    assert len(cands) == 1, "候选条数应跟随 app_kv 的每日篇数（此前会用 .env 的 3）"


def _set_kv(db, key: str, value: str) -> None:
    row = db.get(Kv, key)
    if row is None:
        db.add(Kv(key=key, value=value))
    else:
        row.value = value
    db.commit()
