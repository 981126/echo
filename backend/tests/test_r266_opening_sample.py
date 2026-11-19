"""R-266：开头样本构建（首句/类型/百分位/同行倍数/反例）。"""

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
from app.models.opening_sample import OpeningSample
from app.models.platform import Creator, CreatorAccount, PlatformPost, PlatformPostStat
from app.models.video import Transcript, Video
from app.models.video_review import DouyinPostMetric, VideoReview
from app.services import opening_sample as svc


@pytest.fixture()
def db(tmp_path):
    eng = fresh_engine()
    ensure_schema(eng)
    session = sessionmaker(bind=eng, autoflush=False, autocommit=False)()
    yield session
    session.close()


def _creator(db, name: str, kind: str) -> Creator:
    row = Creator(kind=kind, name=name, is_current=(kind == "owner"))
    db.add(row)
    db.flush()
    db.add(
        CreatorAccount(
            creator_id=row.id,
            platform="douyin",
            nickname=name,
            platform_user_id=f"u{row.id}",
            enabled=True,
        )
    )
    db.commit()
    return row


def _video(db, creator: Creator, index: int, text: str, *, ad: bool = False) -> Video:
    video = Video(filename=f"r266-{creator.id}-{index}.mp4", title=f"作品{index}", creator_id=creator.id, is_ad=ad)
    db.add(video)
    db.flush()
    db.add(Transcript(video_id=video.id, transcript_text=text, corrected_text=text, asr_status="done"))
    db.commit()
    return video


def _post(db, video: Video, *, plays: int, finish_5s: float | None, drop: str = "") -> PlatformPost:
    account = db.query(CreatorAccount).filter_by(creator_id=video.creator_id).one()
    post = PlatformPost(
        account_id=account.id,
        platform="douyin",
        platform_post_id=f"p{video.id}",
        title=video.title,
        publish_time=_app_now() - timedelta(days=1),
        duration_seconds=90,
        local_video_id=video.id,
        raw="{}",
    )
    db.add(post)
    db.flush()
    db.add(DouyinPostMetric(post_id=post.id, snapshot_date="2026-11-01", finish_5s_rate=finish_5s))
    db.add(PlatformPostStat(post_id=post.id, stat_date="2026-11-01", plays=plays, likes=10))
    if drop:
        db.add(
            VideoReview(
                account_id=1,
                post_id=post.id,
                status="done",
                metrics_snapshot=json.dumps(
                    {"charts": {"retention": {"drops": [{"time_label": drop, "drop": 0.12, "end_seconds": 6}]}}}
                ),
            )
        )
    db.commit()
    return post


def test_first_sentence_and_classify():
    assert svc.first_sentence("投简历被拒？先看目标。后面还有") == "投简历被拒"
    assert svc.first_sentence("大家好，今天聊 3 个方法。第二句")[:6] == "大家好，今天"
    assert svc.first_sentence("甲" * 200).endswith("…")
    assert svc.classify_opening("投简历一直被拒。") == "result"
    assert svc.classify_opening("为什么你投了 100 份还没面试？") == "question"
    assert svc.classify_opening("月薪 3 万的人都在干嘛") == "number"
    assert svc.classify_opening("大家好，今天聊面试") == "background"
    assert svc.classify_opening("简历只是第一关") == "statement"


def test_build_samples_percentile_and_negative(db):
    owner = _creator(db, "我", "owner")
    owner_videos = []
    for index in range(21):
        video = _video(db, owner, index, f"被拒第 {index} 次后我才明白。先确定目标。")
        _post(db, video, plays=1000 + index, finish_5s=0.2 + index * 0.01, drop="00:04–00:06" if index == 0 else "")
        owner_videos.append(video)

    peer = _creator(db, "同行", "benchmark")
    peer_videos = []
    for index, plays in enumerate((100, 300)):
        video = _video(db, peer, index, f"同行开头 {index}。后面是正文。")
        _post(db, video, plays=plays, finish_5s=None, drop="00:02–00:04")
        peer_videos.append(video)

    result = svc.build_opening_samples(db, owner_id=owner.id)
    assert result["own"] == 21
    assert result["peer"] == 2

    rows = db.query(OpeningSample).all()
    own = [row for row in rows if row.source_kind == "own"]
    assert all(row.polarity for row in own)
    low = min(own, key=lambda row: row.finish_5s_rate)
    high = max(own, key=lambda row: row.finish_5s_rate)
    assert low.polarity == "low"
    assert high.polarity == "high"
    assert 0 <= low.rank_score <= 100
    assert "掉 12.0 个百分点" in low.negative_reason

    peers = [row for row in rows if row.source_kind == "peer"]
    assert {round(row.rank_score, 2) for row in peers} == {0.5, 1.5}
    assert all(row.polarity == "neutral" for row in peers)
    assert all(row.baseline_note == "同行公开播放，非留人数据" for row in peers)
    assert all(row.finish_5s_rate is None for row in peers)

    stats = svc.coverage(db, owner.id)
    assert stats["own"] == 21 and stats["peer"] == 2
    assert stats["samples_enough"] is True


def test_small_sample_has_no_polarity(db):
    owner = _creator(db, "我", "owner")
    for index in range(3):
        video = _video(db, owner, index, f"被拒 {index} 次。正文。")
        _post(db, video, plays=100, finish_5s=0.3 + index * 0.05)
    svc.build_opening_samples(db, owner_id=owner.id)
    rows = db.query(OpeningSample).all()
    assert rows and all(row.polarity == "" for row in rows)
    assert svc.coverage(db, owner.id)["samples_enough"] is False


def test_ad_and_missing_metric_are_skipped(db):
    owner = _creator(db, "我", "owner")
    ad_video = _video(db, owner, 0, "广告开头。正文。", ad=True)
    _post(db, ad_video, plays=100, finish_5s=0.5)
    no_metric = _video(db, owner, 1, "没有指标的开头。正文。")
    _post(db, no_metric, plays=100, finish_5s=None)
    result = svc.build_opening_samples(db, owner_id=owner.id)
    assert result["own"] == 0
    assert db.query(OpeningSample).count() == 0
