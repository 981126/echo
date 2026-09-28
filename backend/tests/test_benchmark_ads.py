"""R-103 对标广告过滤测试：candidates 排除广告/同款 + 转写补齐时自动判广并顺延（mock 离线）。"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import Base
from app.models.platform import Creator, CreatorAccount, PlatformPost
from app.models.video import Transcript, Video
from app.services.benchmark import candidates, ensure_top_with_text


@pytest.fixture()
def db(tmp_path):
    eng = create_engine(f"sqlite:///{tmp_path}/t.db", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=eng)
    session = sessionmaker(bind=eng, autoflush=False, autocommit=False)()
    yield session
    session.close()
    eng.dispose()


def _seed(db, posts):
    owner = Creator(kind="owner", name="我", is_current=True)
    db.add(owner)
    db.commit()
    bm = Creator(kind="benchmark", parent_id=owner.id, name="对标A")
    db.add(bm)
    db.commit()
    acc = CreatorAccount(creator_id=bm.id, platform="douyin", nickname="对标号", enabled=True)
    db.add(acc)
    db.commit()
    base = datetime(2026, 9, 1, 12, 0, 0)
    for i, (pid, title, is_ad) in enumerate(posts):
        db.add(
            PlatformPost(
                account_id=acc.id,
                platform="douyin",
                platform_post_id=pid,
                title=title,
                publish_time=base - timedelta(hours=i),
                is_ad=is_ad,
            )
        )
    db.commit()
    return bm


def test_candidates_exclude_ad_and_same_title_twin(db):
    bm = _seed(
        db,
        [
            ("n1", "职场干货：如何谈薪", False),
            ("adv", "某品牌手机体验评测", True),
            ("twin", "某品牌手机体验评测", False),  # 同款跨平台漏标，按标题一并排除（R-100）
            ("n2", "简历这样写更稳", False),
        ],
    )
    got = candidates(db, bm, limit=10)
    titles = [u["post"].platform_post_id for u in got]
    assert "adv" not in titles and "twin" not in titles
    assert "n1" in titles and "n2" in titles


def test_ensure_top_skips_ad_and_flags(db, monkeypatch):
    bm = _seed(
        db,
        [
            ("adv1", "广告帖一", False),
            ("n1", "正常帖一", False),
            ("adv2", "广告帖二", False),
            ("n2", "正常帖二", False),
            ("n3", "正常帖三", False),
            ("n4", "正常帖四", False),
        ],
    )
    monkeypatch.setattr("app.services.benchmark._unit_text", lambda db, unit: "有转写文案内容")
    monkeypatch.setattr(
        "app.services.benchmark._unit_is_ad",
        lambda db, unit, text="": unit["post"].platform_post_id in ("adv1", "adv2"),
    )
    picked = ensure_top_with_text(db, bm, limit_candidates=10)
    picked_ids = [u["post"].platform_post_id for u in picked]
    assert len(picked) == 4  # R-174：前3+最新 = 4 条（广告顺延）
    assert "adv1" not in picked_ids and "adv2" not in picked_ids
    # 广告帖被落库标记，之后 candidates 直接排除
    flags = {r.platform_post_id: r.is_ad for r in db.query(PlatformPost).all()}
    assert flags["adv1"] is True and flags["adv2"] is True
    assert flags["n1"] is False


def test_candidates_exclude_post_bound_to_ad_video(db):
    owner = Creator(kind="owner", name="我", is_current=True)
    db.add(owner)
    db.commit()
    bm = Creator(kind="benchmark", parent_id=owner.id, name="对标A")
    db.add(bm)
    db.commit()
    acc = CreatorAccount(creator_id=bm.id, platform="douyin", nickname="号", enabled=True)
    db.add(acc)
    db.commit()
    v = Video(filename="ad_bound.mp4", creator_id=owner.id, is_ad=True)
    db.add(v)
    db.flush()
    base = datetime(2026, 9, 1, 12, 0, 0)
    db.add(
        PlatformPost(
            account_id=acc.id, platform="douyin", platform_post_id="pa",
            title="软广帖", publish_time=base, is_ad=False, local_video_id=v.id,
        )
    )
    db.add(
        PlatformPost(
            account_id=acc.id, platform="douyin", platform_post_id="pb",
            title="正常帖", publish_time=base - timedelta(hours=1),
        )
    )
    db.commit()
    got = candidates(db, bm, limit=10)
    ids = [u["post"].platform_post_id for u in got]
    assert "pa" not in ids and "pb" in ids


def test_top_orders_with_text_first(db):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.api import benchmark as benchmark_api
    from app.db import get_db
    from app.models.platform import PlatformPostStat

    owner = Creator(kind="owner", name="我", is_current=True)
    db.add(owner)
    db.commit()
    bm = Creator(kind="benchmark", parent_id=owner.id, name="对标A")
    db.add(bm)
    db.commit()
    acc = CreatorAccount(creator_id=bm.id, platform="douyin", nickname="号", enabled=True)
    db.add(acc)
    db.commit()
    base = datetime(2026, 9, 1, 12, 0, 0)
    p_high = PlatformPost(
        account_id=acc.id, platform="douyin", platform_post_id="high",
        title="分数高但没文案", publish_time=base,
    )
    p_low = PlatformPost(
        account_id=acc.id, platform="douyin", platform_post_id="low",
        title="分数低但有文案", publish_time=base - timedelta(hours=1),
    )
    db.add_all([p_high, p_low])
    db.flush()
    v = Video(filename="low_with_text.mp4", creator_id=owner.id, status="published")
    db.add(v)
    db.flush()
    db.add(Transcript(video_id=v.id, transcript_text="这是一段有内容的转写口播文案……", asr_status="done"))
    p_low.local_video_id = v.id
    db.add_all(
        [
            PlatformPostStat(post_id=p_high.id, stat_date="2026-09-06", likes=1000, comments=100),
            PlatformPostStat(post_id=p_low.id, stat_date="2026-09-06", likes=200, comments=5),
        ]
    )
    db.commit()

    app = FastAPI()
    app.include_router(benchmark_api.router, prefix="/api/benchmark")

    def override_db():
        try:
            yield db
        finally:
            pass

    app.dependency_overrides[get_db] = override_db
    r = TestClient(app).get("/api/benchmark/top")
    assert r.status_code == 200, r.text
    items = r.json()["benchmarks"][0]["items"]
    assert len(items) == 2
    assert items[0]["post_id"] == p_low.id  # 有文案的顶到前面
    assert items[1]["post_id"] == p_high.id


def test_unit_is_ad_uses_strict_judge(db, monkeypatch):
    from app.services import benchmark as bm

    post = PlatformPost(account_id=1, platform="douyin", platform_post_id="x", title="推自家小程序", is_ad=False)
    unit = {"post": post}

    class FakeLLM:
        def chat_json(self, messages, **kw):
            assert "广告/商单/带货/引流" in messages[0]["content"]
            return {"is_ad": True, "reason": "推广自家小程序"}

    monkeypatch.setattr(bm, "_llm", lambda db=None: FakeLLM())
    assert bm._unit_is_ad(db, unit, "文案内容……") is True

    class FakeNo:
        def chat_json(self, messages, **kw):
            return {"is_ad": False}

    monkeypatch.setattr(bm, "_llm", lambda db=None: FakeNo())
    assert bm._unit_is_ad(db, unit, "普通知识内容") is False
    # 已标记的帖子直接命中，不走 LLM
    post.is_ad = True
    assert bm._unit_is_ad(db, unit, "任意") is True
