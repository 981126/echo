"""R-241 批次 3：AI/DB N+1 收尾与并行化回归。

覆盖：
- opportunity 批量平台数据（与 `metrics._platform_breakdown` / `_video_engagement` 逐条等价、SQL 常数级）；
- `_topic_attribution` 批量后输出与旧口径一致、SQL ≤10；
- `content_opportunities` 三分支并发（独立 Session、单分支失败降级、want 过滤）；
- M4 单飞等待者降级重算结果写回缓存；
- prompt_service.learning_material 批量预取后输出文案不变；
- topic_mining 平台并发抓取 + 批量去重入库（只 2 条 SQL）；
- persona.merge_full 分块并行（真并发、与串行输出一致）；
- prompt_eval errors>0 → detail.partial + reason，判定不变；
- benchmark rerun 进度中间态「计算前3+最新…」。
"""

from __future__ import annotations

import copy
import json
import sys
import threading
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest
from conftest import ensure_schema, fresh_engine
from sqlalchemy import event
from sqlalchemy.orm import sessionmaker


@pytest.fixture()
def db():
    eng = fresh_engine()
    ensure_schema(eng)
    session = sessionmaker(bind=eng, autoflush=False, autocommit=False)()
    yield session
    session.close()


@pytest.fixture(autouse=True)
def _clean_opportunity_cache():
    from app.services import opportunity

    opportunity._CACHE.clear()
    opportunity._INFLIGHT.clear()
    yield
    opportunity._CACHE.clear()
    opportunity._INFLIGHT.clear()


class _SQLCounter:
    """统计 session 绑定 engine 执行了多少 SQL（只用于单测断言查询数）。"""

    def __init__(self, engine):
        self.engine = engine
        self.count = 0
        self.writes = 0
        event.listen(engine, "before_cursor_execute", self._on)

    def _on(self, conn, cursor, statement, parameters, context, executemany):
        self.count += 1
        if not statement.lstrip().upper().startswith(("SELECT", "WITH")):
            self.writes += 1

    def stop(self) -> None:
        event.remove(self.engine, "before_cursor_execute", self._on)


# ---------- opportunity 批量平台数据 ----------


def _seed_platform_videos(db):
    """3 种绑定方式 + 指标快照兜底；返回 (owner, videos, account)。"""
    from app.models.metrics import MetricsSnapshot
    from app.models.platform import Creator, CreatorAccount, PlatformPost, PlatformPostStat
    from app.models.video import Video
    from app.models.work import Work

    owner = Creator(kind="owner", name="我", is_current=True)
    db.add(owner)
    db.commit()
    account = CreatorAccount(creator_id=owner.id, platform="douyin", nickname="主号", enabled=True)
    work = Work(creator_id=owner.id, title="跨平台作品")
    db.add_all([account, work])
    db.commit()

    videos = []
    for i in range(6):
        video = Video(
            filename=f"r241-{i}.mp4",
            title=f"素材{i}",
            creator_id=owner.id,
            status="published",
            is_ad=False,
            main_topics='["求职"]',
            tags='["面试"]',
        )
        db.add(video)
        db.flush()
        videos.append(video)
    videos[1].work_id = work.id
    videos[3].work_id = work.id
    videos[2].platform_post_id = "douyin:d2"
    db.commit()

    # v0：local_video_id 绑定；v1：work_id 绑定 B 站；v2：platform_post_id 兜底；
    # v3：local 抖音 + work B 站（两平台）；v4：仅指标快照；v5：无任何数据
    p0 = PlatformPost(
        account_id=account.id, platform="douyin", platform_post_id="d0", local_video_id=videos[0].id
    )
    p1 = PlatformPost(account_id=account.id, platform="bilibili", platform_post_id="b1", work_id=work.id)
    p2 = PlatformPost(account_id=account.id, platform="douyin", platform_post_id="d2")
    p3 = PlatformPost(
        account_id=account.id, platform="douyin", platform_post_id="d3", local_video_id=videos[3].id
    )
    db.add_all([p0, p1, p2, p3])
    db.commit()
    db.add_all(
        [
            PlatformPostStat(post_id=p0.id, stat_date="2026-10-01", plays=10, likes=1, favorites=0, comments=0),
            PlatformPostStat(post_id=p0.id, stat_date="2026-10-02", plays=100, likes=10, favorites=5, comments=2),
            PlatformPostStat(post_id=p1.id, stat_date="2026-10-01", plays=200, likes=20, favorites=2, comments=3),
            PlatformPostStat(post_id=p2.id, stat_date="2026-10-01", plays=300, likes=30, favorites=3, comments=4),
            PlatformPostStat(post_id=p3.id, stat_date="2026-10-01", plays=400, likes=40, favorites=4, comments=5),
            MetricsSnapshot(
                video_id=videos[4].id, snapshot_date="2026-10-01", plays=50, likes=5, favorites=1, comments=1
            ),
        ]
    )
    db.commit()
    db.expire_all()
    videos = db.query(Video).order_by(Video.id).all()
    return owner, videos, account


