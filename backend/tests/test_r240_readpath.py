"""R-240 读接口批量预取（S1/S8/S6）+ 重新对标并发（M2）自测。

覆盖：
- S1 `benchmarks_of_owner/... /top`：`candidates_many` 一次批量取候选（与单博主口径一致）、
  `unit_text_map` 一次取文案（含同 work 兜底/一视频多转写取一条）、`get_analysis_map` 一次 IN、
  `/top` 首屏 SQL 从数百条降到常数级且输出与旧逐条路径**逐字段一致**；
- S8 对标准备：多条候选合并 1 次批量 LLM 判定、解析失败/异常全按 False（不误杀）、
  `ensure_top_with_text` 凑批判广并保持「前3+最新」/广告顺延/保底 4 条；
- S6 视频复盘：`build_comparison` 一次 IN + 内存 cutoff（语义与逐格查询一致）、
  `peer_references` 窗口函数一次取各账号最新帖、`list_videos` 最新 review 一次批量、`_follower_topics` 一次批量、
  `low_fan_references` 关键词只算一次、`recommend_topics` 人设上下文循环外一次；
- M2 重新对标：按对标博主并发（独立 Session）、主线程累计进度 `[i/total] 名称：...`、
  单博主失败不阻断、BudgetExceeded 向上抛出（后续博主快速退出）。
"""

from __future__ import annotations

import json
import sys
import threading
import time
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest
from conftest import ensure_schema, fresh_engine
from sqlalchemy import event
from sqlalchemy.orm import sessionmaker

from app.models.kv import Kv
from app.models.persona import PersonaTag
from app.models.platform import Creator, CreatorAccount, PlatformPost, PlatformPostComment, PlatformPostStat
from app.models.video import Transcript, Video
from app.models.video_review import DouyinPostMetric, DouyinReferenceVideo, VideoReview
from app.core.timeutil import now as _app_now
from app.models.work import Work
from app.services import benchmark as benchmark_service
from app.services import video_review_service
from app.services import video_review_topics
from app.services.douyin_references import _owner_keywords, relevance_for
from app.services.platform.budget import BudgetExceeded
from app.services.video_review_comparison import (
    SPEC_MAP,
    build_comparison,
    low_fan_references,
    peer_references,
)
from app.services.video_review_rules import comment_questions

BASE = datetime(2026, 9, 1, 12, 0, 0)


@pytest.fixture()
def db(tmp_path):
    eng = fresh_engine()
    ensure_schema(eng)
    session = sessionmaker(bind=eng, autoflush=False, autocommit=False)()
    yield session
    session.close()


@contextmanager
def _sql_count(db):
    """统计上下文内执行的 SQL 条数（R-240 验收：同类查询必须合并为常数条）。"""
    counter = {"n": 0}
    bind = db.get_bind()

    def _before(*_args, **_kwargs):
        counter["n"] += 1

    event.listen(bind, "before_cursor_execute", _before)
    try:
        yield counter
    finally:
        event.remove(bind, "before_cursor_execute", _before)


def _owner(db) -> Creator:
    owner = Creator(kind="owner", name="我", is_current=True)
    db.add(owner)
    db.commit()
    return owner


def _benchmark(db, owner: Creator, name: str, platform: str = "douyin") -> tuple[Creator, CreatorAccount]:
    bm = Creator(kind="benchmark", parent_id=owner.id, name=name)
    db.add(bm)
    db.commit()
    acc = CreatorAccount(creator_id=bm.id, platform=platform, nickname=name, enabled=True)
    db.add(acc)
    db.commit()
    return bm, acc


def _post(
    db,
    acc: CreatorAccount,
    pid: str,
    *,
    hours_ago: int = 1,
    likes: int = 0,
    is_ad: bool = False,
    title: str = "",
    platform: str = "douyin",
    work_id: int | None = None,
) -> PlatformPost:
    post = PlatformPost(
        account_id=acc.id,
        platform=platform,
        platform_post_id=pid,
        title=title or f"标题-{pid}",
        publish_time=BASE - timedelta(hours=hours_ago),
        is_ad=is_ad,
        work_id=work_id,
        tags="[]",
        raw="{}",
    )
    db.add(post)
    db.flush()
    if likes:
        db.add(PlatformPostStat(post_id=post.id, stat_date="2026-09-06", likes=likes))
    return post


