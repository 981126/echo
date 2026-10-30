"""R-152/R-174 测试：对标「前3 + 最新一篇」（4 条）口径 + 素材库非主博主洗稿来源解析（mock 离线）。"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest
from conftest import ensure_schema, fresh_engine
from sqlalchemy.orm import sessionmaker

from app.models.platform import Creator, CreatorAccount, PlatformPost, PlatformPostStat
from app.models.video import Transcript, Video
from app.services.benchmark import ensure_top_with_text, resolve_rewrite_source, target_units

BASE = datetime(2026, 9, 1, 12, 0, 0)


@pytest.fixture()
def db(tmp_path):
    eng = fresh_engine()
    ensure_schema(eng)
    session = sessionmaker(bind=eng, autoflush=False, autocommit=False)()
    yield session
    session.close()


def _seed(db, *, owner=True):
    o = Creator(kind="owner", name="我", is_current=True) if owner else None
    if o is not None:
        db.add(o)
        db.commit()
    bm = Creator(kind="benchmark", parent_id=o.id if o else None, name="对标A")
    db.add(bm)
    db.commit()
    acc = CreatorAccount(creator_id=bm.id, platform="douyin", nickname="号", enabled=True)
    db.add(acc)
    db.commit()
    return o, bm, acc


def _post(db, acc, pid, *, hours_ago, likes=0):
    p = PlatformPost(
        account_id=acc.id,
        platform="douyin",
        platform_post_id=pid,
        title=f"标题-{pid}",
        publish_time=BASE - timedelta(hours=hours_ago),
    )
    db.add(p)
    db.commit()
    db.add(PlatformPostStat(post_id=p.id, stat_date="2026-09-06", likes=likes))
    db.commit()
    return p


def _ids(units):
    return [u["post"].platform_post_id for u in units]


def test_target_units_top3_plus_latest(db):
    """R-174：前 3（互动分）+ 最新一篇 = 4 条。"""
    _, bm, acc = _seed(db)
    _post(db, acc, "best", hours_ago=1, likes=1000)
    _post(db, acc, "second", hours_ago=2, likes=500)
    _post(db, acc, "third", hours_ago=3, likes=300)
    _post(db, acc, "fourth", hours_ago=4, likes=200)  # 前3 之外，不该入选
    _post(db, acc, "recent", hours_ago=0, likes=1)  # 最新一篇，互动分最低

    assert _ids(target_units(db, bm)) == ["best", "second", "third", "recent"]


def test_target_units_overlap_falls_back_to_next_score(db):
    """最新一篇同时是分数第一 → 顺延补第 4 条（保底 4 条，R-174）。"""
    _, bm, acc = _seed(db)
    _post(db, acc, "best", hours_ago=0, likes=1000)  # 既是最新也是最高分
    _post(db, acc, "second", hours_ago=1, likes=500)
    _post(db, acc, "third", hours_ago=2, likes=300)
    _post(db, acc, "fourth", hours_ago=3, likes=200)

    assert _ids(target_units(db, bm)) == ["best", "second", "third", "fourth"]


def test_target_units_candidates_short_returns_all(db):
    """候选不足 4 条时返回可用的全部（与原口径同规则）。"""
    _, bm, acc = _seed(db)
    _post(db, acc, "best", hours_ago=1, likes=1000)
    _post(db, acc, "recent", hours_ago=0, likes=1)

    assert _ids(target_units(db, bm)) == ["best", "recent"]


def test_target_units_with_text_first(db, monkeypatch):
    """展示口径：有文案优先（R-106），没文案的排到有文案之后。"""
    _, bm, acc = _seed(db)
    _post(db, acc, "high_no_text", hours_ago=1, likes=1000)
    _post(db, acc, "low_with_text", hours_ago=2, likes=1)
    _post(db, acc, "another", hours_ago=3, likes=0)
    _post(db, acc, "latest", hours_ago=0, likes=0)
    monkeypatch.setattr(
        "app.services.benchmark._unit_text",
        lambda db_, unit: "有文案" if unit["post"].platform_post_id == "low_with_text" else "",
    )
    ids = _ids(target_units(db, bm, with_text_first=True))
    assert ids[0] == "low_with_text"
    assert "latest" in ids and len(ids) == 4


def test_ensure_top_transcribes_latest(db, monkeypatch):
    """R-152：第三篇（最新）没有文案时也会被补齐转写。"""
    _, bm, acc = _seed(db)
    best = _post(db, acc, "best", hours_ago=1, likes=1000)
    second = _post(db, acc, "second", hours_ago=2, likes=500)
    latest = _post(db, acc, "latest", hours_ago=0, likes=1)

    texts = {best.id: "best 文案", second.id: "second 文案"}
    calls: list[int] = []

    def _fake_text(_db, unit):
        return texts.get(unit["post"].id, "")

    def _fake_media(_db, payload):
        calls.append(payload["post_id"])
        texts[payload["post_id"]] = "补齐的转写文案"

    monkeypatch.setattr("app.services.benchmark._unit_text", _fake_text)
    monkeypatch.setattr("app.services.benchmark._units_are_ad", lambda _db, _units, _texts: {})
    monkeypatch.setattr("app.services.media_ensure.platform_media_task", _fake_media)

    picked = ensure_top_with_text(db, bm, limit_candidates=15)
    assert _ids(picked) == ["best", "second", "latest"]
    assert calls == [latest.id]


def test_resolve_rewrite_source_video(db, monkeypatch):
    owner, bm, acc = _seed(db)
    post = _post(db, acc, "p1", hours_ago=0, likes=10)
    video = Video(filename="bm.mp4", title="对标口播", creator_id=bm.id)
    db.add(video)
    db.flush()
    db.add(Transcript(video_id=video.id, transcript_text="ASR 转写文案内容", asr_status="done"))
    post.local_video_id = video.id
    db.commit()

    src = resolve_rewrite_source(db, owner, video_id=video.id)
    assert src["text"] == "ASR 转写文案内容"
    assert src["title"] == "对标口播"
    assert src["key"] == f"v{video.id}"
    assert src["benchmark_name"] == "对标A"
    assert src["post_id"] == post.id


def test_resolve_rewrite_source_rejects_main_owner_video(db):
    owner, bm, acc = _seed(db)
    own_video = Video(filename="mine.mp4", title="我自己的", creator_id=owner.id)
    db.add(own_video)
    db.flush()
    db.add(Transcript(video_id=own_video.id, transcript_text="我的文案", asr_status="done"))
    db.commit()
    with pytest.raises(ValueError):
        resolve_rewrite_source(db, owner, video_id=own_video.id)


def test_resolve_rewrite_source_requires_text(db):
    owner, bm, acc = _seed(db)
    video = Video(filename="bm.mp4", title="没转写", creator_id=bm.id)
    db.add(video)
    db.commit()
    with pytest.raises(ValueError):
        resolve_rewrite_source(db, owner, video_id=video.id)


def test_resolve_rewrite_source_post(db):
    owner, bm, acc = _seed(db)
    post = _post(db, acc, "cloud1", hours_ago=0, likes=5)
    video = Video(filename="cloud1.mp4", creator_id=bm.id)
    db.add(video)
    db.flush()
    db.add(Transcript(video_id=video.id, corrected_text="校对后的转写", asr_status="done"))
    post.local_video_id = video.id
    db.commit()

    src = resolve_rewrite_source(db, owner, post_id=post.id)
    assert src["text"] == "校对后的转写"
    assert src["key"] == f"p{post.id}"
    assert src["post_id"] == post.id


def _client(db):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.api import benchmark as benchmark_api
    from app.db import get_db

    app = FastAPI()
    app.include_router(benchmark_api.router, prefix="/api/benchmark")

    def override_db():
        yield db

    app.dependency_overrides[get_db] = override_db
    return TestClient(app)


def test_top_endpoint_returns_four_and_latest_last(db):
    """R-174：/api/benchmark/top 每个对标返回 4 条（前3 + 最新），最新在最后一条。"""
    _, bm, acc = _seed(db)
    _post(db, acc, "best", hours_ago=1, likes=1000)
    _post(db, acc, "second", hours_ago=2, likes=500)
    _post(db, acc, "third", hours_ago=3, likes=300)
    _post(db, acc, "recent", hours_ago=0, likes=1)

    r = _client(db).get("/api/benchmark/top")
    assert r.status_code == 200, r.text
    items = r.json()["benchmarks"][0]["items"]
    assert [it["title"] for it in items] == ["标题-best", "标题-second", "标题-third", "标题-recent"]


def test_rewrite_source_endpoint_starts_task(db, monkeypatch):
    owner, bm, acc = _seed(db)
    post = _post(db, acc, "p1", hours_ago=0, likes=10)
    video = Video(filename="bm.mp4", title="对标口播", creator_id=bm.id)
    db.add(video)
    db.flush()
    db.add(Transcript(video_id=video.id, transcript_text="ASR 文案", asr_status="done"))
    post.local_video_id = video.id
    db.commit()

    captured: dict = {}

    def fake_start(kind, payload, fn):
        captured["kind"] = kind
        captured["payload"] = payload
        return 77

    monkeypatch.setattr("app.api.benchmark.start_task", fake_start)
    r = _client(db).post("/api/benchmark/rewrite-source", json={"video_id": video.id})
    assert r.status_code == 200, r.text
    assert r.json()["task_id"] == 77
    assert captured["kind"] == "benchmark_rewrite"
    assert captured["payload"]["owner_id"] == owner.id
    assert captured["payload"]["text"] == "ASR 文案"
    assert captured["payload"]["benchmark_name"] == "对标A"


def test_rewrite_source_endpoint_400_when_no_text(db):
    _, bm, acc = _seed(db)
    video = Video(filename="bm.mp4", title="没转写", creator_id=bm.id)
    db.add(video)
    db.commit()
    r = _client(db).post("/api/benchmark/rewrite-source", json={"video_id": video.id})
    assert r.status_code == 400
    assert "文案" in r.json()["detail"]
