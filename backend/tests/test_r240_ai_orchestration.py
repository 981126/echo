"""R-240 批次 2：AI 编排并行化 + 机会缓存 + 遗留同步 LLM 标记。

覆盖：
- S2 `prompt_eval`：候选版/当前版 × probe 合并任务池并发（独立 LLM 实例、按 (tag, idx) 回填、
  单样本失败记 errors、并发度 ≤1/建池失败回退串行）；
- M1 `pipeline` 每日流水线 / `api.prompts` 提示词自测：独立 Session 并发生成、主线程按序聚合、
  单篇失败不阻断；
- M4 `opportunity._cached` 单飞 / `comment_clusters` 缓存键去 limit / scheduler 低频预热；
- M7 遗留同步接口标记与 `refine_topic` 的 ideas 预算口径。
"""

from __future__ import annotations

import sys
import threading
import time
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest
from conftest import ensure_schema, fresh_engine
from sqlalchemy.orm import sessionmaker


@pytest.fixture()
def db():
    eng = fresh_engine()
    ensure_schema(eng)
    session = sessionmaker(bind=eng, autoflush=False, autocommit=False)()
    yield session
    session.close()


@pytest.fixture(autouse=True)
def _fresh_opportunity_cache():
    """机会缓存是进程级全局状态：每个用例前后清空，避免相互污染。"""
    from app.services import opportunity

    opportunity._CACHE.clear()
    opportunity._INFLIGHT.clear()
    yield
    opportunity._CACHE.clear()
    opportunity._INFLIGHT.clear()


# ---------- S2：prompt_eval 并发 ----------


def test_prompt_eval_collect_parallel_independent_clients_and_backfill(db, monkeypatch):
    """两版 × probe 合并成一个池：每任务独立 LLM 实例，结果按 (tag, idx) 回填，失败记 errors。"""
    from app.services import llm_router, model_settings
    from app.services import prompt_eval as pe

    clients = []

    class FakeLLM:
        def chat(self, messages, **kwargs):
            user = messages[-1]["content"]
            if "fail" in user:
                raise RuntimeError("单样本失败")
            return f"ok:{user}"

    def _from_snapshot(route, feature):
        client = FakeLLM()
        clients.append(client)
        return client

    monkeypatch.setattr(llm_router, "snapshot", lambda db_: object())
    monkeypatch.setattr(model_settings, "feature_route", lambda db_, feature: "model1")
    monkeypatch.setattr(llm_router, "llm_from_snapshot", _from_snapshot)

    contents = {"cand": "候选版", "base": "当前版"}
    probes = [
        {"label": "p0", "user": "u0"},
        {"label": "p1", "user": "u1"},
        {"label": "p2", "user": "fail"},
    ]
    buckets, errors = pe._collect_parallel(db, "video_tags", contents, probes, 3)

    assert buckets["cand"] == ["ok:u0", "ok:u1", ""]
    assert buckets["base"] == ["ok:u0", "ok:u1", ""]
    assert errors == {"cand": 1, "base": 1}
    assert len(clients) == 6  # 2 版 × 3 probe，每任务独立实例
    assert len({id(c) for c in clients}) == 6


def test_prompt_eval_parallel_equals_serial(db, monkeypatch):
    """并发评分口径/顺序与串行完全一致（含空输出与单样本失败）。"""
    from app.services import llm_router, model_settings
    from app.services import prompt_eval as pe

    def _reply(user: str) -> str:
        if user == "u2":
            raise RuntimeError("boom")
        if user == "u1":
            return ""
        return '{"main_topics":["a"],"is_ad":false,"tags":["b"]}'

    class FakeLLM:
        def chat(self, messages, **kwargs):
            return _reply(messages[-1]["content"])

    monkeypatch.setattr(llm_router, "snapshot", lambda db_: object())
    monkeypatch.setattr(model_settings, "feature_route", lambda db_, feature: "model1")
    monkeypatch.setattr(llm_router, "llm_from_snapshot", lambda route, feature: FakeLLM())
    monkeypatch.setattr(pe, "_eval_llm", lambda db_, key: (FakeLLM(), "model1"))

    contents = {"cand": "cand", "base": "base"}
    probes = [{"label": str(i), "user": f"u{i}"} for i in range(3)]
    markers = ["口头禅"]
    redlines = ["红线"]

    monkeypatch.setattr(pe, "get_settings", lambda: types.SimpleNamespace(prompt_eval_concurrency=3))
    parallel = pe._run_versions(db, "video_tags", contents, probes, markers, redlines)
    monkeypatch.setattr(pe, "get_settings", lambda: types.SimpleNamespace(prompt_eval_concurrency=1))
    serial = pe._run_versions(db, "video_tags", contents, probes, markers, redlines)

    assert parallel == serial
    assert parallel["cand"]["errors"] == 1 and parallel["cand"]["empty"] == 2
    assert parallel["cand"]["score"] == serial["cand"]["score"]


