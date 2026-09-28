"""R-179：素材库统一分页（合并去重口径、筛选下推、游标稳定）+ 封面缩略图。"""

from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core import thumbs
from app.db import Base
from app.models.platform import Creator, CreatorAccount, PlatformPost, PlatformPostStat
from app.models.video import Video
from app.models.work import Work
from app.services import library_service
from app.services.library_service import CardFilters


@pytest.fixture()
def db(tmp_path):
    eng = create_engine(f"sqlite:///{tmp_path}/t.db", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=eng)
    session = sessionmaker(bind=eng, autoflush=False, autocommit=False)()
    yield session
    session.close()
    eng.dispose()


def _dt(value: str) -> datetime:
    return datetime.strptime(value, "%Y-%m-%d %H:%M:%S")


def _owner(db):
    c = Creator(kind="owner", name="我", is_current=True)
    db.add(c)
    db.commit()
    acc = CreatorAccount(creator_id=c.id, platform="bilibili", nickname="我", enabled=True)
    db.add(acc)
    db.commit()
    return c, acc


def _video(db, cid, *, title, date, filename=None, **kw):
    # videos.filename 唯一：默认按标题派生，避免测试互相撞名
    if "platforms" in kw:
        kw["platforms"] = json.dumps(kw["platforms"])
    if "tags" in kw:
        kw["tags"] = json.dumps(kw["tags"], ensure_ascii=False)
    v = Video(
        creator_id=cid,
        title=title,
        filename=filename or f"{title}.mp4",
        created_at=_dt(date),
        **kw,
    )
    db.add(v)
    db.commit()
    return v


def _cloud(db, cid, acc, *, title, date, platform="bilibili", tags=None, likes=None, work=None, local_video=None, **kw):
    p = PlatformPost(
        account_id=acc.id,
        platform=platform,
        platform_post_id=f"p{title}{date}",
        title=title,
        publish_time=_dt(date),
        tags=json.dumps(tags or [], ensure_ascii=False),
        is_ad=kw.pop("is_ad", False),
        ad_price=kw.pop("ad_price", None),
        local_video_id=local_video.id if local_video else None,
        work_id=work.id if work else None,
        **kw,
    )
    db.add(p)
    db.commit()
    if likes is not None:
        db.add(PlatformPostStat(post_id=p.id, stat_date=_dt(date).date(), likes=likes))
        db.commit()
    return p


# ---------- 合并去重口径 ----------


def test_cards_merge_local_and_cloud_and_dedupe_bound_video(db):
    c, acc = _owner(db)
    bound = _video(db, c.id, title="已绑定的本地素材", date="2026-09-01 10:00:00")
    _video(db, c.id, title="独立本地素材", date="2026-09-02 10:00:00")
    _cloud(db, c.id, acc, title="云端作品A", date="2026-09-03 10:00:00", local_video=bound, tags=["求职"], likes=120)

    cards = library_service.build_cards(db, c.id)
    kinds = {(c["kind"], c["title"]) for c in cards}
    assert ("local", "独立本地素材") in kinds
    assert ("local", "已绑定的本地素材") not in kinds, "被云端作品绑定的本地素材不应重复出现"
    cloud = next(c for c in cards if c["kind"] == "cloud")
    assert cloud["local_video_id"] == bound.id
    assert cloud["hasVideo"] is True  # 绑定素材有真实文件
    assert cloud["cloudPosts"][0]["latest_stat"]["likes"] == 120
    # 日期倒序：09-03 云端 → 09-02 本地
    assert [c["title"] for c in cards] == ["云端作品A", "独立本地素材"]


def test_cloud_work_merges_platforms_and_dedupes_tags(db):
    c, acc = _owner(db)
    w = Work(creator_id=c.id, title="跨平台作品")
    db.add(w)
    db.commit()
    _cloud(db, c.id, acc, title="B站版", date="2026-09-05 09:00:00", platform="bilibili", tags=["A", "B"], work=w)
    _cloud(db, c.id, acc, title="抖音版", date="2026-09-04 09:00:00", platform="douyin", tags=["B", "C"], work=w)

    cards = library_service.build_cards(db, c.id)
    assert len(cards) == 1
    card = cards[0]
    assert card["type"] == "work" and card["merged"] == 2
    assert card["platforms"] == ["bilibili", "douyin"]
    assert card["tags"] == ["A", "B", "C"], "标签合并去重且保序"
    assert card["date"] == "2026-09-05", "作品卡片日期取排序后的第一篇（按平台名）"


# ---------- 筛选口径（搬移前 applyFiltersTo 同语义） ----------


