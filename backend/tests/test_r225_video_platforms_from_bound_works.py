"""R-225：素材库抽屉平台勾选由绑定作品决定。"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.api.platform import post_to_material
from app.api.videos import get_video
from app.db import Base
from app.models.platform import Creator, CreatorAccount, PlatformPost
from app.models.video import Video
from app.models.work import Work
from app.services.works_service import auto_merge_creator, merge_manual, split_work


@pytest.fixture()
def db(tmp_path):
    eng = create_engine(f"sqlite:///{tmp_path}/t.db", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=eng)
    session = sessionmaker(bind=eng, autoflush=False, autocommit=False)()
    yield session
    session.close()
    eng.dispose()


def _make_owner_with_accounts(db):
    owner = Creator(kind="owner", name="我", is_current=True)
    db.add(owner)
    db.flush()
    douyin = CreatorAccount(
        creator_id=owner.id,
        platform="douyin",
        nickname="我-抖音",
        platform_user_id="dy_uid",
        enabled=True,
    )
    xhs = CreatorAccount(
        creator_id=owner.id,
        platform="xiaohongshu",
        nickname="我-小红书",
        platform_user_id="xhs_uid",
        enabled=True,
    )
    bili = CreatorAccount(
        creator_id=owner.id,
        platform="bilibili",
        nickname="我-B站",
        platform_user_id="bili_uid",
        enabled=True,
    )
    db.add_all([douyin, xhs, bili])
    db.commit()
    return owner, douyin, xhs, bili


def test_get_video_derives_platforms_from_bound_posts(db):
    """Video.platforms 列陈旧时，GET /api/videos/{id} 仍从绑定帖子推导。"""
    owner, dy_acc, xhs_acc, bili_acc = _make_owner_with_accounts(db)
    work = Work(creator_id=owner.id, title="同一个标题")
    db.add(work)
    db.flush()
    posts = [
        PlatformPost(account_id=dy_acc.id, platform="douyin", platform_post_id="d1", title="同一个标题", work_id=work.id, local_video_id=None),
        PlatformPost(account_id=xhs_acc.id, platform="xiaohongshu", platform_post_id="x1", title="同一个标题", work_id=work.id, local_video_id=None),
        PlatformPost(account_id=bili_acc.id, platform="bilibili", platform_post_id="b1", title="同一个标题", work_id=work.id, local_video_id=None),
    ]
    db.add_all(posts)
    db.commit()

    video = Video(filename="real.mp4", title="同一个标题", creator_id=owner.id, work_id=work.id, platforms="[]")
    db.add(video)
    db.commit()
    posts[0].local_video_id = video.id
    db.commit()

    out = get_video(video.id, db)
    assert sorted(out.platforms) == ["bilibili", "douyin", "xiaohongshu"]


def test_auto_merge_recomputes_video_platforms(db):
    """自动合并后，绑定的本地素材 platforms 列刷新为全部成员平台。"""
    owner, dy_acc, xhs_acc, bili_acc = _make_owner_with_accounts(db)
    posts = [
        PlatformPost(account_id=dy_acc.id, platform="douyin", platform_post_id="d1", title="同一个标题"),
        PlatformPost(account_id=xhs_acc.id, platform="xiaohongshu", platform_post_id="x1", title="同一个标题"),
        PlatformPost(account_id=bili_acc.id, platform="bilibili", platform_post_id="b1", title="同一个标题"),
    ]
    db.add_all(posts)
    db.commit()

    video = Video(filename="real.mp4", title="同一个标题", creator_id=owner.id, platforms=json.dumps(["douyin"], ensure_ascii=False))
    db.add(video)
    db.commit()
    posts[0].local_video_id = video.id
    db.commit()

    auto_merge_creator(db, owner.id)
    db.refresh(video)
    assert sorted(json.loads(video.platforms or "[]")) == ["bilibili", "douyin", "xiaohongshu"]


def test_merge_manual_recomputes_video_platforms(db):
    """手动合并后，绑定的本地素材 platforms 列刷新。"""
    owner, dy_acc, xhs_acc, _ = _make_owner_with_accounts(db)
    posts = [
        PlatformPost(account_id=dy_acc.id, platform="douyin", platform_post_id="d1", title="标题 A"),
        PlatformPost(account_id=xhs_acc.id, platform="xiaohongshu", platform_post_id="x1", title="标题 B"),
    ]
    db.add_all(posts)
    db.commit()

    video = Video(filename="real.mp4", title="标题", creator_id=owner.id, platforms="[]")
    db.add(video)
    db.commit()
    posts[0].local_video_id = video.id
    db.commit()

    merge_manual(db, [p.id for p in posts])
    db.refresh(video)
    assert sorted(json.loads(video.platforms or "[]")) == ["douyin", "xiaohongshu"]


def test_split_work_recomputes_video_platforms(db):
    """拆分作品后，绑定的本地素材 platforms 列按仍绑定（local_video_id / work）的帖子刷新。

    注意：当前 split_work 不会清掉被拆出帖子的 local_video_id，因此它们仍绑定素材；
    若未来拆分同时解绑，这里会自然只剩保留成员的平台。
    """
    owner, dy_acc, xhs_acc, bili_acc = _make_owner_with_accounts(db)
    work = Work(creator_id=owner.id, title="同一个标题")
    db.add(work)
    db.flush()
    posts = [
        PlatformPost(account_id=dy_acc.id, platform="douyin", platform_post_id="d1", title="同一个标题", work_id=work.id),
        PlatformPost(account_id=xhs_acc.id, platform="xiaohongshu", platform_post_id="x1", title="同一个标题", work_id=work.id),
        PlatformPost(account_id=bili_acc.id, platform="bilibili", platform_post_id="b1", title="同一个标题", work_id=work.id),
    ]
    db.add_all(posts)
    db.commit()

    video = Video(filename="real.mp4", title="同一个标题", creator_id=owner.id, work_id=work.id, platforms="[]")
    db.add(video)
    db.commit()
    for p in posts:
        p.local_video_id = video.id
    db.commit()

    split_work(db, work.id, keep_ids=[posts[0].id])
    db.refresh(video)
    # 三个帖子的 local_video_id 都还在，所以仍算绑定
    assert sorted(json.loads(video.platforms or "[]")) == ["bilibili", "douyin", "xiaohongshu"]


def test_post_to_material_uses_work_member_platforms(db):
    """对合并 work 的帖子转本地素材时，platforms 包含全部成员平台。"""
    owner, dy_acc, xhs_acc, bili_acc = _make_owner_with_accounts(db)
    work = Work(creator_id=owner.id, title="同一个标题")
    db.add(work)
    db.flush()
    posts = [
        PlatformPost(account_id=dy_acc.id, platform="douyin", platform_post_id="d1", title="同一个标题", work_id=work.id),
        PlatformPost(account_id=xhs_acc.id, platform="xiaohongshu", platform_post_id="x1", title="同一个标题", work_id=work.id),
        PlatformPost(account_id=bili_acc.id, platform="bilibili", platform_post_id="b1", title="同一个标题", work_id=work.id),
    ]
    db.add_all(posts)
    db.commit()

    res = post_to_material(posts[0].id, db)
    video = db.get(Video, res["video_id"])
    assert video is not None
    assert sorted(json.loads(video.platforms or "[]")) == ["bilibili", "douyin", "xiaohongshu"]