def _add_transcript(db, filename: str, *, creator_id: int, text: str, work_id: int | None = None) -> Video:
    video = Video(filename=filename, creator_id=creator_id, work_id=work_id)
    db.add(video)
    db.flush()
    db.add(Transcript(video_id=video.id, transcript_text=text, asr_status="done"))
    db.flush()
    return video


# ---------- S1：候选批量预取 / 文案 map / 分析 map / /top ----------


def test_candidates_many_matches_single_benchmark(db):
    """批量候选与单博主 candidates() 口径一致：广告、同款漏标、work 聚合、排序。"""
    owner = _owner(db)
    bm1, acc1 = _benchmark(db, owner, "对标A")
    bm2, acc2 = _benchmark(db, owner, "对标B")
    work = Work(creator_id=bm1.id, title="同作品")
    db.add(work)
    db.commit()
    _post(db, acc1, "n1", hours_ago=1, title="谈薪技巧")
    _post(db, acc1, "adv", hours_ago=2, title="某品牌手机", is_ad=True)
    _post(db, acc1, "twin", hours_ago=2, title="某品牌手机")  # 与广告同标题 → 一并排除（R-100）
    w1 = _post(db, acc1, "w-douyin", hours_ago=2, work_id=work.id, title="同作品抖音")
    w2 = _post(db, acc1, "w-bili", hours_ago=3, work_id=work.id, platform="bilibili", title="同作品B站")
    _post(db, acc2, "b1", hours_ago=1)
    db.commit()

    many = benchmark_service.candidates_many(db, [bm1, bm2], limit=15)
    for bm, acc in ((bm1, acc1), (bm2, acc2)):
        single = benchmark_service.candidates(db, bm, limit=15)
        assert [u["post"].platform_post_id for u in many[bm.id]] == [
            u["post"].platform_post_id for u in single
        ]
    ids = [u["post"].platform_post_id for u in many[bm1.id]]
    assert "adv" not in ids and "twin" not in ids
    grouped = next(u for u in many[bm1.id] if u.get("work_id") == work.id)
    assert {m.platform_post_id for m in grouped["members"]} == {w1.platform_post_id, w2.platform_post_id}
    assert grouped["post"].platform_post_id == "w-douyin"  # 最新成员当主帖


def test_unit_text_map_work_fallback_and_highest_transcript(db):
    """文案 map：本地视频优先、同 work 其它平台视频兜底；一视频多转写取 transcript.id 最大一条。"""
    owner = _owner(db)
    bm, acc = _benchmark(db, owner, "对标A")
    work = Work(creator_id=bm.id, title="同作品")
    db.add(work)
    db.commit()
    video_a = Video(filename="a.mp4", creator_id=bm.id)
    db.add(video_a)
    db.flush()
    video_b = Video(filename="b.mp4", creator_id=bm.id, work_id=work.id)
    db.add(video_b)
    db.flush()
    db.add(Transcript(video_id=video_b.id, transcript_text="旧文案", asr_status="done"))
    db.flush()
    db.add(Transcript(video_id=video_b.id, transcript_text="新文案", asr_status="done"))
    db.flush()
    p_work = _post(db, acc, "p-work", work_id=work.id)
    p_work.local_video_id = video_a.id
    video_c = _add_transcript(db, "c.mp4", creator_id=bm.id, text="本地视频文案")
    p_local = _post(db, acc, "p-local")
    p_local.local_video_id = video_c.id
    db.commit()

    unit_work = {"work_id": work.id, "post": p_work}
    unit_local = {"work_id": None, "post": p_local}
    text_map = benchmark_service.unit_text_map(db, [unit_work, unit_local])
    assert text_map[p_work.id] == "新文案"  # 本地视频无转写 → 同 work 的其它视频兜底
    assert text_map[p_local.id] == "本地视频文案"


