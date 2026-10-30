"""R-241 复核：逻辑/数据幂等与并发正确性回归。

覆盖：
1. 预算原子计费：并发不超发、不丢计费；stale session 下仍精确；
2. 卡片缓存：ORM 原地编辑/同日统计更新后精确失效；重复读取零写库；
3. start_task 去重并发竞态只建一个任务；失败路径释放并发名额；
4. 证据缓存：命中返回副本、不重复调用、人设变化后 miss；
5. 同步重复执行幂等（复用 R-240 回归，确认 R-241 未破坏）。
"""

from __future__ import annotations

import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from conftest import ensure_schema, fresh_engine  # noqa: E402
from sqlalchemy import event  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

from app.core.pipeline import today_key  # noqa: E402
from app.models.kv import Kv  # noqa: E402
from app.models.platform import (  # noqa: E402
    Creator,
    CreatorAccount,
    PlatformPost,
    PlatformPostStat,
)
from app.models.task import BackgroundTask  # noqa: E402
from app.models.video import Video  # noqa: E402
from app.services import works_service  # noqa: E402
from app.tasks import start_task  # noqa: E402


def _session_factory():
    eng = fresh_engine()
    ensure_schema(eng)
    return eng, sessionmaker(bind=eng, autoflush=False, autocommit=False)


def _seed_creator(s) -> tuple[Creator, CreatorAccount]:
    owner = Creator(kind="owner", name="我", is_current=True)
    s.add(owner)
    s.commit()
    acc = CreatorAccount(
        creator_id=owner.id,
        platform="douyin",
        nickname="我的号",
        platform_user_id="u-r241",
        enabled=True,
    )
    s.add(acc)
    s.commit()
    return owner, acc


def _wait_task_status(S, task_id: int, statuses: set[str], timeout: float = 10.0) -> str:
    deadline = time.monotonic() + timeout
    last = ""
    while time.monotonic() < deadline:
        s = S()
        try:
            row = s.get(BackgroundTask, task_id)
            last = row.status if row is not None else ""
        finally:
            s.close()
        if last in statuses:
            return last
        time.sleep(0.05)
    return last


# ---------- 1) 预算原子计费 ----------


def test_budget_atomic_charge_concurrent_never_oversells() -> None:
    """20 线程并发各计 1 次、上限 5：恰好 5 次成功、15 次 BudgetExceeded，最终 used=5（不超发/不丢计费）。"""
    _eng, S = _session_factory()
    s0 = S()
    try:
        s0.add(Kv(key="tikhub_budget_limit", value="5"))
        s0.add(Kv(key=f"tikhub_budget_used:{today_key()}", value="0"))
        s0.commit()
    finally:
        s0.close()

    from app.services.platform.budget import BudgetExceeded, _charge, get_budget

    ok = 0
    failed = 0
    lock = threading.Lock()

    def _run() -> None:
        nonlocal ok, failed
        s = S()
        try:
            _charge(s, 1)
            with lock:
                ok += 1
        except BudgetExceeded:
            with lock:
                failed += 1
        except Exception:  # noqa: BLE001 其它异常视为失败但不计入超发断言
            with lock:
                failed += 1
        finally:
            s.close()

    threads = [threading.Thread(target=_run) for _ in range(20)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)

    s = S()
    try:
        assert get_budget(s)["used"] == 5, f"预算不超发失败：used={get_budget(s)['used']}"
    finally:
        s.close()
    assert ok == 5 and failed == 15, f"计费成功/失败数不对：ok={ok} failed={failed}"


def test_budget_atomic_charge_ignores_stale_session_reads() -> None:
    """两个 session 先各自预读预算，再依次计费 → 计数必须是 2（原子 SQL 不读旧值）。"""
    _eng, S = _session_factory()
    s0 = S()
    try:
        s0.add(Kv(key=f"tikhub_budget_used:{today_key()}", value="0"))
        s0.commit()
    finally:
        s0.close()

    from app.services.platform.budget import _charge, get_budget

    s1, s2 = S(), S()
    try:
        get_budget(s1)
        get_budget(s2)
        _charge(s1, 1)
        _charge(s2, 1)
    finally:
        s1.close()
        s2.close()
    s3 = S()
    try:
        assert get_budget(s3)["used"] == 2
    finally:
        s3.close()


# ---------- 2) 卡片缓存精确失效 + 读幂等 ----------


def test_cards_cache_invalidates_on_video_edit_and_stat_update() -> None:
    from app.services import library_service

    _eng, S = _session_factory()
    s = S()
    try:
        owner, acc = _seed_creator(s)
        video = Video(title="旧标题", filename="v1.mp4", creator_id=owner.id)
        s.add(video)
        s.commit()
        post = PlatformPost(
            account_id=acc.id,
            platform="douyin",
            platform_post_id="p-r241",
            title="作品",
            raw="{}",
        )
        s.add(post)
        s.commit()
        stat = PlatformPostStat(post_id=post.id, stat_date=today_key(), plays=10, likes=1)
        s.add(stat)
        s.commit()
        library_service._CARD_CACHE.clear()
        works_service._INFLIGHT.clear()

        before = library_service.build_cards(s, owner.id)
        assert any(c.get("title") == "旧标题" for c in before)

        # 视频标题原地编辑（id/条数不变）→ 下一次读取必须是新值
        video.title = "新标题"
        s.commit()
        after = library_service.build_cards(s, owner.id)
        assert any(c.get("title") == "新标题" for c in after), "视频原地编辑后卡片未刷新"

        # 同日统计原地更新（id/条数不变）→ 版本键必须前进
        from app.services.works_service import cards_version

        ver_before_stat = cards_version(s, owner.id)
        stat.likes = 999
        s.commit()
        ver_after_stat = cards_version(s, owner.id)
        assert ver_after_stat != ver_before_stat, "同日统计原地更新后版本键未前进"
    finally:
        s.close()
        library_service._CARD_CACHE.clear()
        works_service._INFLIGHT.clear()


