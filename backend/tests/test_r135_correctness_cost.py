"""R-135：重复入队判重、预算护栏、生成模型策略、选题池隔离、四维分回流测试。"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest
from conftest import ensure_schema, fresh_engine
from sqlalchemy.orm import sessionmaker

from app.models.kv import Kv
from app.models.hot_topic import TopicIdea
from app.models.platform import Creator
from app.models.task import BackgroundTask
from app.services import media_ensure
from app.services.platform.budget import BudgetExceeded, ensure_budget, get_budget
from app.services.pipeline import _comment_candidates


@pytest.fixture()
def db(tmp_path):
    eng = fresh_engine()
    ensure_schema(eng)
    session = sessionmaker(bind=eng, autoflush=False, autocommit=False)()
    yield session
    session.close()


def _set_kv(db, key, value):
    row = db.get(Kv, key)
    if row is None:
        db.add(Kv(key=key, value=str(value)))
    else:
        row.value = str(value)
    db.commit()


# ---------- 预算护栏 ----------


def test_ensure_budget_raises_when_exhausted(db):
    _set_kv(db, "tikhub_budget_limit", 5)
    from app.core.pipeline import today_key

    _set_kv(db, f"tikhub_budget_used:{today_key()}", 5)
    with pytest.raises(BudgetExceeded) as exc:
        ensure_budget(db)
    assert "未发起新请求" in str(exc.value)
    assert get_budget(db)["remaining"] == 0


def test_ensure_budget_ok_when_remaining(db):
    _set_kv(db, "tikhub_budget_limit", 100)
    ensure_budget(db)  # 不抛


# ---------- 重复入队判重 ----------


def test_submit_media_task_dedupes_pending(db, monkeypatch):
    db.add(
        BackgroundTask(
            kind="platform_media",
            status="running",
            payload=json.dumps({"post_id": 42}),
        )
    )
    db.commit()
    called: list = []
    monkeypatch.setattr(media_ensure, "start_task", lambda *a, **k: called.append(a) or 1)
    monkeypatch.setattr(
        media_ensure,
        "inspect_media",
        lambda _db, **_k: {"action": "download", "video_id": None},
    )
    res = media_ensure.submit_media_task(db, post_id=42)
    assert res["status"] == "duplicate"
    assert called == [], "已在队列中不应重复投递"


def test_submit_media_task_starts_when_no_duplicate(db, monkeypatch):
    called: list = []
    monkeypatch.setattr(media_ensure, "start_task", lambda *a, **k: called.append(a) or 7)
    monkeypatch.setattr(
        media_ensure,
        "inspect_media",
        lambda _db, **_k: {"action": "download", "video_id": None},
    )
    res = media_ensure.submit_media_task(db, post_id=99)
    assert res["status"] == "started" and res["task_id"] == 7
    assert called


# ---------- 生成模型策略 ----------




# ---------- 选题池博主隔离 ----------


def test_comment_candidates_filters_by_creator(db):
    owner = Creator(kind="owner", name="我", is_current=True)
    other = Creator(kind="benchmark", name="对标", parent_id=None)
    db.add_all([owner, other])
    db.flush()
    db.add(
        TopicIdea(
            creator_id=owner.id, source="comment", title="我的评论灵感", platform="douyin", snapshot_date="2099-01-01", likes=1
        )
    )
    db.add(
        TopicIdea(
            creator_id=other.id, source="comment", title="对标的评论灵感", platform="douyin", snapshot_date="2099-01-01", likes=99
        )
    )
    db.commit()
    titles = [x["title"] for x in _comment_candidates(db, None, days=36500)]
    assert "我的评论灵感" in titles
    assert "对标的评论灵感" not in titles, "对标博主的评论灵感不应进入主博主选题"


# R-211：四维分随反馈体系重构下线（`_dim_examples` 已删除，不再注入生成上下文）
