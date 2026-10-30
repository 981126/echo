"""R-240（S5/S3/M5）：素材库/作品快照缓存 + 人设批量 + 生成上下文缓存。

覆盖：
- S5：数据版本键 + TTL 快照缓存命中（page/list_works 不重复全量重建）、命中返回浅拷贝、
  数据变化（新增素材/作品合并/新增指标）自动失效、分页/筛选/游标语义与原直算逻辑一致；
- S3：`_all_texts` 预取 transcript、`_weight` 批量 map、`suggest_phrase_candidates` 批量指标
  （输出内容/顺序不变，engagement 仍是整数）；
- M5：`_material_version` 覆盖「转写正文原地编辑」、`_style_profile` 命中不再全量加载语料、
  `author_style_context` 静态部分缓存但素材/人设变化后重建、`_reverted_lessons` 批量输出不变。
"""

from __future__ import annotations

import json
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest
from conftest import ensure_schema, fresh_engine
from sqlalchemy.orm import sessionmaker

from app.models.draft import Draft
from app.models.metrics import MetricsSnapshot
from app.models.persona import PersonaTag
from app.models.platform import Creator, CreatorAccount, PlatformPost, PlatformPostStat
from app.models.video import Transcript, Video
from app.services import generation as gen
from app.services import library_service, persona, works_service
from app.services.draft_versions import snapshot_version
from app.services.library_service import CardFilters


@pytest.fixture()
def db(tmp_path):
    eng = fresh_engine()
    ensure_schema(eng)
    session = sessionmaker(bind=eng, autoflush=False, autocommit=False)()
    yield session
    session.close()


@pytest.fixture(autouse=True)
def _clear_process_caches():
    """进程内缓存跨用例共享（R-240）：用例前后清空，避免本文件结果污染其它测试。"""

    def _clear() -> None:
        library_service._CARD_CACHE.clear()
        works_service._CARD_CACHE.clear()
        works_service._WORKS_CACHE.clear()
        gen._INDEX_CACHE.clear()
        gen._PROFILE_DICT_CACHE.clear()
        gen._STATIC_STYLE_CACHE.clear()

    _clear()
    yield
    _clear()


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


def _video(db, cid, *, title, date, text=None, **kw):
    for key in ("platforms", "main_topics", "tags"):
        if key in kw and isinstance(kw[key], list):
            kw[key] = json.dumps(kw[key], ensure_ascii=False)
    v = Video(creator_id=cid, title=title, filename=f"{title}.mp4", created_at=_dt(date), **kw)
    db.add(v)
    db.commit()
    if text is not None:
        db.add(Transcript(video_id=v.id, corrected_text=text))
        db.commit()
    return v


def _post(db, acc, *, title, date, tags=None, platform="bilibili", **kw):
    p = PlatformPost(
        account_id=acc.id,
        platform=platform,
        platform_post_id=f"p-{title}",
        title=title,
        publish_time=_dt(date),
        tags=json.dumps(tags or [], ensure_ascii=False),
        **kw,
    )
    db.add(p)
    db.commit()
    return p


def _stat(db, post, *, stat_date: str, likes):
    db.add(
        PlatformPostStat(
            post_id=post.id,
            stat_date=stat_date,
            likes=likes,
            plays=100,
        )
    )
    db.commit()


def _count_calls(monkeypatch, module, name: str) -> dict:
    """把模块内函数替换成带计数的包装，返回 `{"n": 调用次数}`。"""
    calls = {"n": 0}
    orig = getattr(module, name)

    def wrapper(*args, **kwargs):
        calls["n"] += 1
        return orig(*args, **kwargs)

    monkeypatch.setattr(module, name, wrapper)
    return calls


# ---------- S5：素材库卡片快照缓存 ----------


