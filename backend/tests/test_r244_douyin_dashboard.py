"""R-244：抖音数据看板（账号总览/近期作品/作品分析/评论热词/刷新任务）。"""

from __future__ import annotations

import sys
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest
from conftest import ensure_schema, fresh_engine
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from app.api import douyin_dashboard
from app.core.timeutil import now
from app.db import get_db
from app.models.kv import Kv
from app.models.platform import Creator, CreatorAccount, CreatorAccountSnapshot, PlatformPost, PlatformPostComment, PlatformPostStat
from app.models.video_review import DouyinCreatorCredential, DouyinPostMetric
from app.services import douyin_dashboard as service
from app.services import douyin_creator_sync as sync_mod


@pytest.fixture()
def db():
    eng = fresh_engine()
    ensure_schema(eng)
    session = sessionmaker(bind=eng, autoflush=False, autocommit=False)()
    yield session
    session.close()


@pytest.fixture()
def client():
    eng = fresh_engine()
    ensure_schema(eng)
    session = sessionmaker(bind=eng, autoflush=False, autocommit=False)()

    def override_db():
        try:
            yield session
        finally:
            pass

    app = FastAPI()
    app.include_router(douyin_dashboard.router, prefix="/api/douyin-dashboard")
    app.dependency_overrides[get_db] = override_db
    with TestClient(app) as c:
        yield c, session
    session.close()


def _owner_account(db, *, with_credential: bool = True) -> tuple[Creator, CreatorAccount]:
    owner = Creator(kind="owner", name="作者", is_current=True)
    db.add(owner)
    db.flush()
    account = CreatorAccount(
        creator_id=owner.id,
        platform="douyin",
        nickname="作者抖音",
        platform_user_id="MS4w-test",
        enabled=True,
    )
    db.add(account)
    db.flush()
    if with_credential:
        db.add(
            DouyinCreatorCredential(
                account_id=account.id,
                cookie_value="test-cookie",
                enabled=True,
                status="valid",
            )
        )
    db.commit()
    return owner, account


def _post(db, account: CreatorAccount, platform_post_id: str = "1001", title: str = "作品A") -> PlatformPost:
    post = PlatformPost(
        account_id=account.id,
        platform="douyin",
        platform_post_id=platform_post_id,
        title=title,
        publish_time=now() - timedelta(days=3),
    )
    db.add(post)
    db.commit()
    return post


def _metric(db, post: PlatformPost, snapshot_date: str, **kwargs) -> DouyinPostMetric:
    row = db.query(DouyinPostMetric).filter_by(post_id=post.id, snapshot_date=snapshot_date).first()
    if row is None:
        row = DouyinPostMetric(post_id=post.id, snapshot_date=snapshot_date)
        db.add(row)
    for key, value in kwargs.items():
        setattr(row, key, value)
    db.commit()
    return row


def _stat(db, post: PlatformPost, stat_date: str, **kwargs) -> PlatformPostStat:
    row = db.query(PlatformPostStat).filter_by(post_id=post.id, stat_date=stat_date).first()
    if row is None:
        row = PlatformPostStat(post_id=post.id, stat_date=stat_date)
        db.add(row)
    for key, value in kwargs.items():
        setattr(row, key, value)
    db.commit()
    return row


# ---------- 状态映射 ----------


def test_post_status_mapping(db):
    _, account = _owner_account(db)
    post = _post(db, account)
    row = _metric(db, post, "2026-11-01")

    row.raw = '{"item": {"review": {"status": 2}, "visibility": {"status": 1}}}'
    assert service.post_status(row) == ("approved", "通过")

    row.raw = '{"item": {"review": {"status": 4, "details": [{"text": "不适宜公开"}]}, "visibility": {"status": 3}}}'
    assert service.post_status(row) == ("private", "私密")

    row.raw = '{"item": {"review": {"status": 4}, "visibility": {"status": 1}}}'
    assert service.post_status(row) == ("rejected", "不适宜公开")

    row.raw = '{"item": {"visibility": {"status": 1}}}'
    assert service.post_status(row) == ("published", "已发布")

    row.raw = '{"item": {}}'
    assert service.post_status(row) == ("unknown", "状态未知")

    assert service.post_status(None) == ("unknown", "—")


