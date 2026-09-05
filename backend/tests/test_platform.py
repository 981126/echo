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
from app.services.creator_service import creator_public_meta, get_current_creator, switch_current
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
    assert parse_link("douyin", "https://www.douyin.com/user/MS4wLjABAAAA_abc?from_tab_name=main") == "MS4wLjABAAAA_abc"
    assert parse_link("xiaohongshu", "https://www.xiaohongshu.com/user/profile?userId=abc123&x=1") == "abc123"
    assert parse_link("xiaohongshu", "https://www.xiaohongshu.com/user/profile/5f2c6a1b000000001203abcd") == "5f2c6a1b000000001203abcd"
    assert parse_link("bilibili", "https://space.bilibili.com/1234567?spm_id_from=333") == "1234567"
    assert parse_link("bilibili", "https://space.bilibili.com/1234567/video") == "1234567"
    # 无法识别的格式/短链在离线时不返回乱码尾巴（避免存错 ID）
    assert parse_link("douyin", "https://example.com/whatever") == ""
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
    owner, _ = _seed_owner(db)
    result = run_sync(db, scope="daily")
    assert result["accounts"][0]["posts"] > 0
    assert db.query(PlatformPost).count() > 0
    assert db.query(CreatorAccountSnapshot).count() == 1
    assert db.query(TopicIdea).count() > 0  # 评论区选题进池（R-028）
    assert db.query(SyncJob).count() == 1
    job = db.query(SyncJob).first()
    assert job.status == "done"
    # 账号头像自动生成 + 全网粉丝数 = 各平台粉丝独立累计的汇总
    meta = creator_public_meta(db, owner)
    assert meta["accounts"][0]["followers"] > 0
    assert meta["followers_total"] == meta["accounts"][0]["followers"]
    assert meta["avatar"] is None  # 无真实头像时保持空（前端显示空圆框，不生成汉字占位）


def test_budget_guard(db):
    _seed_owner(db)
    set_budget(db, 3)
    result = run_sync(db, scope="daily")  # 单平台失败被隔离，整批不抛错
    assert result["accounts"]
    acc = result["accounts"][0]
    assert "error" in acc or "skipped" in acc
    budget = get_budget(db)
    assert budget["used"] <= budget["limit"]


def _post(db, account_id, platform, pid, title):
    from app.models.platform import PlatformPost

    p = PlatformPost(
        account_id=account_id,
        platform=platform,
        platform_post_id=pid,
        title=title,
        raw="{}",
    )
    db.add(p)
    return p


def test_auto_merge_same_title_cross_platform(db):
    from app.models.platform import CreatorAccount
    from app.models.work import Work
    from app.services.works_service import auto_merge_creator, list_works

    owner, _ = _seed_owner(db)
    a2 = CreatorAccount(creator_id=owner.id, platform="bilibili", nickname="B", platform_user_id="1", enabled=True)
    db.add(a2)
    db.commit()
    _post(db, 1, "douyin", "dy1", "聊聊 offer 怎么选")
    _post(db, a2.id, "bilibili", "bi1", "聊聊 offer 怎么选")
    _post(db, 1, "douyin", "dy2", "完全不相关的另一条")
    db.commit()
    created = auto_merge_creator(db, owner.id)
    assert created >= 1
    works = list_works(db, owner.id)
    merged = [w for w in works if w["type"] == "work"]
    assert len(merged) == 1
    assert sorted(m["platform"] for m in merged[0]["posts"]) == ["bilibili", "douyin"]
    assert db.query(Work).count() == 1


def test_manual_merge_and_split(db):
    from app.models.work import Work
    from app.services.works_service import list_works, merge_manual, split_work

    owner, _ = _seed_owner(db)
    from app.models.platform import CreatorAccount

    a2 = CreatorAccount(creator_id=owner.id, platform="xiaohongshu", nickname="X", platform_user_id="2", enabled=True)
    db.add(a2)
    db.commit()
    p1 = _post(db, 1, "douyin", "dy9", "标题 A")
    p2 = _post(db, a2.id, "xiaohongshu", "xh9", "标题 B（其实是同一条视频）")
    db.commit()
    r = merge_manual(db, [p1.id, p2.id], owner.id)
    assert r["work_id"]
    works = list_works(db, owner.id)
    assert len([w for w in works if w["type"] == "work"]) == 1
    split_work(db, r["work_id"])
    assert db.query(Work).count() == 0
    assert db.query(PlatformPost).filter(PlatformPost.work_id.is_(None)).count() == 2
