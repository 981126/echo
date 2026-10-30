"""R-239：账号级创作者 Cookie、数据源策略、失效停采、防覆盖与素材库播放展示。"""

from __future__ import annotations

import sys
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest
from conftest import ensure_schema, fresh_engine
from cryptography.fernet import Fernet
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from app.api import creators
from app.config import get_settings
from app.core.timeutil import now
from app.db import get_db
from app.models.platform import Creator, CreatorAccount, PlatformPost, PlatformPostStat
from app.models.video import Video
from app.models.video_review import DouyinCreatorCredential
from app.services import douyin_creator_sync as sync_mod
from app.services import platform_sync
from app.services.douyin_account_policy import (
    SOURCE_BLOCKED,
    SOURCE_CREATOR,
    SOURCE_PUBLIC,
    credential_summary,
    mark_invalid,
    resolve_data_policy,
)
from app.services.douyin_creator_sync import (
    CredentialError,
    backfill_account_creator_data,
    backfill_done,
    creator_stats_for_post,
    encrypt_cookie,
    sync_account_creator_data,
)
from app.services.library_service import _slim_post
from app.services.platform.tikhub import TikHubBusinessError


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
    app.include_router(creators.router, prefix="/api/creators")
    app.dependency_overrides[get_db] = override_db
    with TestClient(app) as c:
        yield c, session
    session.close()


def _owner_account(db, platform: str = "douyin") -> tuple[Creator, CreatorAccount]:
    owner = Creator(kind="owner", name="作者", is_current=True)
    db.add(owner)
    db.flush()
    account = CreatorAccount(
        creator_id=owner.id,
        platform=platform,
        nickname="作者抖音",
        platform_user_id="MS4w-test",
        enabled=True,
    )
    db.add(account)
    db.commit()
    return owner, account


def _credential(db, account, *, status: str = "valid", enabled: bool = True, cookie: str = "sessionid=fake") -> DouyinCreatorCredential:
    row = DouyinCreatorCredential(
        account_id=account.id,
        cookie_value=encrypt_cookie(cookie),
        enabled=enabled,
        status=status,
    )
    db.add(row)
    db.commit()
    return row


def _post(db, account, platform_post_id: str = "post-1", *, days_ago: int = 1) -> PlatformPost:
    post = PlatformPost(
        account_id=account.id,
        platform=account.platform,
        platform_post_id=platform_post_id,
        title="测试作品",
        publish_time=now() - timedelta(days=days_ago),
        raw="{}",
    )
    db.add(post)
    db.commit()
    return post


@pytest.fixture(autouse=True)
def _cookie_key(monkeypatch):
    monkeypatch.setattr(get_settings(), "douyin_cookie_key", Fernet.generate_key().decode())


def test_policy_matrix(db):
    _, douyin = _owner_account(db)
    _, bili = _owner_account(db, "bilibili")
    # 未配置 → 公开
    assert resolve_data_policy(db, douyin).source == SOURCE_PUBLIC
    assert credential_summary(db, douyin)["status"] == "missing"
    # 有效 + 开启 → creator
    _credential(db, douyin, status="valid", enabled=True)
    policy = resolve_data_policy(db, douyin)
    assert policy.source == SOURCE_CREATOR and policy.status == "valid"
    # 关闭开关 → public
    row = db.query(DouyinCreatorCredential).filter_by(account_id=douyin.id).one()
    row.enabled = False
    db.commit()
    assert resolve_data_policy(db, douyin).source == SOURCE_PUBLIC
    assert credential_summary(db, douyin)["status"] == "disabled"
    # 开启但失效 → blocked
    row.enabled = True
    row.status = "invalid"
    row.last_error = "过期"
    db.commit()
    policy = resolve_data_policy(db, douyin)
    assert policy.source == SOURCE_BLOCKED and "失效" in policy.reason
    # B 站恒 public
    assert resolve_data_policy(db, bili).source == SOURCE_PUBLIC
    assert credential_summary(db, bili) is None