def test_library_page_cache_hit_and_data_version_invalidation(db, monkeypatch):
    c, acc = _owner(db)
    _video(db, c.id, title="素材一", date="2026-09-01 10:00:00")
    _video(db, c.id, title="素材二", date="2026-09-02 10:00:00")
    post = _post(db, acc, title="云端作品", date="2026-09-03 10:00:00")
    _stat(db, post, stat_date="2026-09-03", likes=120)
    calls = _count_calls(monkeypatch, library_service, "_build_cards")

    res1 = library_service.page(db, creator_id=c.id, limit=20)
    assert calls["n"] == 1
    res2 = library_service.page(db, creator_id=c.id, limit=20)
    assert calls["n"] == 1, "同一数据版本内翻页/重复请求应命中缓存，不再全量重建"
    assert res1 == res2

    # 新增素材 → 版本键变化 → 自动失效并重建
    _video(db, c.id, title="素材三", date="2026-09-04 10:00:00")
    res3 = library_service.page(db, creator_id=c.id, limit=20)
    assert calls["n"] == 2
    assert res3["total"] == res1["total"] + 1
    assert "素材三" in [i["title"] for i in res3["items"]]

    # 新增指标（数量变化）→ 版本键变化 → 卡片最新数据跟着刷新
    _stat(db, post, stat_date="2026-09-04", likes=999)
    res4 = library_service.page(db, creator_id=c.id, limit=20)
    assert calls["n"] == 3
    cloud = next(i for i in res4["items"] if i["key"] == f"p{post.id}")
    assert cloud["cloudPosts"][0]["latest_stat"]["likes"] == 999


def test_library_cache_hit_returns_shallow_copy(db, monkeypatch):
    c, acc = _owner(db)
    _video(db, c.id, title="素材一", date="2026-09-01 10:00:00")
    _post(db, acc, title="云端作品", date="2026-09-02 10:00:00")
    _count_calls(monkeypatch, library_service, "_build_cards")

    library_service.page(db, creator_id=c.id, limit=20)  # 预热缓存
    cards1 = library_service.build_cards(db, c.id)
    cards1[0]["title"] = "被调用方篡改"
    cards2 = library_service.build_cards(db, c.id)
    assert "被调用方篡改" not in [card["title"] for card in cards2], "命中必须返回浅拷贝，防污染缓存"


def test_library_page_semantics_unchanged_with_cache(db):
    c, acc = _owner(db)
    _video(db, c.id, title="面试技巧", date="2026-09-01 10:00:00", status="published", tags=["求职"])
    _video(db, c.id, title="副业赚钱", date="2026-09-02 10:00:00", status="planned")
    _post(db, acc, title="面试官视角", date="2026-09-03 10:00:00", tags=["面试"], is_ad=True, ad_price=300)

    filters = CardFilters(kw="面试", tags=["面试"])
    uncached = library_service._build_cards(db, c.id)  # 直算（缓存未参与）
    expected = library_service.apply_filters(uncached, filters)
    expected_keys = [card["key"] for card in expected]

    page1 = library_service.page(db, creator_id=c.id, filters=filters, limit=20)
    page2 = library_service.page(db, creator_id=c.id, filters=filters, limit=20)  # 走缓存
    assert page1 == page2
    assert [card["key"] for card in page1["items"]] == expected_keys
    assert page1["total"] == len(uncached)
    assert page1["filtered_total"] == len(expected)
    assert page1["facets"] == library_service.facets(uncached)


def test_library_cursor_pagination_hits_cache_and_stays_stable(db, monkeypatch):
    c, _acc = _owner(db)
    for i in range(1, 6):
        _video(db, c.id, title=f"素材{i}", date=f"2026-09-0{i} 10:00:00")
    calls = _count_calls(monkeypatch, library_service, "_build_cards")

    seen: list[str] = []
    cursor = None
    while True:
        res = library_service.page(db, creator_id=c.id, cursor=cursor, limit=2)
        seen += [item["title"] for item in res["items"]]
        if not res["next_cursor"]:
            break
        cursor = library_service.decode_cursor(res["next_cursor"])
    assert calls["n"] == 1, "整轮翻页共用一个数据版本，只应全量重建一次"
    assert seen == [f"素材{i}" for i in range(5, 0, -1)]


# ---------- S5：云端作品列表缓存 ----------


def test_list_works_cache_hit_copy_and_merge_invalidation(db, monkeypatch):
    c, acc = _owner(db)
    p1 = _post(db, acc, title="跨平台作品B站", date="2026-09-01 10:00:00")
    p2 = _post(db, acc, title="跨平台作品抖音", date="2026-09-02 10:00:00", platform="douyin")
    calls = _count_calls(monkeypatch, works_service, "_list_works")

    first = works_service.list_works(db, c.id)
    assert calls["n"] == 1
    second = works_service.list_works(db, c.id)
    assert calls["n"] == 1
    assert first == second
    assert first[0] is not second[0], "命中必须返回浅拷贝，防调用方修改污染缓存"
    second[0]["title"] = "被调用方篡改"
    assert works_service.list_works(db, c.id)[0]["title"] != "被调用方篡改"

    merged = works_service.merge_manual(db, [p1.id, p2.id], c.id)
    third = works_service.list_works(db, c.id)
    assert calls["n"] == 2, "合并写路径改变版本键 → 缓存应失效"
    work_item = next(item for item in third if item["type"] == "work")
    assert work_item["id"] == merged["work_id"]
    assert sorted(member["platform"] for member in work_item["posts"]) == ["bilibili", "douyin"]


