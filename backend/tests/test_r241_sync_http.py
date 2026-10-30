"""R-241 批次 3 收尾测试（离线：无真实外部 HTTP/LLM）。

覆盖：
- 预算 `_charge` 单条原子 SQL：计费正确、预算不超发（并发 20 抢 5）、超限文案/异常不变、
  每次计费只有 1 条写语句（INSERT ... ON CONFLICT DO UPDATE）；
- 同步进度 `_job_progress`：`force` 参数生效、「补全」不再是强制关键词、B 站循环依赖显式 force；
- `core/http.py` 共享 Client：同 (base_url, follow_redirects) 复用、不同维度隔离、
  `close_all` 释放、httpx.Client 被测试替换时自动重建（不跨用例复用替身）；
- TikHub `make_client` 进程级复用（不同 mode/api_key 不串）与 `_http()` 共享 client；
- DeepSeek Fetch 按 URL 缓存 1h（命中不重复抓正文；空正文不缓存）；
- `station_evidence.retrieve_station` 转写稿批量预取（查询数 ≤ 12，原 380 级 N+1）；
- 证据缓存：同 (creator_id, topic, material_hash) 命中跳过 gather_online，返回副本互不影响，
  不同素材 miss、空结果不缓存；
- `debate._evidence_and_station`：联网检索与站内检索并发（最大并发 2），返回值合并前不变。
"""

from __future__ import annotations

import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest
from conftest import ensure_schema, fresh_engine
from sqlalchemy import event
from sqlalchemy.orm import sessionmaker

from app.config import get_settings
from app.core import http as core_http
from app.models.platform import Creator, SyncJob
from app.models.video import Transcript, Video
from app.services import debate, deepseek_search, evidence, station_evidence
from app.services import platform_sync as platform_sync_mod
from app.services.platform import budget, tikhub


@pytest.fixture()
def db(tmp_path):
    eng = fresh_engine()
    ensure_schema(eng)
    session = sessionmaker(bind=eng, autoflush=False, autocommit=False)()
    yield session
    session.close()


def _make_job(db) -> SyncJob:
    job = SyncJob(job_type="daily", scope="daily", status="running")
    db.add(job)
    db.commit()
    return job


def _count_writes(db, fn) -> list[str]:
    """监听 SQL，返回执行期间的所有写语句（INSERT/UPDATE/DELETE）。"""
    eng = db.get_bind()
    statements: list[str] = []

    def _before(conn, cursor, statement, params, context, executemany):  # noqa: ANN001
        upper = statement.lstrip().upper()
        if upper.startswith(("INSERT", "UPDATE", "DELETE")):
            statements.append(statement)

    event.listen(eng, "before_cursor_execute", _before)
    try:
        fn()
    finally:
        event.remove(eng, "before_cursor_execute", _before)
    return statements


# ---------- 1) 预算原子计费 ----------


def test_budget_charge_is_single_atomic_write(db):
    budget.set_budget(db, 100)
    writes = _count_writes(db, lambda: budget._charge(db, 3))
    assert len(writes) == 1, writes  # 单条 INSERT ... ON CONFLICT DO UPDATE
    assert "INSERT INTO app_kv" in writes[0]
    assert "ON CONFLICT" in writes[0].upper()
    info = budget.get_budget(db)
    assert info["used"] == 3 and info["remaining"] == 97

    # 行已存在时继续累加（同一行 UPDATE 路径）
    writes = _count_writes(db, lambda: budget._charge(db, 2))
    assert len(writes) == 1
    assert budget.get_budget(db)["used"] == 5


def test_budget_charge_keeps_exceeded_semantics(db):
    budget.set_budget(db, 4)
    budget._charge(db, 3)
    with pytest.raises(budget.BudgetExceeded) as ei:
        budget._charge(db, 2)
    assert "今日 TikHub 请求预算已用完" in str(ei.value)
    assert "未发起新请求" in str(ei.value)
    assert budget.get_budget(db)["used"] == 3  # 超预算那次未计费（预检先抛）


def test_budget_charge_no_oversell_with_stale_session_cache(db):
    """同一 Session 先读到旧 used（identity-map 缓存），原子计费仍不得越过上限。"""
    budget.set_budget(db, 1)
    factory = sessionmaker(bind=db.get_bind(), autoflush=False, autocommit=False)
    s1, s2 = factory(), factory()
    try:
        assert budget.get_budget(s1)["used"] == 0  # s1 缓存旧值
        assert budget.get_budget(s2)["used"] == 0  # s2 也缓存旧值
        budget._charge(s1, 1)  # 0 -> 1（用完）
        with pytest.raises(budget.BudgetExceeded):
            budget._charge(s2, 1)  # 预检用的旧值 0 会放过，原子加后 2>1 → 回滚本次增量
    finally:
        s1.close()
        s2.close()
    check = factory()
    try:
        assert budget.get_budget(check)["used"] == 1  # 未超发
    finally:
        check.close()


