from __future__ import annotations

import json
import sys
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest
from conftest import ensure_schema, fresh_engine
from cryptography.fernet import Fernet
from sqlalchemy.orm import sessionmaker

from app.config import get_settings
from app.core.timeutil import now
from app.models.platform import Creator, CreatorAccount, PlatformPost, PlatformPostComment, PlatformPostStat
from app.models.video import Transcript, Video
from app.models.video_review import VideoImprovementPlan, VideoReview, VideoTopicRecommendation
from app.services.douyin_creator_sync import decrypt_cookie, encrypt_cookie
from app.services.douyin_references import _text, refresh_references
from app.services.video_review_comparison import build_comparison, peer_references
from app.services.video_review_service import adopt_topic, link_plan, run_analysis, run_plan_check


@pytest.fixture()
def db():
    eng = fresh_engine()
    ensure_schema(eng)
    session = sessionmaker(bind=eng, autoflush=False, autocommit=False)()
    yield session
    session.close()


def _owner(db) -> tuple[Creator, CreatorAccount]:
    owner = Creator(kind="owner", name="作者", is_current=True)
    db.add(owner)
    db.flush()
    account = CreatorAccount(creator_id=owner.id, platform="douyin", nickname="作者抖音")
    db.add(account)
    db.commit()
    return owner, account