# ---------- S3：人设/金句批量取数 ----------


def test_engagement_map_batches_latest_snapshot(db):
    c, _acc = _owner(db)
    v1 = _video(db, c.id, title="素材一", date="2026-09-01 10:00:00", text="第一句话内容。")
    v2 = _video(db, c.id, title="素材二", date="2026-09-02 10:00:00", text="第二句话内容。")
    db.add(MetricsSnapshot(video_id=v1.id, snapshot_date="2026-09-01", plays=10, likes=2))
    db.add(MetricsSnapshot(video_id=v1.id, snapshot_date="2026-09-02", plays=100, likes=5))
    db.add(MetricsSnapshot(video_id=v2.id, snapshot_date="2026-09-02", plays=200, likes=7))
    db.commit()

    engagements = gen._engagement_map(db, [v1, v2])
    assert engagements[v1.id] == 100 + 5 * 5  # 取最新一天
    assert engagements[v2.id] == 200 + 7 * 5
    weights = gen._weight_map(db, [v1, v2])
    assert set(weights) == {v1.id, v2.id}
    assert weights[v2.id] > weights[v1.id]  # 同一天，互动高 → 权重高


def test_style_overview_uses_batch_weights(db):
    from app.api.persona import style_overview

    c, _acc = _owner(db)
    today = date.today()
    recent = datetime.combine(today, datetime.min.time())
    old = recent - timedelta(days=900)
    v_old = _video(db, c.id, title="旧素材", date=old.strftime("%Y-%m-%d %H:%M:%S"), text="旧的文案内容。")
    v_new = _video(db, c.id, title="新素材", date=recent.strftime("%Y-%m-%d %H:%M:%S"), text="新的文案内容。")
    db.add(MetricsSnapshot(video_id=v_old.id, snapshot_date="2026-01-01", plays=10, likes=1))
    db.add(MetricsSnapshot(video_id=v_new.id, snapshot_date="2026-01-01", plays=500, likes=50))
    db.commit()

    out = style_overview(db)
    assert out["count"] == 2
    assert out["top_weighted"][0]["title"] == "新素材", "高互动 + 更近期的素材权重最高"
    assert [item["id"] for item in out["anchor_candidates"]] == [v_new.id, v_old.id]
    assert out["profile"]
    # 两个 sorted 复用同一排序结果：top_weighted 是 anchor_candidates 的前 3 条子集
    assert out["top_weighted"][0]["title"] == out["anchor_candidates"][0]["title"]


def test_suggest_phrase_candidates_batches_engagement(db):
    c, _acc = _owner(db)
    v1 = _video(db, c.id, title="低表现", date="2026-09-01 10:00:00", text="第一句话内容。第二句话内容。")
    v2 = _video(db, c.id, title="高表现", date="2026-09-02 10:00:00", text="第三句话内容。")
    _video(db, c.id, title="广告素材", date="2026-09-03 10:00:00", text="广告句子内容。", is_ad=True)
    db.add(MetricsSnapshot(video_id=v1.id, snapshot_date="2026-09-01", plays=10, likes=1))
    db.add(MetricsSnapshot(video_id=v2.id, snapshot_date="2026-09-01", plays=100, likes=9))
    db.commit()

    candidates = persona.suggest_phrase_candidates(db, limit=10)
    assert candidates, "有转写稿时应能提取金句候选"
    assert candidates[0]["source_title"] == "高表现", "按互动从高到低，输出顺序不变"
    assert isinstance(candidates[0]["engagement"], int), "engagement 字段仍是整数（响应契约不变）"
    assert candidates[0]["engagement"] == 100 + 9 * 5
    assert all(item["source_title"] != "广告素材" for item in candidates), "广告素材不参与人设学习"


# ---------- M5：生成上下文缓存 ----------


def test_material_version_covers_in_place_transcript_edit(db):
    c, _acc = _owner(db)
    v = _video(db, c.id, title="素材", date="2026-09-01 10:00:00", text="短文本")
    version1 = gen._material_version(db)

    transcript = db.query(Transcript).filter(Transcript.video_id == v.id).one()
    transcript.corrected_text = "更长的正文内容（原地编辑，id/条数都不变）"
    db.commit()
    version2 = gen._material_version(db)
    assert version1 != version2, "_material_version 必须覆盖转写正文原地编辑"


