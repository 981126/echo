"""R-202：非实时结果的任务化（/api/tasks 多状态 + label/target + 去重 + 接口转任务）。"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.api import drafts as drafts_api
from app.api import opportunities as opp_api
from app.api.tasks import get_task, list_tasks
from app.db import SessionLocal
from app.models.task import BackgroundTask
from app.tasks import find_running_task


def _add(kind: str, status: str, payload: dict) -> int:
    db = SessionLocal()
    try:
        t = BackgroundTask(kind=kind, status=status, payload=json.dumps(payload))
        db.add(t)
        db.commit()
        db.refresh(t)
        return t.id
    finally:
        db.close()


def _delete(*ids: int) -> None:
    db = SessionLocal()
    try:
        for i in ids:
            row = db.get(BackgroundTask, i)
            if row is not None:
                db.delete(row)
        db.commit()
    finally:
        db.close()


def test_find_running_task_dedup_and_payload_match():
    tid = _add("opportunity_gap", "running", {"limit": 6})
    try:
        assert find_running_task("opportunity_gap") == tid
        assert find_running_task("opportunity_gap", {"limit": 6}) == tid
        assert find_running_task("opportunity_gap", {"limit": 12}) is None  # payload 不匹配
        assert find_running_task("opportunity_weekly") is None
    finally:
        _delete(tid)
    assert find_running_task("opportunity_gap") is None  # 已结束


def test_list_tasks_multi_status_and_label_target():
    tid = _add("benchmark_prepare", "running", {"benchmark_id": 9})
    tid2 = _add("hot_refresh", "pending", {})
    try:
        db = SessionLocal()
        try:
            rows = list_tasks(limit=100, status="running,pending", kind="", db=db)
        finally:
            db.close()
        by_id = {r.id: r for r in rows}
        assert tid in by_id and tid2 in by_id
        assert by_id[tid].label == "对标转写补齐"
        assert by_id[tid].target == "/benchmark"

        db = SessionLocal()
        try:
            one = get_task(tid, db=db)
        finally:
            db.close()
        assert one.label == "对标转写补齐"
        assert one.status == "running"
    finally:
        _delete(tid, tid2)


def test_opportunity_gap_returns_task_and_dedups(monkeypatch):
    created: list[tuple[str, dict]] = []

    def fake_start(kind, payload, fn):
        created.append((kind, payload))
        return _add(kind, "pending", payload)

    monkeypatch.setattr(opp_api, "start_task", fake_start)
    db = SessionLocal()
    try:
        r1 = opp_api.gap_suggestions(limit=6, db=db)
        r2 = opp_api.gap_suggestions(limit=6, db=db)
    finally:
        db.close()
    try:
        assert r1["task_id"] == r2["task_id"]  # 进行中直接复用
        assert len(created) == 1
        assert created[0][0] == "opportunity_gap"
    finally:
        _delete(r1["task_id"])


def test_draft_angles_returns_task(monkeypatch):
    created: list[str] = []

    def fake_start(kind, payload, fn):
        created.append(kind)
        return _add(kind, "pending", payload)

    monkeypatch.setattr(drafts_api, "start_task", fake_start)
    db = SessionLocal()
    try:
        r = drafts_api.suggest_angles(drafts_api.AnglesIn(topic="面试自我介绍"), db=db)
    finally:
        db.close()
    try:
        assert r["task_id"] > 0
        assert created == ["draft_angles"]
    finally:
        _delete(r["task_id"])