def test_platform_breakdown_map_matches_per_video(db):
    """批量 map 与逐条 `_platform_breakdown` 逐字段一致，且查询数 ≤4。"""
    from app.services.metrics import _platform_breakdown
    from app.services.opportunity import platform_breakdown_map

    _owner, videos, _account = _seed_platform_videos(db)
    counter = _SQLCounter(db.get_bind())
    try:
        batch = platform_breakdown_map(db, videos)
    finally:
        counter.stop()

    assert counter.count <= 4, f"批量 map 查询数应为常数级，实际 {counter.count}"
    assert counter.writes == 0
    for video in videos:
        assert batch[video.id] == _platform_breakdown(db, video)


def test_video_engagement_map_matches_per_video(db):
    """批量互动合计（含指标快照兜底）与逐条 `_video_engagement` 完全一致。"""
    from app.services.opportunity import _video_engagement, _video_engagement_map

    _owner, videos, _account = _seed_platform_videos(db)
    batch = _video_engagement_map(db, videos)
    for video in videos:
        assert batch[video.id] == _video_engagement(db, video)
    assert batch[videos[5].id] == 0.0  # 无平台/无快照


def test_topic_attribution_batch_matches_legacy_math(db):
    """`_topic_attribution` 批量后输出与旧逐视频口径一致，SQL ≤10。"""
    from app.models.draft import Draft
    from app.models.video import Video
    from app.services import opportunity

    owner, _videos, _account = _seed_platform_videos(db)
    db.add_all(
        [
            Draft(
                creator_id=owner.id,
                title="草稿A",
                status="done",
                tags='["求职"]',
                performance='{"totals":{"plays":1000,"likes":100,"favorites":10,"comments":5}}',
            ),
            Draft(
                creator_id=owner.id,
                title="草稿B",
                status="used",
                tags='["赚钱"]',
                performance='{"totals":{"plays":200}}',
            ),
        ]
    )
    db.commit()

    counter = _SQLCounter(db.get_bind())
    try:
        data = opportunity._topic_attribution(db, 15)
    finally:
        counter.stop()
    assert counter.count <= 10, f"attribution 应批量预取（≤10 SQL），实际 {counter.count}"
    assert counter.writes == 0

    # 旧口径：草稿 performance + 逐视频 _video_engagement 手工聚合
    expected: list[dict] = []
    by_tag: dict[str, list[float]] = {}
    for draft in db.query(Draft).filter(Draft.status.in_(["used", "done"])).all():
        perf = json.loads(draft.performance or "{}").get("totals")
        if not perf:
            continue
        eng = opportunity._engagement(perf)
        tags = opportunity._draft_tags(draft.tags)
        expected.append({"title": draft.title or "", "engagement": eng, "tags": tags})
        for tag in tags:
            by_tag.setdefault(tag, []).append(eng)
    db.expire_all()
    videos = (
        db.query(Video)
        .filter(Video.creator_id == owner.id, Video.is_ad.is_(False), Video.status == "published")
        .all()
    )
    for video in videos:
        eng = opportunity._video_engagement(db, video)
        if eng <= 0:
            continue
        tags = list(
            dict.fromkeys(
                opportunity._draft_tags(video.main_topics) + opportunity._draft_tags(video.tags)
            )
        )
        expected.append({"title": video.title or "", "engagement": eng, "tags": tags})
        for tag in tags:
            by_tag.setdefault(tag, []).append(eng)

    tag_stats = [
        {"tag": tag, "count": len(vals), "avg_engagement": round(sum(vals) / len(vals), 1)}
        for tag, vals in by_tag.items()
        if tag
    ]
    tag_stats.sort(key=lambda x: (x["avg_engagement"], x["count"]), reverse=True)
    expected.sort(key=lambda r: r["engagement"], reverse=True)
    assert data["draft_count"] == len(expected)
    assert data["by_tag"] == tag_stats[:15]
    assert data["top"] == [
        {"title": r["title"], "engagement": r["engagement"]} for r in expected[:5]
    ]
    assert data["bottom"] == [
        {"title": r["title"], "engagement": r["engagement"]} for r in expected[-5:]
    ]


