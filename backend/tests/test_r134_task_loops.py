"""R-134：任务终态与体验闭环测试（脏 running 清理、失败清状态、inbox 安全、补跑标记）。"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import Base
from app.models.draft import Draft
from app.models.kv import Kv
from app.models.notification import Notification
from app.models.platform import Creator, CreatorAccount, SyncJob
from app.models.task import BackgroundTask
from app.models.video import Video
from app.services import ingest as ingest_mod
from app.services import media_ensure
from app.services.debate import FAILED_SCRIPT, clear_debate_state
from app.tasks import _cleanup_stale_sync_state, mark_interrupted_tasks_on_startup


@pytest.fixture()
def db(tmp_path):
    eng = create_engine(f"sqlite:///{tmp_path}/t.db", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=eng)
    session = sessionmaker(bind=eng, autoflush=False, autocommit=False)()
    yield session
    session.close()
    eng.dispose()


def _set_kv(db, key, value):
    row = db.get(Kv, key)
    if row is None:
        db.add(Kv(key=key, value=value))
    else:
        row.value = value
    db.commit()


# ---------- 启动清理 ----------


def test_interrupted_tasks_are_notified(tmp_path, monkeypatch):
    from app import tasks as tasks_mod

    eng = create_engine(f"sqlite:///{tmp_path}/n.db", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=eng)
    factory = sessionmaker(bind=eng, autoflush=False, autocommit=False)
    monkeypatch.setattr(tasks_mod, "SessionLocal", factory)
    s = factory()
    s.add(BackgroundTask(kind="import_video", status="running", payload="{}"))
    s.add(BackgroundTask(kind="card_sync", status="pending", payload="{}"))
    s.commit()
    s.close()

    n = mark_interrupted_tasks_on_startup()
    assert n == 2
    s = factory()
    assert s.query(BackgroundTask).filter(BackgroundTask.status == "failed").count() == 2
    note = s.query(Notification).filter(Notification.kind == "task_interrupted").first()
    assert note is not None and "2 个任务被中断" in note.title
    s.close()


def test_persona_pending_flag_is_consumed(tmp_path, monkeypatch):
    from app import tasks as tasks_mod

    eng = create_engine(f"sqlite:///{tmp_path}/p.db", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=eng)
    factory = sessionmaker(bind=eng, autoflush=False, autocommit=False)
    monkeypatch.setattr(tasks_mod, "SessionLocal", factory)
    s = factory()
    s.add(Kv(key="persona_incremental_pending", value="1"))
    s.commit()
    s.close()

    called: list = []
    monkeypatch.setattr(
        "app.services.ingest.enqueue_persona_incremental",
        lambda _db, video=None, creator_id=None: called.append(creator_id) or 1,
    )
    mark_interrupted_tasks_on_startup()
    assert called, "pending 标记应触发重新入队"
    s = factory()
    row = s.get(Kv, "persona_incremental_pending")
    assert row is not None and row.value == "0"
    s.close()


def test_cleanup_stale_sync_state(db):
    owner = Creator(kind="owner", name="我", is_current=True)
    db.add(owner)
    db.flush()
    db.add(CreatorAccount(creator_id=owner.id, platform="douyin", nickname="我", sync_status="running"))
    db.add(SyncJob(job_type="sync", scope="daily", status="running"))
    db.commit()
    res = _cleanup_stale_sync_state(db)
    assert res == {"sync_jobs": 1, "accounts": 1}
    assert db.query(SyncJob).filter(SyncJob.status == "running").count() == 0
    assert db.query(CreatorAccount).filter(CreatorAccount.sync_status == "running").count() == 0


# ---------- card_sync 队列中断 ----------


def test_fail_remaining_marks_rows_failed(db):
    rows = [BackgroundTask(kind="card_sync", status="running", progress=4, note="排队中…") for _ in range(3)]
    db.add_all(rows)
    db.commit()
    items = [(1, r.id) for r in rows]
    n = media_ensure._fail_remaining(db, items, "已取消：同步预算不足")
    assert n == 3
    for r in rows:
        db.refresh(r)
        assert r.status == "failed" and "预算不足" in r.note


# ---------- 讨论状态清理 ----------


def test_clear_debate_state_resets_placeholder(db):
    draft = Draft(title="选题", script="（双模型讨论生成中…）", source="ai")
    db.add(draft)
    db.commit()
    _set_kv(db, f"debate:{draft.id}", "KIMI 正在起草…")
    clear_debate_state(db, draft.id)
    assert db.get(Kv, f"debate:{draft.id}") is None
    db.refresh(draft)
    assert draft.script == FAILED_SCRIPT


def test_debate_status_route_registered():
    import app.main

    paths = app.main.app.openapi()["paths"]
    assert "/api/drafts/{draft_id}/debate-status" in paths


# ---------- 补跑标记顺序 ----------


def test_rerun_if_pending_keeps_flag_when_enqueue_fails(db, monkeypatch):
    _set_kv(db, "persona_incremental_pending", "1")

    def _boom(*_a, **_k):
        raise RuntimeError("线程池满了")

    monkeypatch.setattr("app.tasks.start_task", _boom)
    ingest_mod._rerun_if_pending(db, None)
    row = db.get(Kv, "persona_incremental_pending")
    assert row is not None and row.value == "1"  # 入队失败 → 标记保留，下次仍会补跑


# ---------- inbox 安全 ----------


def _fake_settings(tmp_path):
    class _S:
        inbox_dir = tmp_path / "inbox"
        videos_dir = tmp_path / "videos"

    _S.inbox_dir.mkdir(parents=True, exist_ok=True)
    _S.videos_dir.mkdir(parents=True, exist_ok=True)
    return _S()


def test_inbox_registers_before_moving_file(tmp_path, monkeypatch):
    from app import watcher

    settings = _fake_settings(tmp_path)
    (settings.inbox_dir / "clip.mp4").write_bytes(b"fake")
    db = sessionmaker(bind=create_engine(f"sqlite:///{tmp_path}/w.db"), autoflush=False)()
    Base.metadata.create_all(bind=db.get_bind())
    monkeypatch.setattr(watcher, "SessionLocal", lambda: db)

    watcher._scan_once(settings)
    assert db.query(Video).count() == 1
    assert not list(settings.inbox_dir.glob("*.mp4"))  # 已移走
    assert list(settings.videos_dir.glob("*.mp4"))
    db.close()


def test_inbox_keeps_file_when_move_fails(tmp_path, monkeypatch):
    from app import watcher

    settings = _fake_settings(tmp_path)
    src = settings.inbox_dir / "clip.mp4"
    src.write_bytes(b"fake")
    db = sessionmaker(bind=create_engine(f"sqlite:///{tmp_path}/w2.db"), autoflush=False)()
    Base.metadata.create_all(bind=db.get_bind())
    monkeypatch.setattr(watcher, "SessionLocal", lambda: db)

    def _boom(self, _dest):  # noqa: ANN001
        raise OSError("disk full")

    monkeypatch.setattr(Path, "replace", _boom)
    watcher._scan_once(settings)
    assert src.exists(), "移动失败时文件必须留在 inbox"
    assert db.query(Video).count() == 0, "移动失败时要回滚入库记录，避免库里有文件没有"
    db.close()
