"""R-226：卡片标题去 #话题 + 三平台标签合并去重。"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import Base
from app.models.platform import Creator, CreatorAccount, PlatformPost
from app.models.video import Video
from app.models.work import Work
from app.services import library_service
from app.services.text_tags import extract_hashtags, strip_hashtags
from app.services.title_cleanup import clean_hashtag_titles


@pytest.fixture()
def db(tmp_path):
    eng = create_engine(f"sqlite:///{tmp_path}/t.db", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=eng)
    session = sessionmaker(bind=eng, autoflush=False, autocommit=False)()
    yield session
    session.close()
    eng.dispose()


def _owner_with_accounts(db):
    owner = Creator(kind="owner", name="我", is_current=True)
    db.add(owner)
    db.flush()
    accounts = {
        "douyin": CreatorAccount(creator_id=owner.id, platform="douyin", nickname="我-抖音", platform_user_id="dy", enabled=True),
        "xiaohongshu": CreatorAccount(creator_id=owner.id, platform="xiaohongshu", nickname="我-小红书", platform_user_id="xhs", enabled=True),
        "bilibili": CreatorAccount(creator_id=owner.id, platform="bilibili", nickname="我-B站", platform_user_id="bili", enabled=True),
    }
    db.add_all(list(accounts.values()))
    db.commit()
    return owner, accounts


def test_strip_and_extract_hashtags():
    assert strip_hashtags("同样的工资 #找工作 #求职") == "同样的工资"
    assert strip_hashtags("标题＃全角 ＃tag") == "标题"
    assert strip_hashtags("#只有话题") == ""  # 去完为空 → 由调用方回落
    assert strip_hashtags("没有话题") == "没有话题"
    assert extract_hashtags("标题 #找工作 #求职 #找工作") == ["找工作", "求职"]
    assert extract_hashtags("#视频 #B站") == []  # 纯平台词被过滤


def test_cloud_card_strips_title_and_merges_platform_tags(db):
    owner, acc = _owner_with_accounts(db)
    work = Work(creator_id=owner.id, title="同样的工资 #找工作 #求职")
    db.add(work)
    db.flush()
    db.add_all(
        [
            # 抖音：tags 为空（top15 同步口径），话题只在标题里
            PlatformPost(account_id=acc["douyin"].id, platform="douyin", platform_post_id="d1", title="同样的工资 #找工作 #求职", desc="同样的工资 #找工作 #求职", tags="[]", work_id=work.id),
            PlatformPost(account_id=acc["xiaohongshu"].id, platform="xiaohongshu", platform_post_id="x1", title="同样的工资", tags=json.dumps(["求职", "面试", "Job"], ensure_ascii=False), work_id=work.id),
            PlatformPost(account_id=acc["bilibili"].id, platform="bilibili", platform_post_id="b1", title="同样的工资", tags=json.dumps(["job", "B站专属"], ensure_ascii=False), work_id=work.id),
        ]
    )
    db.commit()

    cards = library_service.build_cards(db, owner.id)
    card = next(c for c in cards if c["kind"] == "cloud" and c["type"] == "work")
    assert card["title"] == "同样的工资"
    # 抖音→小红书→B站，忽略大小写去重，保留首次出现的写法
    assert card["tags"] == ["找工作", "求职", "面试", "Job", "B站专属"]


def test_clean_hashtag_titles_backfill(db):
    owner, acc = _owner_with_accounts(db)
    post = PlatformPost(account_id=acc["douyin"].id, platform="douyin", platform_post_id="c1", title="标题 #tag1 #tag2")
    only = PlatformPost(account_id=acc["douyin"].id, platform="douyin", platform_post_id="c2", title="#只有话题")
    work = Work(creator_id=owner.id, title="作品 #aaa")
    video = Video(filename="f.mp4", title="素材 #bbb", creator_id=owner.id)
    db.add_all([post, only, work, video])
    db.commit()

    res = clean_hashtag_titles(db)

    assert post.title == "标题"
    assert only.title == "#只有话题"  # 去完为空 → 保留原值
    assert work.title == "作品"
    assert video.title == "素材"
    assert res == {"platform_posts": 1, "works": 1, "videos": 1}