def test_credential_api_flow(client, monkeypatch):
    c, db = client
    _, douyin = _owner_account(db)
    _, bili = _owner_account(db, "bilibili")
    # 保存并验证（测试环境 mock 模式，不发真实请求）
    r = c.put(f"/api/creators/accounts/{douyin.id}/douyin-credential", json={"cookie": "sessionid=abc; ttwid=1", "enabled": True})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "valid" and body["has_cookie"] is True and body["enabled"] is True
    # 不回显 Cookie
    assert "sessionid" not in r.text
    # 仅关闭开关
    r = c.put(f"/api/creators/accounts/{douyin.id}/douyin-credential", json={"enabled": False})
    assert r.status_code == 200 and r.json()["status"] == "disabled"
    # 重新开启（已有 Cookie）
    r = c.put(f"/api/creators/accounts/{douyin.id}/douyin-credential", json={"enabled": True})
    assert r.status_code == 200 and r.json()["status"] == "valid"
    # 非抖音账号不支持
    r = c.put(f"/api/creators/accounts/{bili.id}/douyin-credential", json={"cookie": "x"})
    assert r.status_code == 400
    # 不存在
    assert c.get("/api/creators/accounts/99999/douyin-credential").status_code == 404
    # 空请求
    r = c.put(f"/api/creators/accounts/{douyin.id}/douyin-credential", json={})
    assert r.status_code == 400


def test_account_patch_keeps_extra_config(client):
    c, db = client
    _, account = _owner_account(db)
    account.extra_config = '{"review_homepage": {"bio": "保留我"}}'
    db.commit()
    r = c.patch(f"/api/creators/accounts/{account.id}", json={
        "platform": "douyin",
        "nickname": "新昵称",
        "home_link": "",
        "platform_user_id": "",
        "extra_config": {},
        "enabled": True,
        "sync_frequency": "daily",
    })
    assert r.status_code == 200, r.text
    db.refresh(account)
    assert "review_homepage" in account.extra_config


def test_write_stat_source_priority_merge(db):
    _, account = _owner_account(db)
    post = _post(db, account)
    platform_sync._write_stat(db, post, {"plays": 3587, "likes": 46, "comments": 3, "favorites": 2, "shares": 0, "source": "tikhub_creator"})
    # 公开接口的 0 不得覆盖真实播放；其他真实字段照常更新
    platform_sync._write_stat(db, post, {"plays": 0, "likes": 50, "comments": 4, "favorites": 0, "shares": 0, "source": "tikhub"})
    stat = db.query(PlatformPostStat).filter_by(post_id=post.id).one()
    assert stat.plays == 3587
    assert stat.source == "tikhub_creator"
    assert stat.likes == 50
    # 创作者真实 0 可以覆盖公开的非 0
    platform_sync._write_stat(db, post, {"plays": 0, "likes": 46, "source": "tikhub_creator"})
    db.refresh(stat)
    assert stat.plays == 0
    # 缺失字段不覆盖（fetch_video_statistics 没有收藏）
    before_favorites = stat.favorites
    platform_sync._write_stat(db, post, {"plays": 120, "source": "tikhub_statistics"})
    db.refresh(stat)
    assert stat.plays == 120
    assert stat.favorites == before_favorites


def test_blocked_account_skips_all_third_party_calls(db, monkeypatch):
    _, account = _owner_account(db)
    _credential(db, account, status="invalid", enabled=True)
    post = _post(db, account)
    video = Video(filename="r239.mp4", title="素材", creator_id=account.creator_id, status="published")
    db.add(video)
    db.commit()
    post.local_video_id = video.id
    db.commit()
    calls = {"n": 0}

    def boom(*args, **kwargs):
        calls["n"] += 1
        raise AssertionError("blocked account must not call third-party APIs")

    monkeypatch.setattr(platform_sync, "make_source", boom)
    monkeypatch.setattr(sync_mod, "make_client", boom)
    result = platform_sync.sync_account(db, account, scope="daily", top_n=5)
    assert result["skipped"] == "cookie_invalid"
    with pytest.raises(CredentialError):
        platform_sync.sync_local_video_metrics(db, video)
    with pytest.raises(CredentialError):
        sync_account_creator_data(db, account)
    assert calls["n"] == 0


class _FakeCreatorClient:
    mode = "real"

    def __init__(self, pages):
        self.pages = pages
        self.requests_used = 0

    def fetch_douyin_creator_item_list(self, **kwargs):
        self.requests_used += 1
        return self.pages[min(self.requests_used - 1, len(self.pages) - 1)]

    def fetch_profile(self, platform, user_id, account=None):
        from app.services.platform.base import ProfileData

        return ProfileData(nickname="作者抖音")

    def fetch_comments(self, *args, **kwargs):
        return []

    def fetch_post_stats(self, *args, **kwargs):
        return {}


def _item(item_id: str, view: int) -> dict:
    return {
        "id": item_id,
        "description": "面试技巧 #面试",
        "create_time": str(int(now().timestamp()) - 3600),
        "cover": {"url_list": ["https://example.com/cover.jpg"]},
        "video_info": {"duration": "60000"},
        "metrics": {
            "view_count": str(view),
            "like_count": "46",
            "comment_count": "3",
            "favorite_count": "2",
            "share_count": "0",
            "bounce_rate_2s": "0.42",
            "completion_rate_5s": "0.29",
            "completion_rate": "0.02",
            "avg_view_second": "10.5",
            "homepage_visit_count": "148",
            "subscribe_count": "2",
        },
    }