def test_prompt_eval_parallel_pool_failure_falls_back_to_serial(db, monkeypatch):
    """建池失败 → 回退串行路径，评分照常产出。"""
    from app.services import llm_router, model_settings
    from app.services import prompt_eval as pe

    class FakeLLM:
        def chat(self, messages, **kwargs):
            return '{"main_topics":["a"],"is_ad":false,"tags":["b"]}'

    monkeypatch.setattr(llm_router, "snapshot", lambda db_: object())
    monkeypatch.setattr(model_settings, "feature_route", lambda db_, feature: "model1")
    monkeypatch.setattr(llm_router, "llm_from_snapshot", lambda route, feature: FakeLLM())
    monkeypatch.setattr(pe, "_eval_llm", lambda db_, key: (FakeLLM(), "model1"))
    monkeypatch.setattr(pe, "get_settings", lambda: types.SimpleNamespace(prompt_eval_concurrency=3))

    def _boom(*_a, **_k):
        raise RuntimeError("线程池不可用")

    monkeypatch.setattr(pe, "ThreadPoolExecutor", _boom)

    result = pe._run_versions(db, "video_tags", {"cand": "c"}, [{"label": "p", "user": "u"}], [], [])
    assert result["cand"]["format_rate"] == 1.0
    assert result["cand"]["probes"] == 1


# ---------- M1：每日流水线并发生成 ----------


def _pipeline_candidates() -> list[dict]:
    return [
        {"title": "选题A", "platform": "ai", "score": 3, "reason": "ra", "slot": "ai"},
        {"title": "选题B", "platform": "comment", "score": 2, "reason": "rb", "slot": "comment"},
        {"title": "选题C", "platform": "hot", "score": 1, "reason": "rc", "slot": "hot"},
    ]


def _pipeline_no_side_channels(monkeypatch, pl):
    monkeypatch.setattr(pl, "fetch_and_store", lambda *_a, **_k: [])
    monkeypatch.setattr(pl, "send_daily_digest", lambda *_a, **_k: True)
    monkeypatch.setattr(pl, "push_daily_best", lambda *_a, **_k: None)


def test_pipeline_generates_candidates_concurrently(db, monkeypatch):
    """多篇候选并发生成：每篇独立 Session，主线程按原顺序写 TopicCandidate。"""
    from app.models.draft import Draft
    from app.models.hot_topic import TopicCandidate
    from app.services import pipeline as pl

    _pipeline_no_side_channels(monkeypatch, pl)
    monkeypatch.setattr(pl, "_compose_daily_candidates", lambda *_a, **_k: _pipeline_candidates())
    monkeypatch.setattr(pl, "get_settings", lambda: types.SimpleNamespace(pipeline_generate_concurrency=2))

    sessions: list = []
    thread_names: list[str] = []
    lock = threading.Lock()

    def _fake_generate(session, topic, settings=None):
        time.sleep(0.02)
        draft = Draft(title=topic, script="正文", source="ai")
        session.add(draft)
        session.commit()
        session.refresh(draft)
        with lock:
            sessions.append(session)  # 持有对象引用，避免 id 被回收复用
            thread_names.append(threading.current_thread().name)
        return draft

    monkeypatch.setattr(pl, "generate_draft", _fake_generate)
    run = pl.run_daily_pipeline(db, force=True)

    assert run.status == "done" and run.generated_count == 3
    assert len({id(item) for item in sessions}) == 3, "每篇生成必须使用独立 Session"
    assert all(item is not db for item in sessions)
    assert all(name.startswith("echo-sync") for name in thread_names), "生成应发生在并发池线程"
    rows = db.query(TopicCandidate).order_by(TopicCandidate.id).all()
    assert [r.title for r in rows] == ["选题A", "选题B", "选题C"]  # 主线程按原顺序落库
    assert all(r.draft_id is not None for r in rows)