def test_target_units_uses_prefetched_text_map_without_queries(db, monkeypatch):
    """传入 map 时 target_units 不再逐条查文案；有文案优先排序口径不变。"""
    owner = _owner(db)
    bm, acc = _benchmark(db, owner, "对标A")
    p_no_text = _post(db, acc, "no-text", hours_ago=1, likes=1000)
    p_text = _post(db, acc, "with-text", hours_ago=2, likes=10)
    db.commit()
    units = [
        {"work_id": None, "post": p_no_text},
        {"work_id": None, "post": p_text},
    ]

    def _must_not_call(*_args, **_kwargs):
        raise AssertionError("传入 video_text_map 后不应再逐条 _unit_text 查库")

    monkeypatch.setattr(benchmark_service, "_unit_text", _must_not_call)
    picked = benchmark_service.target_units(
        db,
        bm,
        with_text_first=True,
        units=units,
        video_text_map={p_no_text.id: "", p_text.id: "有文案"},
        stats_map={},
    )
    assert [u["post"].platform_post_id for u in picked] == ["with-text", "no-text"]


def test_benchmark_top_batch_sql_and_output_equivalence(db):
    """S1 验收：/top 首屏 SQL ≤10，且输出与旧逐条路径完全一致（含文案/分析/前3+最新排序）。"""
    owner = _owner(db)
    bm1, acc1 = _benchmark(db, owner, "对标A")
    bm2, acc2 = _benchmark(db, owner, "对标B")
    work = Work(creator_id=bm1.id, title="同作品")
    db.add(work)
    db.commit()
    best = _post(db, acc1, "best", hours_ago=1, likes=1000)
    _post(db, acc1, "second", hours_ago=2, likes=500)
    latest = _post(db, acc1, "latest", hours_ago=0, likes=0)
    w_post = _post(db, acc1, "w", hours_ago=3, work_id=work.id)
    _post(db, acc1, "ad", hours_ago=4, likes=9999, is_ad=True)
    # 有文案：best 走本地视频、w 走同 work 视频兜底
    video_best = _add_transcript(db, "best.mp4", creator_id=bm1.id, text="best 文案")
    best.local_video_id = video_best.id
    _add_transcript(db, "w.mp4", creator_id=bm1.id, text="work 文案", work_id=work.id)
    # 分析结果：一次 IN 取两条
    db.add(Kv(key=f"ba:{owner.id}:p{best.id}", value=json.dumps({"can": True, "reason": "能讲", "suggestion": ""})))
    db.add(Kv(key=f"ba:{owner.id}:w{work.id}", value=json.dumps({"can": False, "reason": "不合适", "suggestion": ""})))
    # 第二个对标：有文案的低分帖应排在没文案的高分帖前面
    _post(db, acc2, "b-high", hours_ago=1, likes=100)
    b_low = _post(db, acc2, "b-low", hours_ago=2, likes=10)
    video_b = _add_transcript(db, "b-low.mp4", creator_id=bm2.id, text="b 文案")
    b_low.local_video_id = video_b.id
    db.commit()

    with _sql_count(db) as counter:
        result = benchmark_service.benchmarks_top(db, owner)
    assert counter["n"] <= 10, f"/top 首屏应为常数级 SQL，实际 {counter['n']} 条"

    # 旧逐条路径（保留为兼容默认参数）作为等价性基准
    legacy = []
    for bm in benchmark_service.benchmarks_of_owner(db, owner):
        picked = benchmark_service.target_units(db, bm, limit_candidates=15, with_text_first=True)
        legacy.append(
            {
                "benchmark_id": bm.id,
                "name": bm.name,
                "note": bm.note or "",
                "items": [benchmark_service.unit_payload(db, u, owner_id=owner.id) for u in picked],
            }
        )
    legacy_out = {"owner_id": owner.id, "owner_name": owner.name, "benchmarks": legacy}
    assert result == legacy_out

    items1 = result["benchmarks"][0]["items"]
    assert [item["title"] for item in items1] == [
        best.title,
        w_post.title,
        "标题-second",
        latest.title,
    ]
    assert items1[0]["has_text"] is True and items1[0]["text"] == "best 文案"
    assert items1[0]["analysis"] == {"can": True, "reason": "能讲", "suggestion": ""}
    assert items1[1]["key"] == f"w{work.id}" and items1[1]["text"] == "work 文案"
    assert items1[1]["analysis"] == {"can": False, "reason": "不合适", "suggestion": ""}
    items2 = result["benchmarks"][1]["items"]
    assert [item["title"] for item in items2] == [b_low.title, "标题-b-high"]