def test_apply_item_metrics_keeps_review_visibility(db):
    """详情刷新（overview 不带 review/visibility）不能把列表状态刷没。"""
    _, account = _owner_account(db)
    post = _post(db, account)
    sync_mod._apply_item_metrics(db, post, {"metrics": {"view_count": "100", "like_count": "5"}})
    row = db.query(DouyinPostMetric).filter_by(post_id=post.id).first()
    assert row is not None
    row.raw = '{"item": {"review": {"status": 2}, "visibility": {"status": 1}, "metrics": {"view_count": "100"}}}'
    db.commit()

    sync_mod._apply_item_metrics(db, post, {"metrics": {"view_count": "120"}})
    db.refresh(row)
    payload = service._loads(row.raw, {})
    assert payload["item"]["review"]["status"] == 2
    assert payload["item"]["visibility"]["status"] == 1


# ---------- 账号诊断归一化 ----------


def test_normalize_diagnosis():
    diagnosis = service.normalize_diagnosis(
        {
            "data": {
                "code": 0,
                "data": {
                    "PlayCnt": {"OwnValue": 88474, "SimilarValue": 32470, "AuthorRank": 0.6604, "SimilarCount": 17367},
                    "NewFans": {"OwnValue": -63, "SimilarValue": 128, "AuthorRank": 0.0, "SimilarCount": 17367},
                    "PlayFinishRatio": {"OwnValue": 0.1316, "SimilarValue": 0.1094, "AuthorRank": 0.5975},
                },
            }
        }
    )
    assert diagnosis is not None
    assert diagnosis["metrics"]["plays"]["own"] == 88474
    assert diagnosis["metrics"]["plays"]["similar"] == 32470
    assert diagnosis["metrics"]["plays"]["rank"] == pytest.approx(0.6604)
    assert diagnosis["metrics"]["new_fans"]["own"] == -63
    assert diagnosis["metrics"]["finish_rate"]["own"] == pytest.approx(0.1316)



# ---------- 账号 7 日 KPI 与逐日趋势 ----------