def test_creator_mode_sync_account_and_provenance(db, monkeypatch):
    _, account = _owner_account(db)
    _credential(db, account, status="valid", enabled=True)
    fake = _FakeCreatorClient([{"data": {"items": [_item("post-1", 3587)], "has_more": False}}])
    monkeypatch.setattr(sync_mod, "make_client", lambda *a, **k: fake)
    import app.services.platform.tikhub as tikhub_mod

    monkeypatch.setattr(tikhub_mod, "make_client", lambda *a, **k: fake)
    result = platform_sync.sync_account(db, account, scope="daily", top_n=15)
    assert result["posts"] == 1
    post = db.query(PlatformPost).filter_by(platform_post_id="post-1").one()
    stat = db.query(PlatformPostStat).filter_by(post_id=post.id).one()
    assert stat.plays == 3587 and stat.source == "tikhub_creator"
    slim = _slim_post(post, stat)
    assert slim["latest_stat"]["plays_known"] is True
    assert slim["latest_stat"]["plays_source"] == "tikhub_creator"


def test_iter_pagination_and_backfill(db, monkeypatch):
    _, account = _owner_account(db)
    _credential(db, account, status="valid", enabled=True)
    for index in range(2):
        db.add(
            PlatformPost(
                account_id=account.id,
                platform="douyin",
                platform_post_id=f"p{index}",
                title=f"作品 {index}",
                publish_time=now() - timedelta(days=1 + index),
                raw="{}",
            )
        )
    db.commit()
    page1 = {"data": {"items": [_item("p0", 100)], "has_more": True, "max_cursor": "1000"}}
    page2 = {"data": {"items": [_item("p1", 200)], "has_more": False}}
    fake = _FakeCreatorClient([page1, page2])
    monkeypatch.setattr(sync_mod, "make_client", lambda *a, **k: fake)
    result = backfill_account_creator_data(db, account, max_requests=5)
    assert result["complete"] is True
    assert backfill_done(db, account.id) is True
    assert db.query(PlatformPostStat).filter(PlatformPostStat.plays.in_([100, 200])).count() == 2, result


def test_creator_stats_for_post_and_public_provenance(db, monkeypatch):
    _, account = _owner_account(db)
    _credential(db, account, status="valid", enabled=True)
    post = _post(db, account, "post-x")
    fake = _FakeCreatorClient([])

    def overview(**kwargs):
        fake.requests_used += 1
        return {"data": {"items": [_item("post-x", 888)], "status_code": 0}}

    fake.fetch_douyin_creator_overview = overview  # type: ignore[attr-defined]
    monkeypatch.setattr(sync_mod, "make_client", lambda *a, **k: fake)
    stats = creator_stats_for_post(db, account, post)
    assert stats["plays"] == 888 and stats["source"] == "tikhub_creator"
    stat = db.query(PlatformPostStat).filter_by(post_id=post.id).one()
    assert stat.plays == 888 and stat.source == "tikhub_creator"
    assert _slim_post(post, stat)["latest_stat"]["plays_known"] is True
    # 公开来源播放不可信
    stat.source = "tikhub"
    db.commit()
    assert _slim_post(post, stat)["latest_stat"]["plays_known"] is False


def test_mark_invalid_notifies_once(db, monkeypatch):
    _, account = _owner_account(db)
    _credential(db, account, status="valid", enabled=True)
    monkeypatch.setattr(get_settings(), "douyin_cookie_key", get_settings().douyin_cookie_key)
    assert mark_invalid(db, account, "用户未登录", notify=True) is True
    assert mark_invalid(db, account, "用户未登录", notify=True) is False


def test_business_error_marks_invalid_on_sync(db, monkeypatch):
    _, account = _owner_account(db)
    _credential(db, account, status="valid", enabled=True)

    class _AuthFail:
        mode = "real"
        requests_used = 0

        def fetch_douyin_creator_item_list(self, **kwargs):
            raise TikHubBusinessError("业务错误 8：用户未登录", code=8)

    monkeypatch.setattr(sync_mod, "make_client", lambda *a, **k: _AuthFail())
    with pytest.raises(CredentialError):
        sync_account_creator_data(db, account)
    row = db.query(DouyinCreatorCredential).filter_by(account_id=account.id).one()
    assert row.status == "invalid"