def test_pipeline_single_failure_keeps_other_drafts(db, monkeypatch):
    """单篇失败不阻断其余：已生成的稿子保留，失败原因进 run.error。"""
    from app.models.draft import Draft
    from app.models.hot_topic import TopicCandidate
    from app.services import pipeline as pl

    _pipeline_no_side_channels(monkeypatch, pl)
    monkeypatch.setattr(pl, "_compose_daily_candidates", lambda *_a, **_k: _pipeline_candidates())
    monkeypatch.setattr(pl, "get_settings", lambda: types.SimpleNamespace(pipeline_generate_concurrency=2))

    def _fake_generate(session, topic, settings=None):
        if "坏" in topic:
            raise RuntimeError("模型不可用")
        draft = Draft(title=topic, script="正文", source="ai")
        session.add(draft)
        session.commit()
        session.refresh(draft)
        return draft

    monkeypatch.setattr(pl, "generate_draft", _fake_generate)
    candidates = _pipeline_candidates()
    candidates[1]["title"] = "坏选题"
    monkeypatch.setattr(pl, "_compose_daily_candidates", lambda *_a, **_k: candidates)

    run = pl.run_daily_pipeline(db, force=True)

    assert run.status == "done" and run.generated_count == 2
    assert "生成失败" in run.error and "坏选题" in run.error
    rows = db.query(TopicCandidate).order_by(TopicCandidate.id).all()
    assert [r.title for r in rows] == ["选题A", "选题C"]


def test_pipeline_all_fail_marks_failed(db, monkeypatch):
    """全部篇失败仍按原语义判整轮 failed（不掩盖总失败）。"""
    from app.models.pipeline import PipelineRun
    from app.services import pipeline as pl

    _pipeline_no_side_channels(monkeypatch, pl)
    monkeypatch.setattr(pl, "_compose_daily_candidates", lambda *_a, **_k: _pipeline_candidates())
    monkeypatch.setattr(pl, "get_settings", lambda: types.SimpleNamespace(pipeline_generate_concurrency=2))
    monkeypatch.setattr(pl, "send_failure_alert", lambda *_a, **_k: False)

    def _boom(session, topic, settings=None):
        raise RuntimeError("模型全挂")

    monkeypatch.setattr(pl, "generate_draft", _boom)
    with pytest.raises(pl.PipelineError):
        pl.run_daily_pipeline(db, force=True)
    run = db.query(PipelineRun).order_by(PipelineRun.id.desc()).first()
    assert run is not None and run.status == "failed"


# ---------- M1：提示词自测并发生成 ----------


def _seed_selfcheck(db, count: int = 3) -> None:
    from app.models.draft import Draft
    from app.models.feedback import Feedback
    from app.models.hot_topic import TopicCandidate

    for i in range(count):
        draft = Draft(title=f"金样本稿{i}", script="正文", source="ai", status="done")
        db.add(draft)
        db.flush()
        db.add(Feedback(draft_id=draft.id, rating=5))
        db.add(
            TopicCandidate(
                run_date="2026-10-30",
                title=f"金选题{i}",
                platform="ai",
                score=1,
                slot="ai",
                reason="金样本",
                draft_id=draft.id,
            )
        )
    db.commit()


def test_prompt_selfcheck_generates_concurrently(db, monkeypatch):
    """金样本自测：多篇独立 Session 并发生成，主线程按原通知口径统计 made。"""
    from app.api import prompts as prompts_api
    from app.models.notification import Notification

    _seed_selfcheck(db)
    monkeypatch.setattr("app.config.get_settings", lambda: types.SimpleNamespace(prompt_selfcheck_concurrency=3))

    sessions: list = []
    thread_names: list[str] = []
    lock = threading.Lock()

    def _fake_generate(session, topic, snapshot=True, **kwargs):
        time.sleep(0.01)
        with lock:
            sessions.append(session)  # 持有对象引用，避免 id 被回收复用
            thread_names.append(threading.current_thread().name)

    monkeypatch.setattr("app.services.generation.generate_draft", _fake_generate)

    prompts_api._selfcheck_task(db, {"version": 7})

    row = db.query(Notification).filter(Notification.kind == "prompt_selfcheck").one()
    assert "生成 3 篇" in row.message
    assert len({id(item) for item in sessions}) == 3 and all(item is not db for item in sessions)
    assert all(name.startswith("echo-sync") for name in thread_names)


def test_prompt_selfcheck_single_failure_does_not_block(db, monkeypatch):
    """单篇自测失败不阻断其余，通知里的 made 数按成功篇数统计。"""
    from app.api import prompts as prompts_api
    from app.models.notification import Notification

    _seed_selfcheck(db)
    monkeypatch.setattr("app.config.get_settings", lambda: types.SimpleNamespace(prompt_selfcheck_concurrency=3))

    def _fake_generate(session, topic, snapshot=True, **kwargs):
        if "金选题1" in topic:
            raise RuntimeError("模型不可用")

    monkeypatch.setattr("app.services.generation.generate_draft", _fake_generate)

    prompts_api._selfcheck_task(db, {"version": 8})

    row = db.query(Notification).filter(Notification.kind == "prompt_selfcheck").one()
    assert "生成 2 篇" in row.message