# ---------- S8：对标准备广告判定批量化 ----------


class _FakeBatchLLM:
    def __init__(self, results):
        self.results = results
        self.calls: list[list[dict]] = []

    def chat_json(self, messages, **_kwargs):
        self.calls.append(messages)
        if isinstance(self.results, Exception):
            raise self.results
        return self.results


def _bare_post(pid: int, title: str = "标题", is_ad: bool = False) -> PlatformPost:
    post = PlatformPost(account_id=1, platform="douyin", platform_post_id=str(pid), title=title, is_ad=is_ad)
    post.id = pid
    return post


def test_units_are_ad_single_batch_llm_and_fail_open(db, monkeypatch):
    units = [{"post": _bare_post(101, "正常内容")}, {"post": _bare_post(102, "推自家小程序")}]
    texts = ["普通口播", "快来买我的课"]

    class _Fake(_FakeBatchLLM):
        def chat_json(self, messages, **_kwargs):
            payload = json.loads(messages[1]["content"])
            self.results = {"results": [{"id": item["id"], "is_ad": item["id"] == 102} for item in payload]}
            return super().chat_json(messages, **_kwargs)

    fake = _Fake({})
    monkeypatch.setattr(benchmark_service, "_llm", lambda _db=None: fake)
    flags = benchmark_service._units_are_ad(db, units, texts)
    assert flags == {101: False, 102: True}
    assert len(fake.calls) == 1, "多条候选必须合并为一次 LLM 调用"
    assert len(json.loads(fake.calls[0][1]["content"])) == 2
    # 已标记广告不再送审（保持直接命中）
    flagged = [{"post": _bare_post(103, "已标广告", is_ad=True)}, *units]
    fake2 = _FakeBatchLLM({"results": []})
    monkeypatch.setattr(benchmark_service, "_llm", lambda _db=None: fake2)
    assert benchmark_service._units_are_ad(db, flagged, ["a", "普通口播", "快来买我的课"])[103] is True
    assert [item["id"] for item in json.loads(fake2.calls[0][1]["content"])] == [101, 102]

    # 解析失败 / LLM 异常 → 全部按 False（宁可不误杀）
    monkeypatch.setattr(benchmark_service, "_llm", lambda _db=None: _FakeBatchLLM({"results": "bad"}))
    assert benchmark_service._units_are_ad(db, units, texts) == {101: False, 102: False}
    monkeypatch.setattr(benchmark_service, "_llm", lambda _db=None: _FakeBatchLLM(RuntimeError("no key")))
    assert benchmark_service._units_are_ad(db, units, texts) == {101: False, 102: False}


def test_ensure_top_judges_ads_in_batches_and_keeps_fallback(db, monkeypatch):
    """6 条有文案候选里前两条判为广告 → 分两批（4+2）判定，广告标记落库并顺延出 4 条。"""
    owner = _owner(db)
    bm, acc = _benchmark(db, owner, "对标A")
    posts = [_post(db, acc, f"p{i}", hours_ago=i) for i in range(6)]
    db.commit()
    ad_ids = {posts[0].id, posts[2].id}
    batches: list[list[int]] = []

    def _fake_units_are_ad(_db, units, _texts):
        batches.append([u["post"].id for u in units])
        return {u["post"].id: u["post"].id in ad_ids for u in units}

    monkeypatch.setattr(benchmark_service, "_unit_text", lambda _db, _unit: "有转写文案")
    monkeypatch.setattr(benchmark_service, "_units_are_ad", _fake_units_are_ad)
    picked = benchmark_service.ensure_top_with_text(db, bm, limit_candidates=15)
    assert [len(batch) for batch in batches] == [4, 2], "典型场景按 4 条一批、最多再补一批"
    assert len(picked) == 4
    assert not {u["post"].id for u in picked} & ad_ids
    flags = {row.id: row.is_ad for row in db.query(PlatformPost).all()}
    assert flags[posts[0].id] is True and flags[posts[2].id] is True
    # 统计 map 循环外一次：picked 的 score 已按最新统计算好（无统计时 0）
    assert all(u["score"] == 0 for u in picked)