# ---------- content_opportunities：三分支并发 + 降级 ----------


class _FakeSession:
    def __init__(self):
        self.closed = False

    def close(self):
        self.closed = True


def test_content_opportunities_branches_concurrent_and_degraded(monkeypatch):
    """三分支并发（barrier 证明）各自独立 Session；单分支失败只降级该分支。"""
    from app.services import opportunity

    barrier = threading.Barrier(3)
    sessions: list[_FakeSession] = []

    def _factory():
        session = _FakeSession()
        sessions.append(session)
        return session

    def _comment(db):
        barrier.wait(timeout=2)
        return {"comment_clusters": [{"title": "问1"}]}

    def _weekly(db):
        barrier.wait(timeout=2)
        return {"weekly_pack": [{"title": "包1"}]}

    def _gap(db):
        barrier.wait(timeout=2)
        raise RuntimeError("AI 挂了")

    monkeypatch.setattr(opportunity, "_content_comment_branch", _comment)
    monkeypatch.setattr(opportunity, "_content_weekly_branch", _weekly)
    monkeypatch.setattr(opportunity, "_content_gap_branch", _gap)

    out = opportunity.content_opportunities("all", session_factory=_factory)

    assert out["comment_clusters"] == [{"title": "问1"}]
    assert out["weekly_pack"] == [{"title": "包1"}]
    assert out["gap"] == [] and "AI 暂不可用" in out["gap_note"]
    assert len({id(s) for s in sessions}) == 3, "每个分支应使用独立 Session"
    assert all(s.closed for s in sessions)
    # 键顺序与旧实现一致（JSON 序列化稳定）
    assert list(out) == ["comment_clusters", "weekly_pack", "gap", "gap_note"]


def test_content_opportunities_want_filter_and_unknown(monkeypatch):
    from app.services import opportunity

    sessions: list[_FakeSession] = []

    def _factory():
        session = _FakeSession()
        sessions.append(session)
        return session

    monkeypatch.setattr(
        opportunity, "_content_weekly_branch", lambda db: {"weekly_pack": [{"title": "包1"}]}
    )
    out = opportunity.content_opportunities("weekly", session_factory=_factory)
    assert out == {"weekly_pack": [{"title": "包1"}]}
    assert len(sessions) == 1
    assert opportunity.content_opportunities("nonsense", session_factory=_factory) == {}


# ---------- M4：等待者降级重算结果写回缓存 ----------


def test_cached_waiter_degraded_result_written_back(monkeypatch):
    """等待超时的「自己算」结果也写回缓存：持续慢计算时后续请求直接命中。"""
    from app.services import opportunity

    monkeypatch.setattr(opportunity, "_INFLIGHT_WAIT", 0.05)
    calls: list[int] = []
    started = threading.Event()
    release = threading.Event()

    def fn():
        n = len(calls)
        calls.append(n)
        if n == 0:
            started.set()
            release.wait(2)
        return {"v": n}

    owner = threading.Thread(target=lambda: opportunity._cached("waiter-wb", fn))
    owner.start()
    assert started.wait(2), "首个线程应开始重算"
    first = opportunity._cached("waiter-wb", fn)  # 等 0.05s 超时 → 自己算并写缓存
    third = opportunity._cached("waiter-wb", fn)  # 命中降级写回的缓存，不再重算
    release.set()
    owner.join(timeout=5)

    assert first == {"v": 1} and third == {"v": 1}
    assert calls == [0, 1], f"降级结果应写回缓存，不应重复重算：{calls}"


# ---------- prompt_service.learning_material 批量 ----------


