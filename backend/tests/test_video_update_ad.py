"""修复：素材抽屉保存后，取消商务广告 / 清空广告价格 / 清空实际发布 不被平台帖旧值覆盖。"""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.api.videos import update_video
from app.db import Base
from app.models.platform import Creator, CreatorAccount, PlatformPost
from app.models.video import Video
from app.schemas.video import VideoUpdate


@pytest.fixture()
def db(tmp_path):
    eng = create_engine(f"sqlite:///{tmp_path}/t.db", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=eng)
    session = sessionmaker(bind=eng, autoflush=False, autocommit=False)()
    yield session
    session.close()
    eng.dispose()


def _seed_bound_ad(db):
    owner = Creator(kind="owner", name="我", is_current=True)
    db.add(owner)
    db.flush()
    acc = CreatorAccount(
        creator_id=owner.id, platform="douyin", nickname="我-抖音", platform_user_id="u", enabled=True
    )
    db.add(acc)
    db.flush()
    video = Video(
        filename="v.mp4",
        title="素材",
        creator_id=owner.id,
        is_ad=True,
        ad_price=500,
        published_at=datetime(2026, 1, 2, 3, 4, 5),
    )
    db.add(video)
    db.flush()
    post = PlatformPost(
        account_id=acc.id,
        platform="douyin",
        platform_post_id="p1",
        title="素材",
        is_ad=True,
        ad_price=500,
        publish_time=datetime(2026, 1, 2, 3, 4, 5),
        local_video_id=video.id,
    )
    db.add(post)
    db.commit()
    return video, post


def test_uncheck_ad_and_clear_price_stick(db):
    video, post = _seed_bound_ad(db)

    update_video(video.id, VideoUpdate(is_ad=False, ad_price=None), db)

    db.refresh(video)
    db.refresh(post)
    assert video.is_ad is False
    assert video.ad_price is None
    # 本地 → 平台帖 单向推送生效
    assert post.is_ad is False
    assert post.ad_price is None


def test_clear_published_at_not_refilled(db):
    video, post = _seed_bound_ad(db)

    update_video(video.id, VideoUpdate(published_at=None), db)

    db.refresh(video)
    assert video.published_at is None
    # 平台帖的 publish_time（平台真实时间）不受影响
    db.refresh(post)
    assert post.publish_time is not None