def test_style_profile_hit_skips_all_texts(db, monkeypatch):
    c, _acc = _owner(db)
    _video(db, c.id, title="素材一", date="2026-09-01 10:00:00", text="第一段作者文案内容。")
    _video(db, c.id, title="素材二", date="2026-09-02 10:00:00", text="第二段作者文案内容。")
    gen._PROFILE_DICT_CACHE.clear()

    profile1 = gen._style_profile(db)
    calls = _count_calls(monkeypatch, gen, "_all_texts")
    profile2 = gen._style_profile(db)
    assert calls["n"] == 0, "命中缓存时不应再全量加载 _all_texts"
    assert profile1 == profile2

    transcript = db.query(Transcript).join(Video, Video.id == Transcript.video_id).first()
    transcript.corrected_text = "第二段作者文案内容，追加了一句新的正文。"
    db.commit()
    profile3 = gen._style_profile(db)
    assert calls["n"] == 1, "素材版本变化后应重算"
    assert profile3 is not None


def test_author_style_context_static_cache_and_invalidation(db, monkeypatch):
    c, _acc = _owner(db)
    _video(db, c.id, title="素材一", date="2026-09-01 10:00:00", text="你好，我是作者。今天聊聊天。")

    first = gen.author_style_context(db, "如何谈薪")
    second = gen.author_style_context(db, "如何谈薪")
    assert first == second
    assert first.index("作者人设：") < first.index("红线（不要违反）：")
    assert first.index("红线（不要违反）：") < first.index("作者语言习惯")
    assert first.index("作者语言习惯") < first.index("风格样本")

    # 静态部分命中：第二次不再全量加载语料
    calls = _count_calls(monkeypatch, gen, "_all_texts")
    gen.author_style_context(db, "如何谈薪")
    assert calls["n"] == 0, "静态上下文命中后不应再全量加载语料"

    # 人设版本变化 → 静态部分重建，人设行出现
    db.add(PersonaTag(creator_id=c.id, label="犀利", description="", category="style", status="confirmed", version=2))
    db.commit()
    third = gen.author_style_context(db, "如何谈薪")
    assert third != first
    assert "犀利" in third

    # 素材正文变长（版本变化）→ 静态部分重建（画像等跟随变化）
    transcript = db.query(Transcript).join(Video, Video.id == Transcript.video_id).first()
    transcript.corrected_text = "你好，我是作者。今天聊聊天，再补充一段更长的正文内容。"
    db.commit()
    fourth = gen.author_style_context(db, "如何谈薪")
    assert fourth != third


def test_author_style_context_dynamic_mode_and_topic_samples(db):
    c, _acc = _owner(db)
    _video(db, c.id, title="素材一", date="2026-09-01 10:00:00", text="如何谈薪这件事，我有三个具体建议。")

    plain = gen.author_style_context(db, "如何谈薪")
    sharp = gen.author_style_context(db, "如何谈薪", mode="sharp")
    assert "本次创作模式" not in plain
    assert "本次创作模式：犀利干货" in sharp
    # 同一数据版本 + 不同 mode：只差动态模式行，静态部分完全复用
    other = gen.author_style_context(db, "完全不同的选题")
    assert other != plain, "风格样本随选题检索变化，属于动态部分"


def test_reverted_lessons_batch_same_output(db):
    c, _acc = _owner(db)

    def _reverted_draft(title: str, original: str, discussed: str) -> Draft:
        d = Draft(title=title, script=original, source="manual", creator_id=c.id)
        db.add(d)
        db.commit()
        snapshot_version(db, d, source="manual", note="定稿")
        d.script = discussed
        db.commit()
        snapshot_version(db, d, source="ai_discuss", note="讨论后")
        d.script = original
        db.commit()
        snapshot_version(db, d, source="rollback", note="回退到原稿")
        return d

    _reverted_draft("稿一", "作者原稿正文一", "AI 讨论后的正文一")
    _reverted_draft("稿二", "作者原稿正文二", "AI 讨论后的正文二")

    text = gen._reverted_lessons(db, limit=3)
    assert "改回了自己原来的稿子" in text
    assert "AI 讨论后的正文一" in text and "作者原稿正文一" in text
    assert "AI 讨论后的正文二" in text and "作者原稿正文二" in text