def test_filters_match_previous_frontend_semantics(db):
    c, acc = _owner(db)
    _video(db, c.id, title="面试技巧", date="2026-09-01 10:00:00", platforms=["douyin"], status="published", tags=["求职"])
    _video(db, c.id, title="副业赚钱", date="2026-09-02 10:00:00", platforms=["bilibili"], status="planned", filename="__cloud__")
    _cloud(db, c.id, acc, title="面试官视角", date="2026-09-03 10:00:00", tags=["面试"], likes=500, is_ad=True, ad_price=300)

    cards = library_service.build_cards(db, c.id)
    assert len(library_service.apply_filters(cards, CardFilters(kw="面试"))) == 2
    assert len(library_service.apply_filters(cards, CardFilters(status="planned"))) == 1
    assert len(library_service.apply_filters(cards, CardFilters(ad="ad"))) == 1
    # 无视频 = __cloud__ 占位稿 + 没有绑定本地素材的云端卡片（与搬移前同语义）
    assert len(library_service.apply_filters(cards, CardFilters(video="no"))) == 2
    assert len(library_service.apply_filters(cards, CardFilters(video="yes"))) == 1
    assert len(library_service.apply_filters(cards, CardFilters(platforms=["douyin"]))) == 1
    assert len(library_service.apply_filters(cards, CardFilters(tags=["求职"]))) == 1
    assert len(library_service.apply_filters(cards, CardFilters(tags=["求职", "面试"]))) == 0, "多标签是 AND"
    assert len(library_service.apply_filters(cards, CardFilters(likes_min=100, likes_max=600))) == 1
    assert len(library_service.apply_filters(cards, CardFilters(likes_min=600))) == 0
    assert library_service.facets(cards)["tags"] == ["求职", "副业", "面试"] or set(
        library_service.facets(cards)["tags"]
    ) == {"求职", "面试"}


# ---------- 游标分页 ----------


def test_cursor_pagination_is_stable_when_new_items_arrive(db):
    c, acc = _owner(db)
    for i in range(1, 8):
        _video(db, c.id, title=f"素材{i}", date=f"2026-09-0{i} 10:00:00")

    seen: list[str] = []
    cursor = None
    pages = 0
    while True:
        res = library_service.page(db, creator_id=c.id, cursor=cursor, limit=3)
        assert res["filtered_total"] >= 7, "筛选后总数是实时口径"
        seen += [i["title"] for i in res["items"]]
        pages += 1
        if not res["next_cursor"]:
            break
        cursor = library_service.decode_cursor(res["next_cursor"])
        if pages == 1:
            # 翻页途中后台同步插入更新的条目（插在列表最前面）
            _video(db, c.id, title="插队的新素材", date="2026-09-09 10:00:00")
            res_after = library_service.page(db, creator_id=c.id, cursor=cursor, limit=3)
            assert "插队的新素材" not in [i["title"] for i in res_after["items"]], "游标之后不该看到新插入的条目"
    assert pages == 3
    assert seen == [f"素材{i}" for i in range(7, 0, -1)], f"不重复不漏条：{seen}"


def test_decode_cursor_bad_input():
    assert library_service.decode_cursor("") is None
    assert library_service.decode_cursor("!!!not-base64!!!") is None
    token = library_service._encode_cursor({"date": "2026-09-01", "kind": "local", "id": 3})
    assert library_service.decode_cursor(token) == ("2026-09-01", "local", 3)


# ---------- 缩略图 ----------


def test_clamp_width():
    assert thumbs.clamp_width(None) is None
    assert thumbs.clamp_width("abc") is None
    assert thumbs.clamp_width(10) == thumbs.MIN_WIDTH
    assert thumbs.clamp_width(400) == 400
    assert thumbs.clamp_width(99999) == thumbs.MAX_WIDTH


def test_make_thumb_resizes_and_keeps_jpeg(tmp_path):
    from PIL import Image

    src = tmp_path / "big.jpg"
    Image.new("RGB", (1600, 900), (200, 30, 30)).save(src, quality=95)
    dest = tmp_path / "thumbs" / "big.jpg.w400.jpg"

    assert thumbs.make_thumb(src, dest, 400) is True
    with Image.open(dest) as im:
        assert im.width == 400
        assert im.height == 225
    assert dest.stat().st_size < src.stat().st_size


def test_make_thumb_bad_image_returns_false(tmp_path):
    src = tmp_path / "broken.jpg"
    src.write_bytes(b"not an image")
    assert thumbs.make_thumb(src, tmp_path / "t.jpg", 400) is False


def test_cover_route_serves_thumbnail(tmp_path, monkeypatch):
    """`/covers/<name>?w=400` 走缩略图并落盘缓存；不带 w 走原图。"""
    from fastapi.testclient import TestClient
    from PIL import Image

    from app import main as main_module

    covers = tmp_path / "covers"
    covers.mkdir()
    Image.new("RGB", (1200, 800), (10, 90, 200)).save(covers / "demo.jpg", quality=95)
    monkeypatch.setattr(main_module._settings, "covers_dir", covers)
    client = TestClient(main_module.app)

    full = client.get("/covers/demo.jpg")
    assert full.status_code == 200
    assert len(full.content) > 0

    resp = client.get("/covers/demo.jpg?w=400")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "image/jpeg"
    assert (covers / "thumbs" / "demo.jpg.w400.jpg").is_file(), "缩略图应落盘缓存"
    with Image.open(covers / "thumbs" / "demo.jpg.w400.jpg") as im:
        assert im.width == 400
    assert len(resp.content) < len(full.content)

    # 目录穿越防护
    assert client.get("/covers/../echo.db").status_code == 404
    assert client.get("/covers/nope.jpg").status_code == 404