def test_cards_read_path_is_write_free_when_warm() -> None:
    """缓存热/冷读都不得写库（GET 幂等）。"""
    from app.services import library_service

    _eng, S = _session_factory()
    s = S()
    try:
        owner, acc = _seed_creator(s)
        s.add(Video(title="素材", filename="v2.mp4", creator_id=owner.id))
        s.add(
            PlatformPost(
                account_id=acc.id,
                platform="douyin",
                platform_post_id="p-r241-w",
                title="作品",
                raw="{}",
            )
        )
        s.commit()
        library_service._CARD_CACHE.clear()
        works_service._INFLIGHT.clear()
        library_service.build_cards(s, owner.id)  # 冷：建缓存

        writes: list[str] = []
        bind = s.get_bind()

        def _before(_conn, _cursor, statement, _params, _ctx, _many):
            head = str(statement).lstrip().upper()
            if head.startswith(("INSERT", "UPDATE", "DELETE", "TRUNCATE")):
                writes.append(head[:20])

        event.listen(bind, "before_cursor_execute", _before)
        try:
            for _ in range(3):
                library_service.build_cards(s, owner.id)
        finally:
            event.remove(bind, "before_cursor_execute", _before)
            library_service._CARD_CACHE.clear()
            works_service._INFLIGHT.clear()
        assert writes == [], f"读路径出现写库：{writes}"
    finally:
        s.close()


# ---------- 3) 后台任务：去重竞态 + 失败释放名额 ----------


def test_start_task_dedupe_under_concurrent_double_click() -> None:
    """两个线程同时提交同 kind+payload：只创建一个任务（返回同一 task_id）。"""
    _eng, S = _session_factory()

    release = threading.Event()
    done = threading.Event()

    def _fn(db, payload):  # noqa: ANN001
        release.wait(5)
        done.set()

    payload = {"case": "race", "n": 1}
    results: list[int] = []
    lock = threading.Lock()

    def _call() -> None:
        tid = start_task("r241_race", payload, _fn)
        with lock:
            results.append(tid)

    t1 = threading.Thread(target=_call)
    t2 = threading.Thread(target=_call)
    t1.start()
    t2.start()
    t1.join(10)
    t2.join(10)
    assert len(results) == 2 and results[0] == results[1], f"并发双击创建了多个任务：{results}"

    release.set()
    assert done.wait(5)
    _wait_task_status(S, results[0], {"done"})
    s = S()
    try:
        assert (
            s.query(BackgroundTask)
            .filter(BackgroundTask.kind == "r241_race", BackgroundTask.status.in_(["pending", "running", "done"]))
            .count()
            == 1
        )
    finally:
        s.close()


def test_start_task_releases_slot_after_failure(monkeypatch) -> None:
    """任务函数抛异常（失败路径）也必须释放全局并发名额，后续任务可执行。"""
    import app.tasks as tasks_mod

    _eng, S = _session_factory()
    monkeypatch.setattr(tasks_mod, "_TASK_SLOTS", threading.BoundedSemaphore(1))

    def _boom(db, payload):  # noqa: ANN001
        raise RuntimeError("mock 失败")

    tid1 = start_task("r241_fail", {"case": "fail"}, _boom)
    assert _wait_task_status(S, tid1, {"failed"}) == "failed"

    ran = threading.Event()

    def _ok(db, payload):  # noqa: ANN001
        ran.set()

    tid2 = start_task("r241_after_fail", {"case": "after"}, _ok)
    assert ran.wait(5), "失败任务未释放全局并发名额，后续任务被永久阻塞"
    _wait_task_status(S, tid2, {"done"})


# ---------- 4) 证据缓存：只读、副本、人设变化 miss ----------


def test_evidence_cache_hit_is_copy_and_persona_sensitive(monkeypatch) -> None:
    from app.services import evidence

    calls: list[str] = []

    def _fake_gather(db, topic, *, material="", draft_id=None, creator_id=None, count=None, time_range="", persona="", picker=None):  # noqa: ANN001, ANN003
        calls.append(persona)
        return {
            "sources": [{"title": "来源", "url": f"https://x.com/{len(calls)}", "content": "正文"}],
            "selected": [{"title": "来源", "url": f"https://x.com/{len(calls)}", "content": "正文", "picked": True}],
            "queries": [{"query": topic}],
            "block": f"证据块{len(calls)}",
            "log_ids": [len(calls)],
            "rejected": [],
        }

    monkeypatch.setattr(evidence, "gather_online", _fake_gather)
    evidence._reset_evidence_cache()

    ev1 = evidence.gather_online_cached(
        None, "选题A", material="素材", creator_id=1, persona="人设1"
    )
    assert ev1["log_ids"] == [1]
    ev1["selected"][0]["title"] = "被调用方修改"
    ev1["log_ids"].append(999)

    ev2 = evidence.gather_online_cached(
        None, "选题A", material="素材", creator_id=1, persona="人设1"
    )
    assert len(calls) == 1, "同 key 应命中缓存、不重复调用 gather_online"
    assert ev2["selected"][0]["title"] == "来源", "缓存命中必须返回副本，调用方修改不得污染缓存"
    assert ev2["log_ids"] == [], "命中不应复用旧留痕 id（避免覆盖旧草稿的 used 归属）"

    ev3 = evidence.gather_online_cached(
        None, "选题A", material="素材", creator_id=1, persona="人设2-已变化"
    )
    assert len(calls) == 2, "人设变化后必须 miss 重新抓取"
    assert ev3["block"] == "证据块2"
    evidence._reset_evidence_cache()