def _post(db, account: CreatorAccount, index: int, plays: int, days_ago: int = 10) -> PlatformPost:
    published = now() - timedelta(days=days_ago)
    post = PlatformPost(
        account_id=account.id,
        platform="douyin",
        platform_post_id=f"external-{account.id}-{index}",
        title=f"面试自我介绍怎么做 {index}",
        publish_time=published,
        raw="{}",
    )
    db.add(post)
    db.flush()
    db.add(PlatformPostStat(
        post_id=post.id,
        stat_date=(published + timedelta(days=3)).date().isoformat(),
        plays=plays,
        likes=max(1, plays // 20),
        comments=max(1, plays // 500),
        favorites=max(1, plays // 300),
        shares=max(1, plays // 800),
    ))
    db.commit()
    return post


def _update(pct=None, note=""):
    return None


def test_comparison_uses_samples_and_real_zero(db):
    owner, account = _owner(db)
    for index in range(6):
        _post(db, account, index, 5000 + index * 100, 20 + index)
    target = _post(db, account, 99, 10000, 3)
    result = build_comparison(db, target)
    assert result["comparison"]["count"] == 6
    assert result["facts"]["plays"]["value"] == 10000
    assert result["facts"]["plays"]["baseline"] > 0
    assert result["facts"]["follower_gain"]["missing"] is True
    assert result["facts"]["follower_gain"]["value"] is None


def test_comparison_uses_valid_sample_count_for_overall(db):
    _, account = _owner(db)
    for index in range(6):
        post = _post(db, account, index, 5000, 20 + index)
        if index < 4:
            db.query(PlatformPostStat).filter_by(post_id=post.id).delete()
    target = _post(db, account, 99, 10000, 3)
    result = build_comparison(db, target)
    assert result["comparison"]["count"] == 6
    assert result["facts"]["plays"]["sample_count"] == 2
    assert result["overall"] == "unknown"
    assert result["warnings"]


def test_peer_requires_manual_relationship_and_two_x(db):
    owner, account = _owner(db)
    benchmark = Creator(kind="benchmark", parent_id=owner.id, name="同行")
    db.add(benchmark)
    db.flush()
    other = CreatorAccount(creator_id=benchmark.id, platform="douyin", nickname="同行")
    db.add(other)
    db.commit()
    for index in range(5):
        _post(db, other, index, 1000, 10 + index)
    hit = _post(db, other, 99, 10000, 2)
    items, charts = peer_references(db, owner)
    assert len(items) == 1
    assert items[0]["verdict"] == "同行爆款"
    assert items[0]["verdict_evidence"]["play_multiple"] >= 2
    assert charts[0]["post_id"] == hit.id


def test_analysis_adopt_link_and_check(db):
    owner, account = _owner(db)
    for index in range(6):
        _post(db, account, index, 5000 + index * 100, 20 + index)
    target = _post(db, account, 99, 10000, 3)
    video = Video(filename="r237.mp4", title=target.title, creator_id=owner.id, main_topics='["面试"]', status="published")
    db.add(video)
    db.flush()
    db.add(Transcript(video_id=video.id, transcript_text="面试自我介绍先给结果，再讲经历。", asr_status="done"))
    target.local_video_id = video.id
    db.add(PlatformPostComment(post_id=target.id, platform="douyin", text="面试自我介绍应该怎么说？", likes=8, user_nick="观众1"))
    db.commit()
    review = VideoReview(account_id=account.id, post_id=target.id, input_fingerprint="test")
    db.add(review)
    db.commit()
    result = run_analysis(db, {"review_id": review.id, "refresh": True}, _update)
    assert result["review_id"] == review.id
    db.refresh(review)
    assert review.status in ("done", "partial")
    assert review.metrics_snapshot
    topics = db.query(VideoTopicRecommendation).filter_by(review_id=review.id).all()
    assert topics
    primary = next(x for x in topics if x.role == "primary")
    plan = adopt_topic(db, primary, {"kept_text": "保留主题", "changes": ["开头先给结果"], "target_metrics": ["plays"]})
    assert isinstance(plan, VideoImprovementPlan)
    plan.created_at = now() - timedelta(days=2)
    db.commit()
    published = _post(db, account, 100, 16000, 1)
    link_plan(db, plan, published, replace=False)
    checked = run_plan_check(db, {"plan_id": plan.id, "refresh": False}, _update)
    assert checked["items"][0]["result"] in ("improved", "not_improved", "uncertain")
    assert checked["items"][0]["before"] is not None
    assert checked["items"][0]["after"] is not None


def test_low_fan_refresh_keeps_official_label(db):
    owner, _ = _owner(db)
    result = refresh_references(db, owner, {"category_id": "628", "keyword": "", "date_window": 168})
    assert result["saved"] == 2


def test_reference_text_is_bounded():
    assert len(_text("面" * 700, 500)) == 500
    assert _text(None, 100) == ""


def test_cookie_is_encrypted(db):
    settings = get_settings()
    old = settings.douyin_cookie_key
    settings.douyin_cookie_key = Fernet.generate_key().decode()
    try:
        encrypted = encrypt_cookie("session-secret")
        assert encrypted != "session-secret"
        assert "session-secret" not in encrypted
        assert decrypt_cookie(encrypted) == "session-secret"
    finally:
        settings.douyin_cookie_key = old


# ---------- 2026-10-30 真实接口冒烟后补充：真实字段映射 / 业务错误 / 同行播放量补采 ----------

from app.models.video_review import (  # noqa: E402
    DouyinCreatorCredential,
    DouyinPostMetric,
    DouyinReferenceVideo,
)
from app.services import douyin_creator_sync as sync_mod  # noqa: E402
from app.services import douyin_references as refs_mod  # noqa: E402
from app.services.douyin_creator_sync import (  # noqa: E402
    CredentialError,
    backfill_peer_plays,
    sync_post_creator_data,
)
from app.services.platform.tikhub import TikHubBusinessError  # noqa: E402
from app.services.video_review_service import _post_out  # noqa: E402


def _real_credential(db, account: CreatorAccount, monkeypatch) -> None:
    monkeypatch.setattr(get_settings(), "douyin_cookie_key", Fernet.generate_key().decode())
    db.add(DouyinCreatorCredential(account_id=account.id, cookie_value=encrypt_cookie("sessionid=fake"), status="valid"))
    db.commit()


class _CreatorRealClient:
    """真实 creator_v2 响应形状的假客户端（不联网）。"""

    mode = "real"
    requests_used = 0

    def fetch_douyin_creator_overview(self, *, cookie: str, item_id: str) -> dict:
        return {
            "data": {
                "items": [{
                    "id": item_id,
                    "create_time": "1793281505",
                    "video_info": {"duration": "85774"},
                    "metrics": {
                        "view_count": "6735",
                        "like_count": "151",
                        "comment_count": "10",
                        "share_count": "13",
                        "favorite_count": "17",
                        "bounce_rate_2s": "0.294310",
                        "completion_rate_5s": "0.479379",
                        "completion_rate": "0.074710",
                        "avg_view_second": "18.067086",
                        "homepage_visit_count": "0",
                        "subscribe_count": "4",
                        "unsubscribe_count": "16",
                    },
                }],
                "status_code": 0,
                "status_msg": "",
            }
        }

    def fetch_douyin_creator_play_source(self, *, cookie: str, item_id: str) -> dict:
        return {"data": {"play_source": [{"key": "homepage_hot", "value": 0.786}, {"key": "follow", "value": 0.184}], "status_code": 0}}

    def fetch_douyin_creator_search_keyword(self, *, cookie: str, item_id: str) -> dict:
        return {"data": {"inspire_search": [{"keyword": "面试技巧", "percent": 0.424}], "show_from": [], "status_code": 0}}

    def fetch_douyin_watch_trend(self, *, cookie: str, item_id: str, analysis_type: int) -> dict:
        return {"data": {"analysis_trend": {"current_item": [{"key": "00:00", "value": 1.0}, {"key": "00:01", "value": 0.85}], "similar_author": []}, "status_code": 0}}


def test_creator_real_metrics_mapping(db, monkeypatch):
    owner, account = _owner(db)
    _real_credential(db, account, monkeypatch)
    post = _post(db, account, 1, 6735, 3)
    monkeypatch.setattr(sync_mod, "make_client", lambda: _CreatorRealClient())
    result = sync_post_creator_data(db, account, post)
    assert result["post_id"] == post.id
    metric = db.query(DouyinPostMetric).filter_by(post_id=post.id).one()
    assert metric.bounce_2s_rate == pytest.approx(0.29431)
    assert metric.finish_5s_rate == pytest.approx(0.479379)
    assert metric.finish_rate == pytest.approx(0.07471)
    assert metric.avg_play_seconds == pytest.approx(18.067086)
    assert metric.profile_visits == 0
    assert metric.follower_gain == 4  # 创作者中心「吸粉量」= subscribe_count
    assert metric.cover_click_rate is None  # 平台未返回，不估算
    today_stat = db.query(PlatformPostStat).filter_by(post_id=post.id).order_by(PlatformPostStat.stat_date.desc()).first()
    assert today_stat.plays == 6735
    traffic = metric.traffic_sources
    assert "推荐" in traffic
    assert "面试技巧" in metric.search_terms
    assert json.loads(metric.retention_trend)


class _AuthFailClient:
    mode = "real"
    requests_used = 0

    def fetch_douyin_creator_overview(self, *, cookie: str, item_id: str) -> dict:
        raise TikHubBusinessError("TikHub 业务错误 8：用户未登录", code=8)


def test_business_error_is_not_treated_as_success(db, monkeypatch):
    owner, account = _owner(db)
    _real_credential(db, account, monkeypatch)
    post = _post(db, account, 2, 5000, 3)
    db.query(PlatformPostStat).filter_by(post_id=post.id).delete()
    db.commit()
    monkeypatch.setattr(sync_mod, "make_client", lambda: _AuthFailClient())
    with pytest.raises(CredentialError):
        sync_post_creator_data(db, account, post)
    assert db.query(DouyinPostMetric).filter_by(post_id=post.id).count() == 0
    assert db.query(PlatformPostStat).filter_by(post_id=post.id).count() == 0
    credential = db.query(DouyinCreatorCredential).filter_by(account_id=account.id).one()
    assert credential.status == "invalid"
    assert "Cookie" in credential.last_error


class _BillboardClient:
    mode = "real"
    requests_used = 0

    def fetch_douyin_low_fan(self, **kwargs):
        # 真实响应为两层信封：{code, data: {code, data: {objs: [...]}, extra, message}}
        return {
            "code": 200,
            "data": {
                "code": 0,
                "data": {
                    "objs": [{
                        "item_id": "7100000000000000001",
                        "item_title": "低粉爆款：面试反问怎么问",
                        "item_cover_url": "https://example.com/cover.jpg",
                        "item_url": "https://lf9-music.example.com/some.mp3",
                        "item_duration": 27900,
                        "publish_time": 1761700000,
                        "nick_name": "小周",
                        "fans_cnt": 1800,
                        "play_cnt": 180000,
                        "like_cnt": 9600,
                        "share_cnt": 800,
                        "image_cnt": 1,
                        "media_type": 2,
                    }],
                    "page": {"page": 1, "total": 1, "page_size": 20},
                },
                "extra": {},
                "message": "",
            },
        }


def test_billboard_real_shape_parsed(db, monkeypatch):
    owner, _ = _owner(db)
    monkeypatch.setattr(refs_mod, "make_client", lambda: _BillboardClient())
    result = refresh_references(db, owner, {"category_id": "628", "keyword": "", "date_window": 168})
    assert result["saved"] == 1
    row = db.query(DouyinReferenceVideo).filter_by(external_post_id="7100000000000000001").one()
    assert row.title == "低粉爆款：面试反问怎么问"
    assert row.author_nickname == "小周"
    assert row.author_followers == 1800
    assert row.plays == 180000
    assert row.duration_seconds == 28  # 毫秒归一到秒
    # item_url 是图片贴的音乐资源，不能当视频链接；应回退到作品页
    assert row.video_url == "https://www.douyin.com/note/7100000000000000001"
    assert row.source == "low_fan_billboard"


class _SearchClient:
    mode = "real"
    requests_used = 0

    def __init__(self) -> None:
        self.date_type = None

    def search_douyin_items(self, *, query: str, category_id: str, date_type: int, label_type: int, duration_type: int) -> dict:
        self.date_type = date_type
        return {"data": {"items": [{"itemId": "7100000000000000002", "itemTitle": "面试自我介绍", "duration": 79, "likes": "110", "createTime": "2026-10-25 17:25:57"}]}}

    def fetch_douyin_video_statistics(self, item_id: str) -> dict:
        return {"data": {"statistics_list": [{"aweme_id": item_id, "play_count": 13017, "digg_count": 128, "share_count": 13, "comment_count": 2}]}}


def test_index_search_valid_date_type_and_play_backfill(db, monkeypatch):
    owner, _ = _owner(db)
    client = _SearchClient()
    monkeypatch.setattr(refs_mod, "make_client", lambda: client)
    result = refresh_references(db, owner, {"category_id": "0", "keyword": "面试", "date_window": 168})
    assert result["saved"] == 1
    assert client.date_type == 7  # 168 小时 → date_type=7，绝不发非法的 1
    row = db.query(DouyinReferenceVideo).filter_by(external_post_id="7100000000000000002").one()
    assert row.plays == 13017
    assert row.duration_seconds == 79


class _PeerStatsClient:
    mode = "real"
    requests_used = 0

    def fetch_douyin_video_statistics(self, item_ids) -> dict:
        ids = item_ids if isinstance(item_ids, str) else ",".join(item_ids)
        return {"data": {"statistics_list": [{"aweme_id": item, "play_count": 50000 + index * 1000, "digg_count": 100, "comment_count": 2, "share_count": 1} for index, item in enumerate(ids.split(","))]}}


def test_backfill_peer_plays_and_reuse(db, monkeypatch):
    owner, _ = _owner(db)
    benchmark = Creator(kind="benchmark", parent_id=owner.id, name="同行")
    db.add(benchmark)
    db.flush()
    other = CreatorAccount(creator_id=benchmark.id, platform="douyin", nickname="同行")
    db.add(other)
    db.commit()
    for index in range(2):
        db.add(PlatformPost(account_id=other.id, platform="douyin", platform_post_id=f"peer-{index}", title=f"同行视频 {index}", publish_time=now() - timedelta(days=2), raw="{}"))
    db.commit()
    monkeypatch.setattr(sync_mod, "make_client", lambda: _PeerStatsClient())
    result = backfill_peer_plays(db, owner, force=True)
    assert result["updated"] == 2
    stats = db.query(PlatformPostStat).filter(PlatformPostStat.post_id.in_([p.id for p in db.query(PlatformPost).filter_by(account_id=other.id)])).all()
    assert len(stats) == 2
    assert all(stat.plays > 0 for stat in stats)
    reused = backfill_peer_plays(db, owner)
    assert reused["reused"] is True and reused["requests"] == 0


def test_post_duration_is_converted_from_milliseconds(db):
    owner, account = _owner(db)
    post = PlatformPost(account_id=account.id, platform="douyin", platform_post_id="x", title="t", raw='{"duration": 147469}', publish_time=now())
    db.add(post)
    db.commit()
    assert _post_out(post)["duration_seconds"] == 147