# ---------- S6：视频复盘批量预取 ----------


def _review_seed(db, *, posts: int = 6) -> tuple[Creator, CreatorAccount, PlatformPost]:
    owner = _owner(db)
    acc = CreatorAccount(creator_id=owner.id, platform="douyin", nickname="我的抖音")
    db.add(acc)
    db.commit()
    target = _post(db, acc, "target", hours_ago=0, likes=0)
    target.publish_time = _app_now() - timedelta(days=3)  # 3 天前，age=3
    for index in range(posts):
        post = _post(db, acc, f"c{index}", hours_ago=1, likes=0)
        post.publish_time = target.publish_time - timedelta(days=20 + index)
    db.commit()
    return owner, acc, target


def test_build_comparison_batch_sql_and_cutoff(db):
    """build_comparison 一次 IN 后内存按 cutoff 取最后一条：逐格查询的语义保持不变。"""
    _owner_, acc, target = _review_seed(db, posts=1)
    candidate = db.query(PlatformPost).filter_by(platform_post_id="c0").one()
    # 目标视频最新统计
    db.add(PlatformPostStat(post_id=target.id, stat_date="2026-09-21", plays=10000, likes=100))
    # 对比视频：cutoff=publish+3d，取 1000；更晚的 9999 不能被用到
    db.add(PlatformPostStat(post_id=candidate.id, stat_date=(candidate.publish_time + timedelta(days=3)).date().isoformat(), plays=1000))
    db.add(PlatformPostStat(post_id=candidate.id, stat_date=(candidate.publish_time + timedelta(days=10)).date().isoformat(), plays=9999))
    db.commit()

    with _sql_count(db) as counter:
        result = build_comparison(db, target)
    assert counter["n"] <= 8, f"build_comparison 应批量预取，实际 {counter['n']} 条 SQL"
    assert result["comparison"]["count"] == 1
    assert result["facts"]["plays"]["value"] == 10000
    assert result["facts"]["plays"]["baseline"] == 1000.0
    assert result["facts"]["plays"]["sample_count"] == 1
    assert result["overall"] == "unknown"


def test_peer_references_batches_account_posts_and_stats(db):
    """同行参考榜：窗口函数一次取各账号最新帖 + 一次统计，口径（2 倍爆款判定）不变。"""
    owner = _owner(db)
    for index in range(2):
        _bm, acc = _benchmark(db, owner, f"同行{index}")
        normal_posts = []
        for j in range(5):
            post = _post(db, acc, f"p{index}-{j}")
            post.publish_time = _app_now() - timedelta(days=10 + j)
            normal_posts.append(post)
        hit = _post(db, acc, f"hit{index}")
        hit.publish_time = _app_now() - timedelta(days=2)
        db.commit()
        for post in normal_posts:
            db.add(
                PlatformPostStat(
                    post_id=post.id,
                    stat_date=(post.publish_time + timedelta(days=1)).date().isoformat(),
                    plays=1000,
                    likes=10,
                    comments=1,
                )
            )
        db.add(
            PlatformPostStat(
                post_id=hit.id,
                stat_date=(hit.publish_time + timedelta(days=1)).date().isoformat(),
                plays=10000,
                likes=100,
                comments=5,
            )
        )
        db.commit()

    with _sql_count(db) as counter:
        items, charts = peer_references(db, owner)
    assert counter["n"] <= 6, "同行参考榜应批量取帖+统计，不再逐账号 N+1"
    assert len(items) == 2 and all(item["verdict"] == "同行爆款" for item in items)
    assert [chart["play_multiple"] for chart in charts] == [10.0, 10.0]