def test_learning_material_uses_batch_breakdown(db, monkeypatch):
    """转写文案 + 平台互动数据输出不变，且不再逐视频调用 `_platform_breakdown`。"""
    from app.models.video import Transcript, Video
    from app.services import prompt_service
    from app.services.metrics import _platform_breakdown

    _owner, videos, _account = _seed_platform_videos(db)
    db.add_all(
        [
            Transcript(video_id=videos[0].id, transcript_text="这是第一篇口播文案内容"),
            Transcript(video_id=videos[1].id, transcript_text="这是第二篇口播文案内容"),
            Transcript(video_id=videos[4].id, transcript_text="这是第三篇口播文案内容"),
        ]
    )
    db.commit()
    db.expire_all()
    videos = db.query(Video).order_by(Video.id).all()

    expected_stats: dict[int, str] = {}
    for video in videos:
        plays = likes = fav = comments = 0
        for row in _platform_breakdown(db, video):
            plays += int(row.get("plays") or 0)
            likes += int(row.get("likes") or 0)
            fav += int(row.get("favorites") or 0)
            comments += int(row.get("comments") or 0)
        expected_stats[video.id] = f"播放{plays} 赞{likes} 藏{fav} 评{comments}"

    # 批量路径不应再走逐视频 `metrics._platform_breakdown`
    def _boom(*_args, **_kwargs):
        raise AssertionError("learning_material 仍在逐视频调用 _platform_breakdown")

    monkeypatch.setattr("app.services.metrics._platform_breakdown", _boom)
    text = prompt_service.learning_material(db, 16)

    assert "作者真实口播文案" in text
    # 只校验有平台的素材统计行（v0 抖音最新统计 / v1 B 站 work 绑定）
    for video_id in (videos[0].id, videos[1].id):
        assert expected_stats[video_id] in text
    assert "播放100 赞10 藏5 评2" in text  # v0 取 10-02 最新，而非 10-01
    assert "播放200 赞20 藏2 评3" in text  # v1 work 绑定 B 站


# ---------- topic_mining：并发抓取 + 批量去重 ----------


def test_topic_mining_fetch_concurrent_and_batch_dedupe(db, monkeypatch):
    from app.services import topic_mining as tm

    barrier = threading.Barrier(3)
    items = [tm.HotItem("douyin", "标题A", "1", ""), tm.HotItem("douyin", "标题B", "2", "")]

    class _Source:
        def __init__(self, name, fail=False):
            self.name = name
            self.fail = fail

        def fetch(self):
            barrier.wait(timeout=2)  # 串行执行会 BrokenBarrierError → 用例失败
            if self.fail:
                raise RuntimeError("源挂了")
            return list(items)

    sources = [_Source("s1"), _Source("s2"), _Source("s3", fail=True)]
    monkeypatch.setattr(tm, "get_sources", lambda settings=None: sources)

    # 当天已存在「标题A」→ 只应新增「标题B」，且不覆盖旧行
    db.add(tm.HotTopic(platform="douyin", title="标题A", heat="old", url="", topic_date=tm.today_key()))
    db.commit()

    counter = _SQLCounter(db.get_bind())
    try:
        collected = tm.fetch_and_store(db, settings=types.SimpleNamespace())
    finally:
        counter.stop()

    assert [item.title for item in collected] == ["标题A", "标题B", "标题A", "标题B"]
    assert counter.count <= 4, f"入库应批量去重（≤4 SQL），实际 {counter.count}"
    rows = db.query(tm.HotTopic).order_by(tm.HotTopic.id).all()
    assert [(row.title, row.heat) for row in rows] == [("标题A", "old"), ("标题B", "2")]


# ---------- persona.merge_full 分块并行 ----------


class _MergeLLM:
    """全局合并返回空（逼出分块路径）；分块调用可等 barrier 证明并发。"""

    def __init__(self):
        self.calls: list[int] = []
        self.concurrent = False
        self.barrier: threading.Barrier | None = None

    def chat_json(self, messages, **kwargs):
        label_count = messages[1]["content"].count('"label"')
        self.calls.append(label_count)
        if label_count == 3 and self.barrier is not None:
            try:
                self.barrier.wait(timeout=2)
                self.concurrent = True
            except threading.BrokenBarrierError:
                pass
        if label_count > 3:  # 全局合并失败 → 走分块归并
            return {"tags": [], "redlines": []}
        return {"tags": [{"label": "合并标签", "description": "", "dimension": "语气"}], "redlines": []}


def _merge_parts() -> list[dict]:
    import hashlib

    return [
        {
            "tags": [
                {
                    "label": hashlib.md5(f"r241-{i}".encode()).hexdigest()[:8],
                    "description": "",
                    "dimension": "语气",
                }
            ],
            "redlines": [],
        }
        for i in range(12)
    ]


def test_merge_full_chunks_run_concurrently(monkeypatch):
    from app.services import persona as persona_mod
    from app.services.persona import PersonaService

    monkeypatch.setattr(persona_mod, "_MERGE_BATCH", 3)
    llm = _MergeLLM()
    llm.barrier = threading.Barrier(2)
    out = PersonaService(llm=llm).merge_full(_merge_parts())

    assert out["tags"], "分块归并应产出标签"
    assert llm.concurrent is True, "分块归并应并发（至少两个块同时在跑）"
    assert 3 in llm.calls


