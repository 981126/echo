"""R-267：草稿→作品绑定、效果回填与资产回流。"""

from __future__ import annotations

import json
import sys
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest
from conftest import ensure_schema, fresh_engine
from sqlalchemy.orm import sessionmaker

from app.core.timeutil import now as _app_now
from app.models.author_generation import AuthorAsset, GenerationRun
from app.models.draft import Draft
from app.models.platform import Creator, CreatorAccount, PlatformPost, PlatformPostStat
from app.models.video import Video
from app.models.video_review import DouyinPostMetric
from app.services import draft_publish


@pytest.fixture()
def db(tmp_path):
    eng = fresh_engine()
    ensure_schema(eng)
    session = sessionmaker(bind=eng, autoflush=False, autocommit=False)()
    yield session
    session.close()


def _owner(db, *, current: bool = True) -> tuple[Creator, CreatorAccount]:
    creator = Creator(kind="owner", name="我", is_current=current)
    db.add(creator)
    db.flush()
    account = CreatorAccount(
        creator_id=creator.id, platform="douyin", nickname="我的抖音", platform_user_id=f"u{creator.id}", enabled=True
    )
    db.add(account)
    db.commit()
    return creator, account


def _post(db, account, index: int, *, title: str, plays: int, finish_5s: float | None, days_ago: int = 1):
    post = PlatformPost(
        account_id=account.id,
        platform="douyin",
        platform_post_id=f"p-{account.id}-{index}",
        title=title,
        publish_time=_app_now() - timedelta(days=days_ago),
        duration_seconds=90,
        raw="{}",
    )
    db.add(post)
    db.flush()
    db.add(PlatformPostStat(post_id=post.id, stat_date="2026-11-01", plays=plays, likes=10, favorites=3, comments=2))
    db.add(
        DouyinPostMetric(
            post_id=post.id,
            snapshot_date="2026-11-01",
            finish_5s_rate=finish_5s,
            bounce_2s_rate=0.4 if finish_5s is not None else None,
            finish_rate=0.05 if finish_5s is not None else None,
        )
    )
    db.commit()
    return post


def _draft(db, creator: Creator, *, title: str = "投简历一直被拒") -> Draft:
    row = Draft(creator_id=creator.id, title=title, script="正文", source="ai")
    db.add(row)
    db.commit()
    return row


def test_candidates_only_current_account(db):
    creator, account = _owner(db)
    other, other_account = _owner(db, current=False)
    _post(db, account, 1, title="投简历被拒怎么办", plays=100, finish_5s=0.4)
    _post(db, other_account, 2, title="别人的作品", plays=200, finish_5s=0.3)
    items = draft_publish.candidates(db, query="简历")
    assert len(items) == 1
    assert items[0]["title"] == "投简历被拒怎么办"
    assert items[0]["has_local_video"] is False


def test_bind_rejects_other_creator_post(db):
    creator, _account = _owner(db)
    _other, other_account = _owner(db, current=False)
    foreign = _post(db, other_account, 9, title="别人的作品", plays=100, finish_5s=0.3)
    draft = _draft(db, creator)
    with pytest.raises(ValueError, match="不属于当前主博主"):
        draft_publish.bind(db, draft, post_id=foreign.id)


def test_bind_writes_fields_and_performance(db):
    creator, account = _owner(db)
    for index in range(6):
        _post(db, account, index, title=f"同类作品 {index}", plays=1000 + index, finish_5s=0.3 + index * 0.01)
    target = _post(db, account, 99, title="投简历一直被拒", plays=5000, finish_5s=0.52)
    draft = _draft(db, creator)

    perf = draft_publish.bind(db, draft, post_id=target.id)
    db.refresh(draft)
    assert draft.post_id == target.id
    assert draft.publish_platform == "douyin"
    assert draft.published_at is not None
    item = perf["metrics"]["finish_5s_rate"]
    assert item["value"] == pytest.approx(0.52)
    assert item["baseline"] is not None
    assert perf["private_metrics"] is True


def test_unbind_clears_binding_but_keeps_video(db):
    creator, account = _owner(db)
    video = Video(filename="r267.mp4", title="素材", creator_id=creator.id)
    db.add(video)
    db.commit()
    target = _post(db, account, 1, title="作品", plays=100, finish_5s=0.4)
    draft = _draft(db, creator)
    draft_publish.bind(db, draft, post_id=target.id, video_id=video.id)
    db.refresh(draft)
    assert draft.video_id == video.id

    draft_publish.unbind(db, draft)
    db.refresh(draft)
    assert draft.post_id is None
    assert draft.performance == "{}"
    assert draft.video_id == video.id


def test_refresh_uses_cache_and_force(db):
    creator, account = _owner(db)
    target = _post(db, account, 1, title="作品", plays=100, finish_5s=0.4)
    draft = _draft(db, creator)
    first = draft_publish.bind(db, draft, post_id=target.id)
    db.refresh(draft)
    cached = draft_publish.refresh(db, draft)
    assert cached["refreshed_at"] == first["refreshed_at"]
    forced = draft_publish.refresh(db, draft, force=True)
    assert forced["refreshed_at"] >= first["refreshed_at"]


def test_asset_feedback_written_with_percentile(db):
    creator, account = _owner(db)
    for index in range(6):
        _post(db, account, index, title=f"同类 {index}", plays=1000, finish_5s=0.2 + index * 0.02)
    target = _post(db, account, 99, title="投简历一直被拒", plays=5000, finish_5s=0.5)
    asset = AuthorAsset(
        creator_id=creator.id,
        asset_kind="experience",
        source_kind="asr",
        content="我投过很多简历",
        content_hash="hash-r267",
        status="active",
    )
    db.add(asset)
    db.commit()
    draft = _draft(db, creator)
    db.add(
        GenerationRun(
            creator_id=creator.id,
            draft_id=draft.id,
            topic=draft.title,
            status="succeeded",
            evidence_json=json.dumps({"author_assets": [{"id": asset.id}], "online_sources": []}),
        )
    )
    db.commit()

    perf = draft_publish.bind(db, draft, post_id=target.id)
    percentile = perf["metrics"]["finish_5s_rate"]["percentile"]
    db.refresh(asset)
    stats = json.loads(asset.usage_stats)
    assert percentile is not None
    assert stats["performance"] == pytest.approx(percentile, abs=0.01)
    assert stats["published"]["count"] == 1
    assert stats["published"]["last_post_id"] == target.id


def test_no_private_metrics_skips_asset_writeback(db):
    creator, account = _owner(db)
    target = _post(db, account, 1, title="无创作者数据", plays=300, finish_5s=None)
    asset = AuthorAsset(
        creator_id=creator.id,
        asset_kind="fact",
        source_kind="asr",
        content="事实",
        content_hash="hash-r267-b",
        status="active",
    )
    db.add(asset)
    db.commit()
    draft = _draft(db, creator)
    db.add(
        GenerationRun(
            creator_id=creator.id,
            draft_id=draft.id,
            topic=draft.title,
            status="succeeded",
            evidence_json=json.dumps({"author_assets": [{"id": asset.id}]}),
        )
    )
    db.commit()

    perf = draft_publish.bind(db, draft, post_id=target.id)
    assert perf["private_metrics"] is False
    assert perf["metrics"]["finish_5s_rate"]["missing"] is True
    db.refresh(asset)
    assert json.loads(asset.usage_stats).get("performance") is None