def test_list_videos_latest_review_and_follower_topics_batch(db):
    owner, acc, _target = _review_seed(db, posts=5)
    posts = db.query(PlatformPost).filter_by(account_id=acc.id).order_by(PlatformPost.id.desc()).all()
    candidate_posts = [post for post in posts if post.platform_post_id != "target"]
    first = posts[0]  # list_videos 按 id 倒序，第一帖就是 id 最大的候选
    db.add(VideoReview(account_id=acc.id, post_id=first.id, status="done", input_fingerprint="a"))
    db.commit()
    latest = VideoReview(account_id=acc.id, post_id=first.id, status="running", input_fingerprint="b")
    db.add(latest)
    db.commit()
    for index, post in enumerate(candidate_posts):
        db.add(PlatformPostStat(post_id=post.id, stat_date="2026-09-21", plays=1000 * (index + 1)))
        db.add(DouyinPostMetric(post_id=post.id, snapshot_date="2026-09-21", follower_gain=5 + index))
    db.commit()

    with _sql_count(db) as counter:
        data = video_review_service.list_videos(db, owner, acc.id, "", 0, 20)
    assert counter["n"] <= 10
    assert len(data["items"]) == len(posts)
    assert data["items"][0]["post_id"] == first.id
    assert data["items"][0]["latest_review_id"] == latest.id
    assert data["items"][0]["review_status"] == "running"

    with _sql_count(db) as counter:
        topics = video_review_service._follower_topics(db, acc)
    assert counter["n"] <= 4, "_follower_topics 批量后应只有 3 条 SQL"
    expected = [
        {
            "topic": post.title,
            "follower_gain": 5 + index,
            "follower_per_1k": (5 + index) / (1000 * (index + 1)) * 1000,
            "sample_count": 1,
        }
        for index, post in enumerate(candidate_posts)
    ]
    expected.sort(key=lambda item: item["follower_per_1k"], reverse=True)
    assert topics == expected[:8]


def test_low_fan_references_computes_owner_keywords_once(db):
    owner = _owner(db)
    for index in range(3):
        video = Video(filename=f"v{index}.mp4", creator_id=owner.id, main_topics='["面试"]', tags='["求职技巧"]')
        db.add(video)
    db.commit()
    for index in range(5):
        reference = DouyinReferenceVideo(
            external_post_id=f"lf-{index}",
            title=f"低粉爆款 {index} 面试技巧",
            keyword="面试",
            category_id="628",
            duration_seconds=60,
            last_seen_at=BASE - timedelta(hours=index),
        )
        db.add(reference)
    db.commit()

    with _sql_count(db) as counter:
        items = low_fan_references(db, owner, limit=20)
    assert counter["n"] <= 3, "关键词只算一次：1 条素材查询 + 1 条参考榜查询"
    assert len(items) == 5
    for item in items:
        row = db.query(DouyinReferenceVideo).filter_by(id=int(item["id"].split(":")[1])).one()
        assert item["relevance"] == relevance_for(db, owner, row, keywords=_owner_keywords(db, owner))