# ---------- M4：机会缓存单飞 + 缓存键去 limit + 预热 ----------


def test_cached_single_flight_computes_once():
    """缓存过期时并发请求只允许一个线程重算，其余线程等结果（防击穿）。"""
    from app.services import opportunity

    calls: list[int] = []
    started = threading.Event()
    result: list[dict] = []

    def fn():
        calls.append(1)
        started.set()
        time.sleep(0.2)
        return {"value": 1}

    worker = threading.Thread(target=lambda: result.append(opportunity._cached("single", fn)))
    worker.start()
    assert started.wait(2.0), "首个线程应开始重算"
    second = opportunity._cached("single", fn)  # 主线程等首线程结果，不再自己重算
    worker.join(timeout=5)

    assert calls == [1], "并发未命中只应重算一次"
    assert second == {"value": 1} and result == [{"value": 1}]


def test_cached_waiter_timeout_degrades_to_own_compute(monkeypatch):
    """等待上限超时 → 降级自己算（fail-open，不阻塞请求）。"""
    from app.services import opportunity

    monkeypatch.setattr(opportunity, "_INFLIGHT_WAIT", 0.05)
    calls: list[int] = []
    started = threading.Event()
    release = threading.Event()

    def fn():
        n = len(calls)
        calls.append(1)
        if n == 0:
            started.set()
            release.wait(2.0)
        return {"value": n}

    worker = threading.Thread(target=lambda: opportunity._cached("slow", fn))
    worker.start()
    assert started.wait(2.0)

    value = opportunity._cached("slow", fn)  # 等 0.05s 超时后自己算（第二次 fn 立即返回）
    release.set()
    worker.join(timeout=5)

    assert value == {"value": 1}
    assert len(calls) == 2


def _seed_comment_ideas(db, count: int = 4) -> None:
    from app.models.hot_topic import TopicIdea

    titles = ["试用期被裁怎么办？", "怎么谈薪资", "简历空窗期怎么解释", "面试穿什么合适"]
    for i, title in enumerate(titles[:count]):
        db.add(
            TopicIdea(
                source="comment",
                platform="douyin",
                title=title,
                detail="",
                snapshot_date="2026-10-30",
                likes=10 - i,
                used=False,
            )
        )
    db.commit()


def test_comment_clusters_cache_key_ignores_limit(db, monkeypatch):
    """本地聚类缓存按全量算：不同 limit 复用同一份，读取时切片。"""
    from app.services import opportunity

    _seed_comment_ideas(db)
    calls: list[int] = []
    real = opportunity._comment_clusters
    monkeypatch.setattr(
        opportunity, "_comment_clusters", lambda db_, limit: calls.append(limit) or real(db_, limit)
    )

    small = opportunity.comment_clusters(db, limit=1)
    big = opportunity.comment_clusters(db, limit=100)

    assert calls == [opportunity._SCAN_LIMIT], "第二次不同 limit 不应重算"
    assert len(small["clusters"]) == 1
    assert len(big["clusters"]) == 4
    assert big["total_comments"] == small["total_comments"] == 4


def test_comment_clusters_llm_cache_key_ignores_limit(db, monkeypatch):
    """use_llm=True 的缓存（6h）同样与 limit 解耦，模型不可用时回退本地聚类。"""
    from app.services import opportunity

    _seed_comment_ideas(db)
    calls: list[int] = []
    real = opportunity._llm_comment_clusters
    monkeypatch.setattr(
        opportunity, "_llm_comment_clusters", lambda db_, limit: calls.append(limit) or real(db_, limit)
    )
    monkeypatch.setattr(opportunity, "_ask_groups", lambda listing, deadline: [])

    small = opportunity.comment_clusters(db, limit=1, use_llm=True)
    big = opportunity.comment_clusters(db, limit=100, use_llm=True)

    assert calls == [opportunity._SCAN_LIMIT], "第二次不同 limit 不应重跑模型聚类"
    assert len(small["clusters"]) == 1
    assert len(big["clusters"]) == 4