def test_budget_charge_not_oversold_under_concurrency(db):
    budget.set_budget(db, 5)
    factory = sessionmaker(bind=db.get_bind(), autoflush=False, autocommit=False)
    ok: list[int] = []
    lock = threading.Lock()

    def _work() -> None:
        s = factory()
        try:
            budget._charge(s)
            with lock:
                ok.append(1)
        except Exception:  # noqa: BLE001 预算耗尽属预期
            pass
        finally:
            s.close()

    threads = [threading.Thread(target=_work) for _ in range(20)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    check = factory()
    try:
        info = budget.get_budget(check)
    finally:
        check.close()
    assert len(ok) == 5  # 恰好 5 次成功
    assert info["used"] == 5  # 计数不丢不超发


# ---------- 2) B 站进度防抖 / _job_progress force ----------


def test_job_progress_force_keywords_no_longer_include_buquan():
    assert "补全" not in platform_sync_mod._JOB_PROGRESS_FORCE_KEYWORDS
    assert "完成" in platform_sync_mod._JOB_PROGRESS_FORCE_KEYWORDS


def test_job_progress_debounce_and_explicit_force(db):
    job = _make_job(db)
    ps = platform_sync_mod
    ps._job_progress_pending.pop(job.id, None)
    try:
        # 阶段开始：显式 force → total 立即落库
        ps._job_progress(db, job.id, total=100, note="B站：补全 100 条缺失指标…", force=True)
        db.refresh(job)
        assert job.progress_total == 100 and job.progress_done == 0

        # 每条“补全中…”不再强制写（2s 防抖窗口内只累计）
        for i in range(1, 10):
            ps._job_progress(db, job.id, done=1, note=f"B站：补全中 {i}/100")
        db.expire_all()
        job = db.get(SyncJob, job.id)
        assert job.progress_done == 0

        # 第 10 条显式 force → 累计的 10 条一次 flush
        ps._job_progress(db, job.id, done=1, note="B站：补全中 10/100", force=True)
        db.expire_all()
        job = db.get(SyncJob, job.id)
        assert job.progress_done == 10 and job.progress_total == 100
    finally:
        ps._flush_job_progress(db, job.id)
        ps._job_progress_pending.pop(job.id, None)


# ---------- 3) 共享 HTTP Client ----------


def test_core_http_reuses_client_per_key():
    core_http.close_all()
    try:
        c1 = core_http.get_client("https://example.invalid")
        c2 = core_http.get_client("https://example.invalid")
        assert c1 is c2
        c3 = core_http.get_client("https://example.invalid", follow_redirects=True)
        assert c3 is not c1
        c4 = core_http.get_client("https://example.invalid")
        assert c4 is c1
        core_http.close_all()
        c5 = core_http.get_client("https://example.invalid")
        assert c5 is not c1  # close_all 后重建
    finally:
        core_http.close_all()


def test_core_http_rebuilds_when_httpx_client_replaced(monkeypatch):
    """测试里 monkeypatch httpx.Client 时不复用旧替身（避免跨用例串 calls/状态）。"""
    core_http.close_all()
    real_client = core_http.get_client("https://example.invalid")

    class _FakeClient:
        def __init__(self, *args, **kwargs):  # noqa: ANN002, ANN003
            self.closed = False

        def close(self):
            self.closed = True

    monkeypatch.setattr(core_http.httpx, "Client", _FakeClient)
    fake = core_http.get_client("https://example.invalid")
    assert isinstance(fake, _FakeClient) and fake is not real_client
    assert core_http.get_client("https://example.invalid") is fake  # 同一替身类内复用
    core_http.close_all()


def test_tikhub_make_client_process_cache(monkeypatch):
    tikhub._CLIENT_CACHE.clear()
    try:
        c1 = tikhub.make_client("mock")
        c2 = tikhub.make_client("mock")
        assert c1 is c2  # 进程级复用

        monkeypatch.setattr(get_settings(), "tikhub_api_key", "another-key")
        c3 = tikhub.make_client("real")
        assert c3 is not c1  # api_key 变化 → 不同实例（不串预算计数/鉴权头）
    finally:
        tikhub._CLIENT_CACHE.clear()


def test_tikhub_http_uses_shared_client():
    core_http.close_all()
    tikhub._CLIENT_CACHE.clear()
    try:
        client = tikhub.TikHubClient(mode="mock")
        shared = core_http.get_client(client.base_url, follow_redirects=True)
        assert client._http() is shared
    finally:
        core_http.close_all()
        tikhub._CLIENT_CACHE.clear()


def test_tikhub_requests_used_is_thread_local_for_budget_delta():
    """进程级单例下 requests_used 按线程隔离：并发消费者差值互不污染（预算不被多计）。"""
    client = tikhub.TikHubClient(mode="mock")
    client._bump_request()
    client._bump_request()
    assert client.requests_used == 2  # 当前线程累计

    seen: dict[str, int] = {}

    def _worker() -> None:
        before = client.requests_used
        client._bump_request()
        seen["delta"] = client.requests_used - before

    t = threading.Thread(target=_worker)
    t.start()
    t.join()

    assert seen["delta"] == 1  # 子线程差值只含自己的 1 次
    assert client.requests_used == 2  # 主线程计数不受子线程影响
    assert client.total_requests_used == 3  # 全局累计仅供观测


# ---------- 4) DeepSeek Fetch 缓存 ----------


def test_deepseek_fetch_caches_by_url(monkeypatch):
    deepseek_search._FETCH_CACHE.clear()
    monkeypatch.setattr(deepseek_search, "enabled", lambda: True)
    calls: list[str] = []

    def _fake_post(path: str, body: dict, timeout: float) -> dict:
        calls.append(str(body.get("url") or ""))
        return {"content": f"正文:{body.get('url')}"}

    monkeypatch.setattr(deepseek_search, "_post", _fake_post)
    try:
        first = deepseek_search.fetch("https://a.example/1")
        second = deepseek_search.fetch("https://a.example/1")
        assert first == second == "正文:https://a.example/1"
        assert calls == ["https://a.example/1"]  # 第二次命中缓存，不重复抓

        deepseek_search.fetch("https://a.example/2")
        assert len(calls) == 2
    finally:
        deepseek_search._FETCH_CACHE.clear()


def test_deepseek_fetch_does_not_cache_empty(monkeypatch):
    deepseek_search._FETCH_CACHE.clear()
    monkeypatch.setattr(deepseek_search, "enabled", lambda: True)
    calls: list[str] = []
    monkeypatch.setattr(
        deepseek_search,
        "_post",
        lambda path, body, timeout: calls.append(str(body.get("url"))) or {},
    )
    try:
        assert deepseek_search.fetch("https://a.example/empty") == ""
        assert deepseek_search.fetch("https://a.example/empty") == ""
        assert len(calls) == 2  # 空正文不缓存
    finally:
        deepseek_search._FETCH_CACHE.clear()


# ---------- 5) station_evidence 批量预取 ----------


def test_retrieve_station_batches_transcripts(db):
    owner = Creator(kind="owner", name="我", is_current=True)
    db.add(owner)
    db.flush()
    bm = Creator(kind="benchmark", parent_id=owner.id, name="对标A")
    db.add(bm)
    db.flush()
    for index in range(3):
        v = Video(filename=f"own{index}.mp4", title="面试反问", creator_id=owner.id, is_ad=False)
        bv = Video(filename=f"bm{index}.mp4", title="面试技巧", creator_id=bm.id, is_ad=False)
        db.add_all([v, bv])
        db.flush()
        db.add(
            Transcript(
                video_id=v.id,
                transcript_text="面试时先反问一句，主动权就回到你手里。",
                corrected_text="面试时先反问一句，主动权就回到你手里。",
                asr_status="done",
            )
        )
        db.add(
            Transcript(
                video_id=bv.id,
                transcript_text="面试官问你还有什么问题，可以反问薪资结构。",
                corrected_text="面试官问你还有什么问题，可以反问薪资结构。",
                asr_status="done",
            )
        )
    db.commit()

    eng = db.get_bind()
    statements: list[str] = []

    def _before(conn, cursor, statement, params, context, executemany):  # noqa: ANN001
        statements.append(statement)

    event.listen(eng, "before_cursor_execute", _before)
    try:
        res = station_evidence.retrieve_station(db, "面试反问薪资", creator_id=owner.id)
    finally:
        event.remove(eng, "before_cursor_execute", _before)

    assert any(item["kind"] == "asr" for item in res["author"])
    assert any(item["title"] == "面试技巧" for item in res["benchmark"])
    assert "你的" in res["block"] and "对标" in res["block"]
    # 转写稿走 2 次 IN 预取（作者/对标各一条），总量远小于原 380 级 N+1
    transcript_queries = [s for s in statements if "FROM transcripts" in s]
    assert len(transcript_queries) <= 2
    assert len(statements) <= 12, statements


# ---------- 6) 证据缓存 ----------


def _fake_evidence(topic: str, material: str = "") -> dict:
    return {
        "sources": [{"title": f"{topic}-引用", "url": "https://x.example/a"}],
        "selected": [{"title": f"{topic}-选文", "url": "https://x.example/a", "reason": "有数据"}],
        "queries": [{"provider": "doubao", "query": topic}],
        "block": f"BLOCK:{topic}",
        "log_ids": [11, 12],
        "rejected": [],
    }


def test_evidence_cache_hit_skips_gather_online(db, monkeypatch):
    evidence._reset_evidence_cache()
    calls: list[str] = []

    def _fake_gather(_db, topic, **_kwargs):
        calls.append(topic)
        return _fake_evidence(topic)

    monkeypatch.setattr(evidence, "gather_online", _fake_gather)
    try:
        kwargs = {"material": "素材正文", "creator_id": 7, "persona": "人设A", "picker": None}
        first = evidence.gather_online_cached(db, "选题A", draft_id=1, **kwargs)
        second = evidence.gather_online_cached(db, "选题A", draft_id=2, **kwargs)
        assert calls == ["选题A"]  # 命中缓存，不再联网/选文
        assert second["block"] == first["block"] == "BLOCK:选题A"
        # R-241 复核修复：命中不再返回上次 log_ids（避免 mark_logs_used 覆盖旧草稿留痕）
        assert second["log_ids"] == []
        assert second["selected"][0]["reason"] == "有数据"

        # 返回副本：修改结果不污染缓存
        second["sources"].append({"title": "污染"})
        third = evidence.gather_online_cached(db, "选题A", draft_id=3, **kwargs)
        assert len(third["sources"]) == 1

        # 素材变化 → 不同 key → miss
        evidence.gather_online_cached(db, "选题A", draft_id=4, material="素材正文2", creator_id=7, persona="人设A", picker=None)
        assert calls == ["选题A", "选题A"]

        # 不同 creator → miss
        evidence.gather_online_cached(db, "选题A", draft_id=5, material="素材正文", creator_id=8, persona="人设A", picker=None)
        assert len(calls) == 3
    finally:
        evidence._reset_evidence_cache()


def test_evidence_cache_does_not_store_empty_result(db, monkeypatch):
    evidence._reset_evidence_cache()
    calls: list[int] = []
    empty = {"sources": [], "selected": [], "queries": [], "block": "", "log_ids": [], "rejected": []}

    def _fake_gather(_db, _topic, **_kwargs):
        calls.append(1)
        return dict(empty)

    monkeypatch.setattr(evidence, "gather_online", _fake_gather)
    try:
        assert evidence.gather_online_cached(db, "无证据选题", creator_id=1)["block"] == ""
        evidence.gather_online_cached(db, "无证据选题", creator_id=1)
        assert len(calls) == 2  # 空结果不进缓存（保持无 key 时每次快速降级语义）
    finally:
        evidence._reset_evidence_cache()


# ---------- 7) debate：联网检索与站内检索并发 ----------


def test_evidence_and_station_run_concurrently(db, monkeypatch):
    state = {"active": 0, "max": 0}
    lock = threading.Lock()

    def _enter() -> None:
        with lock:
            state["active"] += 1
            state["max"] = max(state["max"], state["active"])

    def _leave() -> None:
        with lock:
            state["active"] -= 1

    def _fake_online(_db, topic, **_kwargs):
        _enter()
        time.sleep(0.15)
        _leave()
        return {
            "sources": [],
            "selected": [],
            "queries": [],
            "block": "ONLINE",
            "log_ids": [],
            "rejected": [],
        }

    def _fake_station(topic: str, creator_id: int | None):
        _enter()
        time.sleep(0.15)
        _leave()
        return {"author": [], "benchmark": [], "block": "STATION"}, {"author": [], "benchmark": []}

    monkeypatch.setattr(evidence, "gather_online_cached", _fake_online)
    monkeypatch.setattr(debate, "_retrieve_station_side", _fake_station)

    started = time.monotonic()
    ev, station, station_meta = debate._evidence_and_station(
        db,
        topic="并发选题",
        material="素材",
        draft_id=1,
        creator_id=None,
        persona="",
        picker=None,
    )
    elapsed = time.monotonic() - started

    assert state["max"] >= 2, "联网检索与站内检索应并发执行"
    assert elapsed < 0.28  # 串行需 ≥0.30s；并发约 0.15s
    assert ev["block"] == "ONLINE" and station["block"] == "STATION"
    assert station_meta == {"author": [], "benchmark": []}