def test_account_kpis_and_trend(db):
    _, account = _owner_account(db)
    post = _post(db, account)
    today = now().date()
    # 当前 7 日：逐日递增；前一 7 日也有关键两天用于「较前 7 日」
    plays = [100, 120, 140, 160, 180, 200, 210]
    for offset, value in enumerate(plays):
        day = (today - timedelta(days=6 - offset)).isoformat()
        _stat(db, post, day, plays=value, likes=value // 10, comments=value // 100, shares=value // 50)
    prev_plays = [50, 90]
    for offset, value in enumerate(prev_plays):
        day = (today - timedelta(days=13 - offset)).isoformat()
        _stat(db, post, day, plays=value, likes=value // 10, comments=0, shares=0)
    # 主页访问量只在创作者指标表里
    _metric(db, post, (today - timedelta(days=6)).isoformat(), profile_visits=10)
    _metric(db, post, today.isoformat(), profile_visits=35)

    snapshot = service.account_kpis(db, account.id, days=7, today=today)
    fields = snapshot["fields"]
    assert snapshot["period"]["days"] == 7
    assert fields["likes"]["value"] == 210 // 10 - 100 // 10
    assert fields["likes"]["covered"] == 1
    # 前 7 日也有两天快照（likes 5→9），所以能算出对比：11 - 4 = 7
    assert fields["likes"]["delta"] == 7
    assert fields["homepage_visits"]["value"] == 25
    assert fields["comments"]["value"] == 1  # plays//100: 1→2
    series = snapshot["series"]["plays"]
    assert series["mode"] == "daily"
    assert len(series["points"]) == 7
    # 今天新增 = 210 - 200 = 10
    assert series["points"][-1]["value"] == 10
    # 第一天没有前一天快照 → 空缺不补 0
    assert series["points"][0]["value"] is None


def test_account_kpis_prev_delta_and_coverage(db):
    _, account = _owner_account(db)
    post = _post(db, account)
    today = now().date()
    for offset in range(7):
        day = (today - timedelta(days=6 - offset)).isoformat()
        _stat(db, post, day, likes=offset * 10, plays=100 + offset)
    for offset, likes in enumerate((3, 5)):
        day = (today - timedelta(days=13 - offset)).isoformat()
        _stat(db, post, day, likes=likes, plays=50 + offset)
    snapshot = service.account_kpis(db, account.id, days=7, today=today)
    likes = snapshot["fields"]["likes"]
    assert likes["prev"] == 2  # 5 - 3
    assert likes["delta"] == likes["value"] - 2

    # 没有前 7 日数据时返回 None（不显示假对比）
    empty = service.account_kpis(db, account.id, days=7, today=today - timedelta(days=30))
    assert empty["fields"]["likes"]["value"] is None
    assert empty["fields"]["likes"]["delta"] is None


# ---------- 观众画像映射 ----------


def test_audience_sections_mapping(db):
    _, account = _owner_account(db)
    post = _post(db, account)
    row = _metric(db, post, "2026-11-01")
    row.audience_portrait = service._json(
        {
            "active": [
                {"key": "2", "value": 0.0178},
                {"key": "3", "value": 0.1075},
                {"key": "4", "value": 0.8347},
                {"key": "-1", "value": 0.0369},
                {"key": "1", "value": 0.0031},
            ],
            "gender": {"ratio_list": [{"key": "male", "value": 0.9616}, {"key": "female", "value": 0.0384}]},
            "age": {"ratio_list": [{"key": "18-23", "value": 0.42}, {"key": "-18", "value": 0.02}]},
            "province": {"ratio_list": [{"key": "广东", "value": 0.2462}, {"key": "浙江", "value": 0.0943}]},
            "city_level": {"ratio_list": [{"key": "新一线", "value": 0.3}]},
        }
    )
    row.audience_others = service._json(
        {
            "audience_preference": {
                "total_data": {
                    "ratio_data": [
                        {"key": "随拍", "value": 0.25},
                        {"key": "游戏", "value": 0.1667},
                        {"key": "未分类（投稿数不足）", "value": 0.5},
                    ]
                }
            },
            "audience_search_most_keywords": [
                {"keywords": "今日金价", "query_cnt_7d": "20382486"},
                {"keywords": "助眠", "query_cnt_7d": "6084602"},
            ],
        }
    )
    db.commit()
    values = service._overview_values(row, None)
    sections = service._audience_sections(row, db, post.id, values)

    assert [item["label"] for item in sections["active"]] == ["未知", "低活", "轻度", "中度", "重度"]
    assert sections["active"][-1]["ratio"] == pytest.approx(0.8347)
    assert sections["gender"][0] == {"key": "male", "label": "男性", "ratio": pytest.approx(0.9616)}
    assert [item["key"] for item in sections["age"]] == ["-18", "18-23"]
    assert sections["provinces"][0]["name"] == "广东"
    assert sections["interests"] == [{"name": "随拍", "ratio": 0.25}, {"name": "游戏", "ratio": pytest.approx(0.1667)}]
    assert sections["keywords"][0] == {"word": "今日金价", "heat": 20382486}


# ---------- 评论热词 ----------


def test_comment_hot_words():
    comments = [
        "这油价太高了，还是骑电驴吧",
        "油价涨了，电驴真的香",
        "存款最重要，油价贵就少开车",
        "点赞支持",
    ]
    result = service.comment_hot_words(comments)
    assert result["total_comments"] == 4
    words = {item["word"]: item["count"] for item in result["items"]}
    assert words.get("油价") == 3
    assert words.get("电驴") == 2
    assert "还是" not in words
    assert result["items"][0]["ratio"] == pytest.approx(0.75)
    # 确定性：同输入同输出
    assert service.comment_hot_words(comments) == result


def test_comment_hot_words_too_few():
    result = service.comment_hot_words(["好", "不错"])
    assert result["items"] == []
    assert result["total_comments"] == 2
    assert "评论太少" in result["note"]


# ---------- 接口冒烟（mock 模式） ----------


def test_api_overview_empty_state(client):
    http, _ = client
    resp = http.get("/api/douyin-dashboard/overview")
    assert resp.status_code == 200
    body = resp.json()
    assert body["account"] is None
    assert "主博主" in body["blocked_reason"]
    assert body["needs_refresh"] is True

    works = http.get("/api/douyin-dashboard/works")
    assert works.status_code == 400


def test_api_works_and_detail(client):
    http, db = client
    _, account = _owner_account(db)
    post = _post(db, account)
    _stat(db, post, "2026-11-01", plays=13700, likes=330, comments=26, shares=35, favorites=52)
    row = _metric(
        db,
        post,
        "2026-11-01",
        captured_at=now(),
        follower_gain=14,
        profile_visits=80,
        trend_reliable=True,
    )
    row.raw = service._json(
        {
            "item": {
                "review": {"status": 2},
                "visibility": {"status": 1},
                "video_info": {"duration": "85774"},
                "metrics": {
                    "view_count": "13700",
                    "like_count": "330",
                    "comment_count": "26",
                    "share_count": "35",
                    "favorite_count": "52",
                    "danmaku_count": "0",
                    "completion_rate": "0.075",
                    "bounce_rate_2s": "0.3089",
                    "subscribe_count": "14",
                    "unsubscribe_count": "38",
                    "fan_view_proportion": "0.686",
                    "avg_view_proportion": "0.1888",
                    "favorite_rate": "0.0038",
                },
            }
        }
    )
    db.add(PlatformPostComment(post_id=post.id, platform="douyin", text="这油价太高了", likes=3, user_nick="网友A"))
    db.commit()

    works = http.get("/api/douyin-dashboard/works?limit=10")
    assert works.status_code == 200
    body = works.json()
    assert body["total"] == 1
    assert body["items"][0]["status_label"] == "通过"
    assert body["items"][0]["plays"] == 13700

    detail = http.get(f"/api/douyin-dashboard/works/{post.id}")
    assert detail.status_code == 200
    data = detail.json()
    assert data["overview"]["plays"] == 13700
    assert data["overview"]["finish_rate"] == pytest.approx(0.075)
    assert data["overview"]["avg_view_proportion"] == pytest.approx(0.1888)
    assert data["post"]["video_url"] == f"https://www.douyin.com/video/{post.platform_post_id}"
    assert data["fans"]["follower_gain"] == 14
    assert data["audience"]["cards"][0]["label"] == "涨粉量"
    assert data["comments"]["total"] == 1
    assert data["play_trend"]["available"] is False  # 只有一天快照
    assert data["stale"] is False  # captured_at 是刚刚

    missing = http.get("/api/douyin-dashboard/works/9999")
    assert missing.status_code == 404


def test_api_refresh_requires_creator_data(client):
    http, db = client
    _owner_account(db, with_credential=False)
    resp = http.post("/api/douyin-dashboard/overview/refresh")
    assert resp.status_code == 400
    assert "创作者数据" in resp.json()["detail"]


def test_api_refresh_budget_guard(client):
    http, db = client
    _, account = _owner_account(db)
    post = _post(db, account)
    db.add(Kv(key="tikhub_budget_limit", value="1"))
    db.add(Kv(key=f"tikhub_budget_used:{now().date().isoformat()}", value="1"))
    db.commit()
    resp = http.post("/api/douyin-dashboard/overview/refresh")
    assert resp.status_code == 400
    assert "额度不足" in resp.json()["detail"]

    resp = http.post(f"/api/douyin-dashboard/works/{post.id}/refresh")
    assert resp.status_code == 400
    assert "额度不足" in resp.json()["detail"]


def test_api_refresh_post_skipped_within_ttl(client):
    http, db = client
    _, account = _owner_account(db)
    post = _post(db, account)
    _metric(db, post, "2026-11-01", captured_at=now())
    resp = http.post(f"/api/douyin-dashboard/works/{post.id}/refresh", json={"force": False})
    assert resp.status_code == 200
    body = resp.json()
    assert body["skipped"] is True
    assert "最新" in body["reason"]


# ---------- 刷新任务（mock 模式） ----------


def test_overview_worker_mock_and_cache(db):
    _, account = _owner_account(db)
    post = _post(db, account)
    _stat(db, post, now().date().isoformat(), plays=100)

    def update(pct, note):
        return None

    result = service.overview_worker(db, {"account_id": account.id}, update)
    assert result["ok"] is True
    body = service.overview(db)
    assert body["diagnosis"]["available"] is True
    assert body["diagnosis"]["plays"]["own"] == 88474
    assert body["needs_refresh"] is False
    assert body["account"]["id"] == account.id


def test_post_worker_mock_and_detail_audience(db):
    _, account = _owner_account(db)
    post = _post(db, account)

    def update(pct, note):
        return None

    result = service.post_worker(db, {"account_id": account.id, "post_id": post.id}, update)
    assert result["ok"] is True
    detail = service.post_detail(db, post.id)
    assert detail["overview"]["plays"] is not None
    # v33：只拉核心指标 + 评论；流量来源/观看趋势/观众画像/受众兴趣不再请求（对应 tab 已移除）
    assert detail["audience"]["gender"] == []
    assert detail["flow"]["sources"] == []
    assert detail["comment_words"]["total_comments"] >= 0


def test_account_kpis_ignores_zero_snapshot(db):
    """历史「同步失败写 0」的快照不能当基线，否则产生几十万级假增量。"""
    _, account = _owner_account(db)
    post = _post(db, account)
    today = now().date()
    _stat(db, post, (today - timedelta(days=3)).isoformat(), plays=0, likes=0, comments=0, shares=0)
    _metric(db, post, (today - timedelta(days=3)).isoformat(), profile_visits=0)
    _stat(db, post, (today - timedelta(days=2)).isoformat(), plays=1000, likes=100, comments=10, shares=5)
    _metric(db, post, (today - timedelta(days=2)).isoformat(), profile_visits=70)
    _stat(db, post, (today - timedelta(days=1)).isoformat(), plays=1200, likes=120, comments=11, shares=7)
    _metric(db, post, (today - timedelta(days=1)).isoformat(), profile_visits=80)
    _stat(db, post, today.isoformat(), plays=1500, likes=150, comments=12, shares=8)
    _metric(db, post, today.isoformat(), profile_visits=95)
    db.commit()

    snapshot = service.account_kpis(db, account.id, days=7, today=today)
    assert snapshot["fields"]["likes"]["value"] == 50  # 150 - 100，不是 150 - 0
    assert snapshot["fields"]["homepage_visits"]["value"] == 25  # 95 - 70，不是 95
    # 逐日新增只从两条有效快照开始算：day-2→day-1 = 200，day-1→today = 300；1000-0 的假增量不出现
    values = [point["value"] for point in snapshot["series"]["plays"]["points"] if point["value"] is not None]
    assert values == [200, 300]


def test_play_trend_ignores_public_zero_plays(db):
    """公开同步的 plays=0 是缺数（抖音 app/v3 不返回播放数），不能算成一天新增几十万。"""
    _, account = _owner_account(db)
    post = _post(db, account)
    today = now().date()
    _stat(db, post, (today - timedelta(days=2)).isoformat(), plays=0, likes=4620, comments=17, shares=44)
    _stat(db, post, (today - timedelta(days=1)).isoformat(), plays=170573, likes=4620, comments=17, shares=44)
    _stat(db, post, today.isoformat(), plays=170600, likes=4630, comments=18, shares=45)
    db.commit()

    trend = service._play_trend(db, post.id)
    values = [point["added"] for point in trend["points"] if point["added"] is not None]
    assert 170573 not in values  # 0 → 170573 不算一天新增 17 万
    assert values == [27]  # 有效基线从 10-30 的 170573 开始，today 新增 27
    detail = service.post_detail(db, post.id)
    assert detail["play_trend"]["available"] is True


def test_overview_fans_kpis_and_series(db):
    """粉丝数据合并进指标卡：净增粉丝与播放指标同一行（总粉丝量卡已按 v9 移除）；粉丝曲线来自账号每日快照。"""
    _, account = _owner_account(db)
    today = now().date()
    for offset, followers in enumerate((59076, 59063)):
        db.add(
            CreatorAccountSnapshot(
                account_id=account.id,
                snapshot_date=(today - timedelta(days=1 - offset)).isoformat(),
                followers=followers,
            )
        )
    db.commit()

    def update(pct, note):
        return None

    service.overview_worker(db, {"account_id": account.id}, update)
    body = service.overview(db)
    cards = {card["key"]: card for card in body["kpis"]}
    assert [card["key"] for card in body["kpis"]] == [
        "plays",
        "homepage_visits",
        "likes",
        "shares",
        "comments",
        "net_fans",
    ]
    assert "total_fans" not in cards
    assert cards["net_fans"]["value"] == -63  # 7 日周期用账号诊断
    # 净增粉丝曲线仍来自账号每日粉丝快照
    net_series = body["series"]["net_fans"]
    assert net_series["points"][-1]["value"] == -13  # 59063 - 59076


def test_overview_period_and_metric_series(db):
    """统计周期 7/14/30/90 天：KPI 窗口、较前周期与各指标逐日曲线。"""
    _, account = _owner_account(db)
    post = _post(db, account)
    today = now().date()
    for offset in range(30):
        day = (today - timedelta(days=29 - offset)).isoformat()
        _stat(db, post, day, plays=100 + offset * 10, likes=10 + offset, comments=offset, shares=offset)
    db.commit()

    for days in (7, 14, 30):
        snapshot = service.account_kpis(db, account.id, days=days, today=today)
        assert snapshot["period"]["days"] == days
        assert len(snapshot["series"]["plays"]["points"]) == days
        # 每个指标都有独立曲线
        for key in ("plays", "homepage_visits", "likes", "shares", "comments", "net_fans"):
            assert key in snapshot["series"]
        assert "total_fans" not in snapshot["series"]

    body = service.overview(db, 30)
    assert body["period"]["days"] == 30
    cards = {card["key"]: card for card in body["kpis"]}
    # 30 日周期没有账号诊断口径 → 播放量用本地快照
    assert cards["plays"]["source"] == "snapshot"
    with pytest.raises(ValueError):
        service.overview(db, 5)


def test_trend_uses_last_available_snapshot(db):
    """作者确认口径：今天抓的 - 上一次可用快照（昨天没抓就用最近一日），该点含间隔累计。"""
    _, account = _owner_account(db)
    post = _post(db, account)
    today = now().date()
    # 窗口内有 day-3、day-1、今天，day-2 没抓
    _stat(db, post, (today - timedelta(days=3)).isoformat(), plays=100, likes=10, comments=1, shares=1)
    _stat(db, post, (today - timedelta(days=1)).isoformat(), plays=250, likes=25, comments=2, shares=2)
    _stat(db, post, today.isoformat(), plays=300, likes=30, comments=3, shares=3)
    db.add_all(
        [
            CreatorAccountSnapshot(account_id=account.id, snapshot_date=(today - timedelta(days=3)).isoformat(), followers=1000),
            CreatorAccountSnapshot(account_id=account.id, snapshot_date=(today - timedelta(days=1)).isoformat(), followers=1060),
            CreatorAccountSnapshot(account_id=account.id, snapshot_date=today.isoformat(), followers=1075),
        ]
    )
    db.commit()

    snapshot = service.account_kpis(db, account.id, days=7, today=today)
    points = {point["date"]: point["value"] for point in snapshot["series"]["plays"]["points"]}
    assert points[(today - timedelta(days=1)).isoformat()] == 150  # 250 - 100（含 day-2 间隔）
    assert points[today.isoformat()] == 50  # 300 - 250
    fan_points = {point["date"]: point["value"] for point in snapshot["series"]["net_fans"]["points"]}
    assert fan_points[(today - timedelta(days=1)).isoformat()] == 60  # 1060 - 1000
    assert fan_points[today.isoformat()] == 15  # 1075 - 1060
