"""R-107：素材库列表不返回禁用账号的数据（含绑定其作品的本地素材）。"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.api import videos as videos_api
from app.db import Base
from app.models.platform import Creator, CreatorAccount, PlatformPost
from app.models.video import Video


@pytest.fixture()
def db(tmp_path):
    eng = create_engine(f"sqlite:///{tmp_path}/t.db", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=eng)
    session = sessionmaker(bind=eng, autoflush=False, autocommit=False)()
    yield session
    session.close()
    eng.dispose()


def _seed(db):
    creator = Creator(kind="owner", name="我", is_current=True)
    db.add(creator)
    db.commit()
    on = CreatorAccount(creator_id=creator.id, platform="douyin", nickname="启用号", enabled=True)
    off = CreatorAccount(creator_id=creator.id, platform="douyin", nickname="禁用号", enabled=False)
    db.add_all([on, off])
    db.commit()

    v_on = Video(filename="v_on.mp4", creator_id=creator.id, platform_post_id="douyin:on1", status="published")
    v_off = Video(filename="v_off.mp4", creator_id=creator.id, platform_post_id="douyin:off1", status="published")
    v_off_local = Video(filename="v_off_local.mp4", creator_id=creator.id, status="published")
    v_free = Video(filename="v_free.mp4", creator_id=creator.id, status="published")
    db.add_all([v_on, v_off, v_off_local, v_free])
    db.flush()

    db.add_all(
        [
            PlatformPost(account_id=on.id, platform="douyin", platform_post_id="on1", title="启用号作品", local_video_id=v_on.id),
            PlatformPost(account_id=off.id, platform="douyin", platform_post_id="off1", title="禁用号作品", local_video_id=v_off.id),
            PlatformPost(account_id=off.id, platform="douyin", platform_post_id="off2", title="禁用号作品2", local_video_id=v_off_local.id),
        ]
    )
    db.commit()
    return creator


def test_list_videos_excludes_disabled_account_materials(db):
    creator = _seed(db)
    data = videos_api.list_videos(creator_id=creator.id, limit=200, db=db)
    ids = [v.id for v in data["items"]]
    assert data["total"] == 2
    assert data["total"] == len(ids)
    names = {v.filename for v in data["items"]}
    assert "v_free.mp4" in names
    assert "v_on.mp4" in names          # 启用账号绑定的素材保留
    assert "v_off.mp4" not in names       # 禁用账号（platform_post_id 绑定）排除
    assert "v_off_local.mp4" not in names  # 禁用账号（post.local_video_id 绑定）排除
