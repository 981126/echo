"""平台数据/博主管理测试（M13，R-027/R-029，mock 离线可跑）。"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import Base
from app.models.platform import Creator, CreatorAccount, CreatorAccountSnapshot, PlatformPost, SyncJob
from app.models.hot_topic import TopicIdea
from app.services.creator_service import get_current_creator, switch_current
from app.services.platform.tikhub import make_client, parse_link, parse_post_id
from app.services.platform_sync import get_budget, run_sync, set_budget


@pytest.fixture()
def db(tmp_path):
    eng = create_engine(f"sqlite:///{tmp_path}/t.db", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=eng)
    session = sessionmaker(bind=eng, autoflush=False, autocommit=False)()
    yield session
    session.close()
    eng.dispose()


def _seed_owner(db):
    c = Creator(kind="owner", name="我", is_current=True)
    db.add(c)
    db.commit()
    a = CreatorAccount(
        creator_id=c.id,
        platform="douyin",
        nickname="我的抖音",
        home_link="https://www.douyin.com/user/MS4wLjABAAAA_test",
        platform_user_id="MS4wLjABAAAA_test",
        enabled=True,
        sync_frequency="daily",
    )
    db.add(a)
    db.commit()
    return c, a


def test_parse_link():
    assert parse_link("douyin", "https://www.douyin.com/user/MS4wLjABAAAA_abc") == "MS4wLjABAAAA_abc"
    assert parse_link("xiaohongshu", "https://www.xiaohongshu.com/user/profile?userId=abc123&x=1") == "abc123"
    assert parse_link("bilibili", "https://space.bilibili.com/1234567?spm_id_from=333") == "1234567"
    assert parse_link("douyin", "") == ""


def test_parse_post_id():
    assert parse_post_id("https://www.douyin.com/video/7299881234567?x=1") == ("douyin", "7299881234567")
    assert parse_post_id("https://www.bilibili.com/video/BV1xx411c7mD") == ("bilibili", "bvid:BV1xx411c7mD")
    assert parse_post_id("https://www.xiaohongshu.com/explore/64f0a1b2000000001203abcd")[0] == "xiaohongshu"
    assert parse_post_id("https://example.com/foo") == ("", "")


def test_mock_client_deterministic():
    c1 = make_client("mock")
    c2 = make_client("mock")
    a = c1.fetch_profile("douyin", "u1")
    b = c2.fetch_profile("douyin", "u1")
    assert a.followers == b.followers
    posts = c1.fetch_user_posts("douyin", "u1", count=5)
    assert len(posts) == 5
    assert all(p.platform_post_id for p in posts)
    assert all(p.stats.get("plays", 0) > 0 for p in posts)
    assert not any(p.video_url for p in posts)  # 视频不下载


def test_creator_switch(db):
    _seed_owner(db)
    b = Creator(kind="owner", name="马甲号")
    db.add(b)
    db.commit()
    switch_current(db, b.id)
    cur = get_current_creator(db)
    assert cur.id == b.id


def test_daily_sync_creates_posts_and_ideas(db):
    _seed_owner(db)
    result = run_sync(db, scope="daily")
    assert result["accounts"][0]["posts"] > 0
    assert db.query(PlatformPost).count() > 0
    assert db.query(CreatorAccountSnapshot).count() == 1
    assert db.query(TopicIdea).count() > 0  # 评论区选题进池（R-028）
    assert db.query(SyncJob).count() == 1
    job = db.query(SyncJob).first()
    assert job.status == "done"


def test_budget_guard(db):
    _seed_owner(db)
    set_budget(db, 3)
    with pytest.raises(Exception):
        run_sync(db, scope="daily")
    budget = get_budget(db)
    assert budget["used"] <= budget["limit"]