def test_merge_full_parallel_matches_serial(monkeypatch):
    from app.services import persona as persona_mod
    from app.services.persona import PersonaService

    monkeypatch.setattr(persona_mod, "_MERGE_BATCH", 3)
    parallel_llm = _MergeLLM()
    parallel = PersonaService(llm=parallel_llm).merge_full(_merge_parts())

    monkeypatch.setattr(persona_mod, "_MERGE_PARALLEL", 1)
    serial_llm = _MergeLLM()
    serial = PersonaService(llm=serial_llm).merge_full(_merge_parts())

    assert parallel == serial
    assert sorted(parallel_llm.calls) == sorted(serial_llm.calls)


# ---------- prompt_eval：partial 标记 ----------


def _seed_eval_versions(db):
    from app.models.prompt import AiPrompt

    db.add(AiPrompt(key="video_tags", version=1, content="当前启用版", status="enabled"))
    db.add(AiPrompt(key="video_tags", version=2, content="候选版", status="candidate"))
    db.commit()


def _eval_results(cand_errors: int, base_errors: int) -> dict:
    def _result(errors: int) -> dict:
        return {
            "format_rate": 1.0,
            "redline_rate": 0.0,
            "style_rate": None,
            "score": 100.0,
            "probes": 1,
            "empty": errors,
            "errors": errors,
        }

    return {"cand": _result(cand_errors), "base": _result(base_errors)}


def _patch_eval_llm(db, monkeypatch, results):
    from app.services import prompt_eval as pe

    monkeypatch.setattr(pe, "golden_set", lambda db_: {"videos": [("t", "x")], "markers": [], "redlines": []})
    monkeypatch.setattr(pe, "_probes", lambda db_, key, golden: [{"label": "p", "user": "u"}])
    monkeypatch.setattr(pe, "_run_versions", lambda *a, **k: copy.deepcopy(results))


def test_prompt_eval_partial_marked_without_changing_verdict(db, monkeypatch):
    from app.services import prompt_eval as pe

    _seed_eval_versions(db)
    _patch_eval_llm(db, monkeypatch, _eval_results(cand_errors=1, base_errors=0))
    row = pe.evaluate(db, "video_tags", 2)

    assert row is not None and row.supported is True
    assert row.candidate_score == 100.0 and row.base_score == 100.0  # 判定/评分不变
    detail = json.loads(row.detail)
    assert detail["partial"] is True
    assert "部分样本失败" in row.reason and "候选版 1 个" in row.reason


def test_prompt_eval_no_partial_when_no_errors(db, monkeypatch):
    from app.services import prompt_eval as pe

    _seed_eval_versions(db)
    _patch_eval_llm(db, monkeypatch, _eval_results(cand_errors=0, base_errors=0))
    row = pe.evaluate(db, "video_tags", 2)

    assert row is not None and row.supported is True
    detail = json.loads(row.detail)
    assert "partial" not in detail
    assert row.reason == ""


# ---------- benchmark.rerun 进度中间态 ----------


def test_rerun_progress_has_front3_middle_state(db, monkeypatch):
    from app.models.platform import Creator, CreatorAccount
    from app.services import benchmark as benchmark_mod

    owner = Creator(kind="owner", name="我", is_current=True)
    db.add(owner)
    db.commit()
    for name in ("对标A", "对标B"):
        bm = Creator(kind="benchmark", parent_id=owner.id, name=name)
        db.add(bm)
        db.commit()
        db.add(CreatorAccount(creator_id=bm.id, platform="douyin", nickname=name, enabled=True))
    db.commit()

    monkeypatch.setattr("app.services.platform_sync.sync_account", lambda *a, **k: {"posts": 0})
    monkeypatch.setattr(
        benchmark_mod, "ensure_top_with_text", lambda db_, bm, limit_candidates=15: []
    )
    updates: list[tuple[int, str]] = []
    result = benchmark_mod.rerun_benchmarks(
        db, owner, update=lambda pct, note="": updates.append((pct, note))
    )

    assert any(pct == 55 and "计算前3+最新" in note for pct, note in updates), updates
    assert updates[-1][0] == 99, "最终进度应留给 worker 收尾（99）"
    assert result["benchmark_count"] == 2 and result["ok_count"] == 2
    assert result["top_with_text_total"] == 0