def test_recommend_topics_reuses_persona_context(db, monkeypatch):
    owner = _owner(db)
    acc = CreatorAccount(creator_id=owner.id, platform="douyin", nickname="我的抖音")
    db.add(acc)
    db.flush()
    video = Video(filename="mine.mp4", creator_id=owner.id, main_topics='["面试"]', tags='["求职"]')
    db.add(video)
    db.flush()
    db.add(Transcript(video_id=video.id, transcript_text="我的口播", asr_status="done"))
    db.add(PersonaTag(creator_id=owner.id, label="犀利敢说", description="直接给结论", layer="stance", status="confirmed"))
    post = _post(db, acc, "own", hours_ago=0, title="面试自我介绍怎么做")
    db.add(PlatformPostComment(post_id=post.id, platform="douyin", text="面试自我介绍应该怎么讲？", likes=8))
    db.commit()
    comments = db.query(PlatformPostComment).filter_by(post_id=post.id).all()
    facts = {key: {"state": "normal"} for key in SPEC_MAP}
    facts["plays"]["state"] = "high"
    comparison = {"facts": facts}
    peer_items = [
        {"id": "peer:1", "title": "面试反问怎么问", "verdict_evidence": {"play_multiple": 2.5}},
    ]
    low_items = [
        {"id": "low_fan:1", "title": "面试官最讨厌的一句话", "relevance": 50},
        {"id": "low_fan:2", "title": "不相关", "relevance": 10},
    ]
    calls = {"keywords": 0, "material": 0}
    orig_keywords = video_review_topics._keywords
    orig_material = video_review_topics._has_material

    def _count_keywords(db_, owner_):
        calls["keywords"] += 1
        return orig_keywords(db_, owner_)

    def _count_material(db_, owner_):
        calls["material"] += 1
        return orig_material(db_, owner_)

    monkeypatch.setattr(video_review_topics, "_keywords", _count_keywords)
    monkeypatch.setattr(video_review_topics, "_has_material", _count_material)
    with _sql_count(db) as counter:
        result = video_review_topics.recommend_topics(db, owner, post, comparison, comments, peer_items, low_items)
    assert counter["n"] <= 5, "人设关键词/素材/确认标签必须循环外各取一次"
    assert calls == {"keywords": 1, "material": 1}
    assert result["primary"] is not None
    questions = comment_questions(comments)
    total_count = sum(x["commenter_count"] for x in questions)
    total_likes = sum(x["likes"] for x in questions)
    for item in [result["primary"], *result["backups"]]:
        legacy_detail = video_review_topics._score(
            db,
            owner,
            {"topic": item["topic"], "source_types": item["source_types"]},
            comparison["facts"],
            total_count,
            total_likes,
        )
        assert item["score_detail"] == legacy_detail


# ---------- M2：重新对标按对标博主并发 ----------


def _rerun_seed(db, count: int = 4) -> tuple[Creator, list[Creator]]:
    owner = _owner(db)
    bms = []
    for index in range(count):
        bm, _acc = _benchmark(db, owner, f"对标{index}")
        bms.append(bm)
    return owner, bms


def test_rerun_benchmarks_parallel_progress_and_failure_isolation(db, monkeypatch):
    owner, bms = _rerun_seed(db, count=4)
    thread_names: set[str] = set()

    def _fake_ensure(_session, bm, limit_candidates=15):
        thread_names.add(threading.current_thread().name)
        time.sleep(0.25)
        if bm.name == "对标2":
            raise RuntimeError("mock 单博主失败")
        return [object()]

    monkeypatch.setattr(benchmark_service, "ensure_top_with_text", _fake_ensure)
    updates: list[tuple[int, str]] = []
    started = time.perf_counter()
    result = benchmark_service.rerun_benchmarks(
        db,
        owner,
        update=lambda pct, note="": updates.append((pct, note)),
        refetch=False,
    )
    elapsed = time.perf_counter() - started
    assert elapsed < 0.85, f"4 个 0.25s 任务应并发完成（串行约 1.0s+），实际 {elapsed:.2f}s"
    assert len(thread_names) > 1
    assert result["benchmark_count"] == 4 and result["ok_count"] == 3
    assert result["top_with_text_total"] == 3
    assert [row["name"] for row in result["summary"]] == [bm.name for bm in bms]  # 返回顺序不变
    failed = [row for row in result["summary"] if row["error"]]
    assert len(failed) == 1 and failed[0]["name"] == "对标2"
    assert updates[-1][0] == 99
    assert updates[-1][1].startswith("[4/4] 对标")
    assert all(note.startswith("[") for _pct, note in updates)


def test_rerun_benchmarks_budget_exceeded_aborts(db, monkeypatch):
    owner, _bms = _rerun_seed(db, count=3)
    calls = {"n": 0}

    def _fake_ensure(_session, _bm, limit_candidates=15):
        calls["n"] += 1
        time.sleep(0.05)
        raise BudgetExceeded("今日 TikHub 请求预算已用完，未发起新请求")

    monkeypatch.setattr(benchmark_service, "ensure_top_with_text", _fake_ensure)
    with pytest.raises(BudgetExceeded):
        benchmark_service.rerun_benchmarks(db, owner, refetch=False)
    assert calls["n"] >= 1
