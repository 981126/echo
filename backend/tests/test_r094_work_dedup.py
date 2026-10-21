"""R-094 回归：合并作品的多个平台同步只下载一个视频，各平台数据照常同步。"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest
from conftest import ensure_schema, fresh_engine
from sqlalchemy.orm import sessionmaker

from app.models.platform import Creator, CreatorAccount, PlatformPost
from app.models.task import BackgroundTask
from app.models.video import Transcript, Video
from app.services import media_ensure
from app.services import platform_sync as platform_sync_mod
from app.services import sync_pool as sync_pool_mod
from app.services.works_service import auto_merge_creator


@pytest.fixture()
def db(tmp_path):
    eng = fresh_engine()
    ensure_schema(eng)
    session = sessionmaker(bind=eng, autoflush=False, autocommit=False)()
    yield session
    session.close()


def _make_owner_with_accounts(db):
    owner = Creator(kind="owner", name="我", is_current=True)
    db.add(owner)
    db.flush()
    douyin = CreatorAccount(
        creator_id=owner.id,
        platform="douyin",
        nickname="我-抖音",
        platform_user_id="douyin_uid",
        enabled=True,
    )
    xhs = CreatorAccount(
        creator_id=owner.id,
        platform="xiaohongshu",
        nickname="我-小红书",
        platform_user_id="xhs_uid",
        enabled=True,
    )
    db.add_all([douyin, xhs])
    db.commit()
    return owner, douyin, xhs


def _make_merged_posts(db, owner, douyin_acc, xhs_acc):
    post_a = PlatformPost(
        account_id=douyin_acc.id,
        platform="douyin",
        platform_post_id="dy001",
        title="同一个标题",
        raw="",
    )
    post_b = PlatformPost(
        account_id=xhs_acc.id,
        platform="xiaohongshu",
        platform_post_id="xhs001",
        title="同一个标题",
        raw="",
    )
    db.add_all([post_a, post_b])
    db.commit()
    auto_merge_creator(db, owner.id)
    db.refresh(post_a)
    db.refresh(post_b)
    assert post_a.work_id == post_b.work_id, "测试前置：两帖应被合并"
    return post_a, post_b


def test_already_downloaded_cross_run_skips_re_download(db, tmp_path, monkeypatch):
    """跨次同步：A 平台已下载视频且 work_id 为 None，B 平台同步时应复用而不重新下载。"""
    owner, dy_acc, xhs_acc = _make_owner_with_accounts(db)
    post_a, post_b = _make_merged_posts(db, owner, dy_acc, xhs_acc)

    videos_dir = tmp_path / "videos"
    videos_dir.mkdir(parents=True, exist_ok=True)
    (videos_dir / "real.mp4").write_bytes(b"fake")
    monkeypatch.setattr(media_ensure, "_videos_dir", lambda: videos_dir)

    video = Video(
        filename="real.mp4",
        title="同一个标题",
        creator_id=owner.id,
        work_id=None,  # 模拟 A 单独同步时还没合并
    )
    db.add(video)
    db.commit()
    video.transcript = Transcript(
        video_id=video.id,
        transcript_text="口播内容",
        corrected_text="口播内容",
        asr_status="done",
    )
    db.commit()

    post_a.local_video_id = video.id
    db.commit()

    # 合并回填后 Video.work_id 应被修正
    auto_merge_creator(db, owner.id)
    db.refresh(video)
    assert video.work_id == post_a.work_id

    called: list = []

    def _boom(*args, **kwargs):  # noqa: ANN001, ANN002
        called.append(True)
        raise RuntimeError("不应重新下载")

    monkeypatch.setattr(media_ensure, "_download_pick", _boom)

    info = media_ensure.inspect_media(db, post_id=post_b.id)
    assert info["action"] == "skip"
    assert info["has_file"] is True
    assert not called, "inspect_media 不应触发下载"

    res = media_ensure.platform_media_task(db, {"post_id": post_b.id})
    assert res["status"] == "skip"
    assert not called, "platform_media_task 不应触发下载"


def test_in_progress_claim_skips_second_download(db, tmp_path, monkeypatch):
    """A 平台正在下载中，B 平台同步时应因 work 级声明而跳过下载。"""
    owner, dy_acc, xhs_acc = _make_owner_with_accounts(db)
    post_a, post_b = _make_merged_posts(db, owner, dy_acc, xhs_acc)

    videos_dir = tmp_path / "videos"
    videos_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(media_ensure, "_videos_dir", lambda: videos_dir)

    work_id = post_a.work_id
    assert work_id is not None
    media_ensure._active_work_media.add(work_id)
    try:
        called: list = []

        def _boom(*args, **kwargs):  # noqa: ANN001, ANN002
            called.append(True)
            raise RuntimeError("不应并发下载")

        monkeypatch.setattr(media_ensure, "_download_pick", _boom)

        res = media_ensure.platform_media_task(db, {"post_id": post_b.id})
        assert res["status"] == "skip"
        assert "其它平台正在处理" in res.get("reason", "")
        assert not called, "B 不应实际下载"
    finally:
        media_ensure._active_work_media.discard(work_id)


def test_skipped_sibling_still_syncs_comments(db, monkeypatch):
    """同 work 内被标记 skip 的平台帖，评论/灵感池仍应同步，只有视频下载被跳过。"""
    from sqlalchemy.orm import sessionmaker as _sessionmaker

    # run_card_sync_queue 的消费者各自用独立 Session，用共享测试引擎（fresh_engine 已清库）
    eng = fresh_engine()
    ensure_schema(eng)
    session_factory = _sessionmaker(bind=eng, autoflush=False, autocommit=False)
    s = session_factory()

    try:
        owner, dy_acc, xhs_acc = _make_owner_with_accounts(s)
        post_a, post_b = _make_merged_posts(s, owner, dy_acc, xhs_acc)

        task_a = BackgroundTask(kind="card_sync", status="running", payload="{}")
        task_b = BackgroundTask(kind="card_sync", status="running", payload="{}")
        s.add_all([task_a, task_b])
        s.commit()

        comment_calls: list[int] = []
        media_calls: list[int] = []

        def _fake_sync_post_comments(db_session, post, **kwargs):  # noqa: ANN001, ANN002
            comment_calls.append(post.id)
            return {"added": 1, "updated": 0, "pool_added": 1}

        def _fake_platform_media_task(db_session, payload, update=None):  # noqa: ANN001, ANN002, ANN003
            media_calls.append(int(payload.get("post_id") or 0))
            return {"status": "done", "downloaded": True, "transcribed": False}

        monkeypatch.setattr(platform_sync_mod, "sync_post_comments", _fake_sync_post_comments)
        monkeypatch.setattr(media_ensure, "platform_media_task", _fake_platform_media_task)

        # 让 queue 的消费者使用同一个 engine 派生 session
        monkeypatch.setattr(sync_pool_mod, "session_factory", lambda _db: _sessionmaker(bind=eng, autoflush=False, autocommit=False))

        items = [(post_a.id, task_a.id), (post_b.id, task_b.id)]
        stats = media_ensure.run_card_sync_queue(s, items, with_media=True)

        assert len(comment_calls) == 2, "两个平台帖都应同步评论"
        assert post_a.id in comment_calls
        assert post_b.id in comment_calls
        assert len(media_calls) == 1, "视频下载/转写只应执行一次"
        assert media_calls[0] == post_a.id, "抖音优先级高，应由抖音帖执行媒体"
        assert stats["comments"] == 2
        assert stats["pool"] == 2
        assert stats["skipped"] == 1
    finally:
        s.close()