def test_scheduler_registers_opportunity_warm_job(monkeypatch):
    """scheduler 注册低频预热 job（按 TTL/2 周期刷 ledger/attribution）。"""
    import app.scheduler as sch

    jobs: list[tuple] = []

    class FakeSched:
        def add_job(self, fn, trigger, **kw):
            jobs.append((fn.__name__, kw.get("id"), trigger))

        def start(self):
            pass

    monkeypatch.setattr(sch, "BackgroundScheduler", lambda *a, **k: FakeSched())
    monkeypatch.setattr(
        sch,
        "get_settings",
        lambda: types.SimpleNamespace(
            daily_push_time="07:00", tz="Asia/Shanghai", platform_sync_times="06:00,17:00"
        ),
    )
    monkeypatch.setattr(sch, "_scheduler", None)
    sch.setup_scheduler()

    names = [(name, job_id) for name, job_id, _trigger in jobs]
    assert ("_warm_opportunity_caches", "warm_opportunity_caches") in names


def test_opportunity_warm_job_is_best_effort(monkeypatch):
    """预热 job 成功时刷两个缓存；失败只记日志、不抛异常（不告警）。"""
    import app.scheduler as sch
    from app.services import opportunity

    calls: list[str] = []
    monkeypatch.setattr(opportunity, "ledger", lambda db, limit=50: calls.append("ledger") or {})
    monkeypatch.setattr(
        opportunity, "topic_attribution", lambda db, limit=15: calls.append("attribution") or {}
    )
    sch._warm_opportunity_caches()
    assert calls == ["ledger", "attribution"]

    def _boom(*_a, **_k):
        raise RuntimeError("db 挂了")

    monkeypatch.setattr(opportunity, "ledger", _boom)
    sch._warm_opportunity_caches()  # 不抛异常（best-effort）


def test_ask_groups_passes_timeout_seconds_to_llm(monkeypatch):
    """M6 收尾：语义聚类的软超时预算下传给单次 LLM 调用（min(_LLM_DEADLINE, deadline)）。"""
    from app.services import opportunity
    from app.services import persona as persona_mod

    captured: list[dict] = []

    class FakePersonaService:
        def call_json(self, feature, messages, **kwargs):
            captured.append({"feature": feature, **kwargs})
            return {"groups": []}

    monkeypatch.setattr(persona_mod, "PersonaService", FakePersonaService)

    assert opportunity._ask_groups("1. 怎么谈薪资", opportunity._LLM_DEADLINE) == []
    assert opportunity._ask_groups("1. 怎么谈薪资", 40.0) == []
    assert [c["timeout_seconds"] for c in captured] == [100, 40]
    assert {c["feature"] for c in captured} == {"ideas"}


def test_ask_groups_soft_timeout_still_falls_back_to_local(db, monkeypatch):
    """软超时只返回空（不抛异常）→ 调用方仍回退本地聚类，语义不变。"""
    from app.services import opportunity
    from app.services import persona as persona_mod

    class HangingPersonaService:
        def call_json(self, feature, messages, **kwargs):
            time.sleep(0.2)
            return {"groups": []}

    monkeypatch.setattr(persona_mod, "PersonaService", HangingPersonaService)
    assert opportunity._ask_groups("1. 怎么谈薪资", 0.05) == []  # Future.result 软超时 → 空

    _seed_comment_ideas(db)
    res = opportunity.comment_clusters(db, limit=15, use_llm=True)
    assert res["engine"] == "local"  # 模型无结果 → 回退本地聚类


# ---------- M7：遗留同步 LLM 接口标记 ----------


def test_legacy_sync_llm_endpoints_are_marked():
    """M7：遗留同步 LLM 接口只加注释标记，不改契约。"""
    from app.api import drafts as drafts_api
    from app.api import inspiration as inspiration_api

    assert "遗留同步接口" in (drafts_api.generate.__doc__ or "")
    assert "遗留同步" in (inspiration_api.develop_note.__doc__ or "")


def test_refine_topic_uses_ideas_feature_budget(monkeypatch):
    """M7：`refine_topic` 的 LLM 功能名走 `ideas`（M6 的 30s 预算），失败仍回退原文。"""
    from app.services import inspiration

    captured: dict[str, str] = {}

    class FakeLLM:
        def chat(self, messages, **kwargs):
            return "  如何谈薪  \n"

    def _fake_primary(db, feature):
        captured["feature"] = feature
        return FakeLLM()

    monkeypatch.setattr(inspiration.llm_router, "primary_llm", _fake_primary)
    assert inspiration.refine_topic(None, "随手记内容") == "如何谈薪"
    assert captured["feature"] == "ideas"

    monkeypatch.setattr(
        inspiration.llm_router, "primary_llm", lambda db, feature: (_ for _ in ()).throw(RuntimeError("挂了"))
    )
    assert inspiration.refine_topic(None, "随手记内容") == "随手记内容"
