"""R-265：留存曲线补齐的覆盖统计、计划筛选与写入/失败口径。"""

from __future__ import annotations

import json
import sys
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest
from conftest import ensure_schema, fresh_engine
from sqlalchemy.orm import sessionmaker

from app.core.timeutil import now as _app_now
from app.models.platform import Creator, CreatorAccount, PlatformPost, PlatformPostStat
from app.models.video_review import DouyinPostMetric
from app.services import retention_backfill as rb


@pytest.fixture()
def db(tmp_path):
    eng = fresh_engine()
    ensure_schema(eng)
    session = sessionmaker(bind=eng, autoflush=False, autocommit=False)()
    yield session
    session.close()


def _seed(db):
    creator = Creator(kind="owner", name="我", is_current=True)
    db.add(creator)
    db.commit()
    account = CreatorAccount(
        creator_id=creator.id,
        platform="douyin",
        nickname="我的抖音",
        platform_user_id="MS4w-test-r265",
        enabled=True,
        sync_frequency="daily",
    )
    db.add(account)
    db.commit()
    return creator, account


def _post(db, account, external_id: str, *, days_ago: int, has_5s: bool = True, has_trend: bool = False):
    post = PlatformPost(
        account_id=account.id,
        platform="douyin",
        platform_post_id=external_id,
        title=f"作品 {external_id}",
        publish_time=_app_now() - timedelta(days=days_ago),
        raw="{}",
    )
    db.add(post)
    db.flush()
    db.add(
        DouyinPostMetric(
            post_id=post.id,
            snapshot_date="2026-11-01",
            finish_5s_rate=0.4 if has_5s else None,
            retention_trend=json.dumps([{"key": "00:00", "value": 1}]) if has_trend else "[]",
        )
    )
    db.add(PlatformPostStat(post_id=post.id, stat_date="2026-11-01", plays=1200))
    db.commit()
    return post


def test_coverage_and_plan_filters(db):
    _creator, account = _seed(db)
    _post(db, account, "a", days_ago=1)
    _post(db, account, "b", days_ago=10)
    _post(db, account, "covered", days_ago=2, has_trend=True)
    _post(db, account, "no5s", days_ago=3, has_5s=False)

    stats = rb.coverage(db, account)
    assert stats == {"total": 3, "covered": 1, "pending": 2}
    assert len(rb.plan_post_ids(db, account)) == 2
    recent = rb.plan_post_ids(db, account, scope="recent")
    assert [pid for pid in recent] == [rb.plan_post_ids(db, account)[0]]


def test_save_trend_keeps_bounce_and_marks_reliable(db):
    _creator, account = _seed(db)
    post = _post(db, account, "merge", days_ago=1)
    metric = db.query(DouyinPostMetric).filter_by(post_id=post.id).one()
    metric.similar_author_trend = json.dumps({"bounce": [{"key": "00:00", "value": 0.1}]})
    db.commit()

    rb._save_trend(db, post, [{"key": "00:00", "value": 1}, {"key": "00:02", "value": 0.5}], [{"value": 0.7}])
    db.refresh(metric)
    merged = json.loads(metric.similar_author_trend)
    assert merged["bounce"] == [{"key": "00:00", "value": 0.1}]
    assert merged["retention"] == [{"value": 0.7}]
    assert metric.trend_reliable is True
    assert json.loads(metric.retention_trend)[1]["value"] == 0.5


def test_run_backfill_counts_partial_failures(db, monkeypatch):
    _creator, account = _seed(db)
    ok_post = _post(db, account, "ok", days_ago=1)
    bad_post = _post(db, account, "bad", days_ago=2)

    class _Client:
        requests_used = 0

        def fetch_douyin_watch_trend(self, *, cookie, item_id, analysis_type):
            assert cookie == "cookie"
            assert analysis_type == 1
            self.requests_used += 1
            if item_id == "bad":
                raise RuntimeError("接口返回 402")
            return {"analysis_trend": {"current_item": [{"key": "00:00", "value": 1}], "similar_author": []}}

    monkeypatch.setattr(rb, "make_client", lambda: _Client())
    monkeypatch.setattr(rb, "_cookie", lambda db, account_id, client: "cookie")
    monkeypatch.setattr(rb, "resolve_data_policy", lambda db, account: SimpleNamespace(is_blocked=False, is_creator=True))
    monkeypatch.setattr(rb, "_charge_requests", lambda db, client, before: None)
    monkeypatch.setattr(rb.time, "sleep", lambda _seconds: None)

    progress: list[int] = []
    result = rb.run_backfill(
        db,
        {"account_id": account.id, "post_ids": [ok_post.id, bad_post.id]},
        lambda pct, note: progress.append(pct),
    )
    assert result["ok"] == 1
    assert result["failed"] == 1
    assert "成功 1、失败 1" in result["message"]
    assert progress[-1] == 100


def test_run_backfill_all_failed_raises(db, monkeypatch):
    _creator, account = _seed(db)
    post = _post(db, account, "bad", days_ago=1)

    class _Client:
        requests_used = 0

        def fetch_douyin_watch_trend(self, **_kwargs):
            raise RuntimeError("接口未返回观看趋势")

    monkeypatch.setattr(rb, "make_client", lambda: _Client())
    monkeypatch.setattr(rb, "_cookie", lambda db, account_id, client: "cookie")
    monkeypatch.setattr(rb, "resolve_data_policy", lambda db, account: SimpleNamespace(is_blocked=False, is_creator=True))
    monkeypatch.setattr(rb, "_charge_requests", lambda db, client, before: None)
    monkeypatch.setattr(rb.time, "sleep", lambda _seconds: None)

    with pytest.raises(RuntimeError, match="全部失败"):
        rb.run_backfill(db, {"account_id": account.id, "post_ids": [post.id]}, None)
