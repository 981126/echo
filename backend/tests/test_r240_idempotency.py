"""R-240 复核：写入路径幂等/并发正确性回归。

覆盖三件事：
1. 预算计数并发/多 session 下不丢更新（`budget._charge` 的 identity-map 旧值问题）；
2. 灵感池「评论→选题」在多并发消费下仍守 `ECHO_POOL_IDEAS_PER_DAY` 上限、同评论文本不重复进池；
3. 同一同步/转写动作重复执行不产生重复数据（stats/comments/topic_ideas 行数稳定；
   转写失败退避计次递增、成功后清零）。
"""

from __future__ import annotations

import sys
import threading
import time
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from conftest import ensure_schema, fresh_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

from app.core.pipeline import today_key  # noqa: E402
from app.models.hot_topic import TopicIdea  # noqa: E402
from app.models.kv import Kv  # noqa: E402
from app.models.platform import (  # noqa: E402
    Creator,
    CreatorAccount,
    PlatformPost,
    PlatformPostComment,
    PlatformPostStat,
)
from app.models.work import Work  # noqa: E402


def _session_factory():
    eng = fresh_engine()
    ensure_schema(eng)
    return sessionmaker(bind=eng, autoflush=False, autocommit=False)


def _seed_owner_and_posts(S, count: int = 6) -> tuple[int, int, list[int]]:
    s = S()
    try:
        owner = Creator(kind="owner", name="我", is_current=True)
        s.add(owner)
        s.commit()
        acc = CreatorAccount(
            creator_id=owner.id,
            platform="douyin",
            nickname="我的号",
            platform_user_id="u-idempotent",
            enabled=True,
        )
        s.add(acc)
        s.commit()
        for i in range(count):
            s.add(
                PlatformPost(
                    account_id=acc.id,
                    platform="douyin",
                    platform_post_id=f"pid-idem-{i}",
                    title=f"幂等测试帖 {i}",
                    raw="{}",
                )
            )
        s.commit()
        post_ids = [
            p.id
            for p in s.query(PlatformPost)
            .filter(PlatformPost.account_id == acc.id)
            .order_by(PlatformPost.id)
            .all()
        ]
        return owner.id, acc.id, post_ids
    finally:
        s.close()


# ---------- 1) 预算计数不丢更新 ----------


def test_budget_charge_not_lost_when_session_already_read_balance() -> None:
    """两个消费者先各自预检预算，再依次计费 → 计数必须是 2 而不是 1（防读旧值覆盖）。"""
    S = _session_factory()
    s0 = S()
    try:
        s0.add(Kv(key=f"tikhub_budget_used:{today_key()}", value="0"))
        s0.commit()
    finally:
        s0.close()

    from app.services.platform.budget import _charge, get_budget

    s1, s2 = S(), S()
    try:
        # 模拟「同一请求/同一 worker 内先 ensure_budget 预检、稍后 _charge」：两个 session 都缓存了旧值
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


# ---------- 2) 灵感池并发：守每日上限 + 不重复进池 ----------


def test_pool_ideas_concurrent_calls_respect_daily_quota(monkeypatch) -> None:
    """多消费者并发把评论写进灵感池时，同博主当天总量不得超过 ECHO_POOL_IDEAS_PER_DAY。"""
    import app.services.platform_sync as ps

    S = _session_factory()
    creator_id, account_id, post_ids = _seed_owner_and_posts(S, count=6)
    quota = 10
    monkeypatch.setattr(
        ps,
        "get_settings",
        lambda: SimpleNamespace(pool_ideas_per_day=quota, pool_ideas_per_post=8),
    )

    # 重叠检测：把 _pool_quota 人为放慢，统计「同时进入 pool_ideas_from_comments 的线程数」。
    # 修复后（进程内锁）应恒为 1；无锁时 6 个线程会重叠 → 先 COUNT 后 INSERT 的竞态窗口稳定复现。
    orig_quota = ps._pool_quota
    active = {"n": 0, "max": 0}
    active_lock = threading.Lock()

    def _slow_quota(db, cid, date_key):  # noqa: ANN001
        with active_lock:
            active["n"] += 1
            active["max"] = max(active["max"], active["n"])
        try:
            time.sleep(0.05)
            return orig_quota(db, cid, date_key)
        finally:
            with active_lock:
                active["n"] -= 1

    monkeypatch.setattr(ps, "_pool_quota", _slow_quota)

    errors: list[BaseException] = []

    def _run(post_id: int, idx: int) -> None:
        s = S()
        try:
            post = s.get(PlatformPost, post_id)
            acc = s.get(CreatorAccount, account_id)
            comments = [
                SimpleNamespace(text=f"并发唯一评论-{idx}-{j}", likes=100 - j) for j in range(8)
            ]
            ps.pool_ideas_from_comments(s, post, comments, account=acc, per_post=8)
        except BaseException as exc:  # noqa: BLE001 线程内异常收集后统一断言
            errors.append(exc)
        finally:
            s.close()

    threads = [
        threading.Thread(target=_run, args=(pid, idx)) for idx, pid in enumerate(post_ids)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=60)

    s = S()
    try:
        total = (
            s.query(TopicIdea)
            .filter(
                TopicIdea.source == "comment",
                TopicIdea.creator_id == creator_id,
                TopicIdea.snapshot_date == today_key(),
            )
            .count()
        )
    finally:
        s.close()
    assert not errors, errors
    assert active["max"] == 1, f"并发未串行化：最多同时 {active['max']} 个线程在写灵感池"
    assert total <= quota, f"并发进池超过每日上限：{total} > {quota}"


def test_pool_ideas_concurrent_same_comment_no_duplicate(monkeypatch) -> None:
    """同一评论文本被多个消费者并发处理时，灵感池只应留一条（去重不能只在单线程内生效）。"""
    import app.services.platform_sync as ps

    S = _session_factory()
    _creator_id, account_id, post_ids = _seed_owner_and_posts(S, count=6)
    monkeypatch.setattr(
        ps,
        "get_settings",
        lambda: SimpleNamespace(pool_ideas_per_day=100, pool_ideas_per_post=8),
    )
    orig_quota = ps._pool_quota
    active = {"n": 0, "max": 0}
    active_lock = threading.Lock()

    def _slow_quota(db, cid, date_key):  # noqa: ANN001
        with active_lock:
            active["n"] += 1
            active["max"] = max(active["max"], active["n"])
        try:
            time.sleep(0.05)
            return orig_quota(db, cid, date_key)
        finally:
            with active_lock:
                active["n"] -= 1

    monkeypatch.setattr(ps, "_pool_quota", _slow_quota)

    same_text = "这条评论在多个作品下都被并发采集到"
    errors: list[BaseException] = []

    def _run(post_id: int) -> None:
        s = S()
        try:
            post = s.get(PlatformPost, post_id)
            acc = s.get(CreatorAccount, account_id)
            ps.pool_ideas_from_comments(
                s,
                post,
                [SimpleNamespace(text=same_text, likes=5)],
                account=acc,
                per_post=8,
            )
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)
        finally:
            s.close()

    threads = [threading.Thread(target=_run, args=(pid,)) for pid in post_ids]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=60)

    s = S()
    try:
        rows = (
            s.query(TopicIdea)
            .filter(
                TopicIdea.source == "comment",
                TopicIdea.snapshot_date == today_key(),
                TopicIdea.title == same_text,
            )
            .count()
        )
    finally:
        s.close()
    assert not errors, errors
    assert active["max"] == 1, f"并发未串行化：最多同时 {active['max']} 个线程在写灵感池"
    assert rows == 1, f"同评论被重复进池：{rows} 条"


# ---------- 3) 同一同步动作重复执行不产生重复数据 ----------


def test_sync_work_posts_repeat_is_idempotent() -> None:
    """同一合并作品连续同步两次：评论/当天统计/灵感池行数不增（只有 job 历史与预算计数按次增加）。"""
    from app.services.platform_sync import sync_work_posts
    from app.services.works_service import auto_merge_creator

    S = _session_factory()
    s = S()
    try:
        owner = Creator(kind="owner", name="我", is_current=True)
        s.add(owner)
        s.commit()
        accs = {}
        for plat in ("douyin", "bilibili", "xiaohongshu"):
            a = CreatorAccount(
                creator_id=owner.id,
                platform=plat,
                nickname=plat,
                platform_user_id=f"idem-{plat}",
                enabled=True,
            )
            s.add(a)
            s.flush()
            accs[plat] = a
        for plat, pid in (("douyin", "dy-idem-1"), ("bilibili", "bi-idem-1"), ("xiaohongshu", "xh-idem-1")):
            s.add(
                PlatformPost(
                    account_id=accs[plat].id,
                    platform=plat,
                    platform_post_id=pid,
                    title="同一条视频三平台（幂等）",
                    raw="{}",
                )
            )
        s.commit()
        auto_merge_creator(s, owner.id)
        work = s.query(Work).first()
        assert work is not None

        first = sync_work_posts(s, work.id)
        assert first["comments_added"] == 150
        comments_1 = s.query(PlatformPostComment).count()
        stats_1 = s.query(PlatformPostStat).filter(PlatformPostStat.stat_date == today_key()).count()
        ideas_1 = s.query(TopicIdea).filter(TopicIdea.snapshot_date == today_key()).count()

        second = sync_work_posts(s, work.id)
        comments_2 = s.query(PlatformPostComment).count()
        stats_2 = s.query(PlatformPostStat).filter(PlatformPostStat.stat_date == today_key()).count()
        ideas_2 = s.query(TopicIdea).filter(TopicIdea.snapshot_date == today_key()).count()

        assert second["comments_added"] == 0
        assert comments_2 == comments_1 == 150
        assert stats_2 == stats_1 == 3
        assert ideas_2 == ideas_1
        # 灵感池标题不重复
        titles = [
            r.title
            for r in s.query(TopicIdea)
            .filter(TopicIdea.snapshot_date == today_key())
            .all()
        ]
        assert len(titles) == len(set(titles))
    finally:
        s.close()


def test_sync_local_video_metrics_repeat_is_idempotent() -> None:
    """同一素材连续「同步数据」两次：评论/当天统计行数不增。"""
    from app.models.video import Video
    from app.services.platform_sync import sync_local_video_metrics

    S = _session_factory()
    s = S()
    try:
        owner = Creator(kind="owner", name="我", is_current=True)
        s.add(owner)
        s.commit()
        accs = {}
        for plat in ("douyin", "bilibili", "xiaohongshu"):
            a = CreatorAccount(
                creator_id=owner.id,
                platform=plat,
                nickname=plat,
                platform_user_id=f"loc-{plat}",
                enabled=True,
            )
            s.add(a)
            s.flush()
            accs[plat] = a
        video = Video(title="本地素材（幂等）", filename="idem.mp4", creator_id=owner.id)
        s.add(video)
        s.flush()
        for plat, pid in (("douyin", "dy-loc-idem"), ("bilibili", "bi-loc-idem"), ("xiaohongshu", "xh-loc-idem")):
            s.add(
                PlatformPost(
                    account_id=accs[plat].id,
                    platform=plat,
                    platform_post_id=pid,
                    title="本地素材（幂等）",
                    raw="{}",
                    local_video_id=video.id,
                )
            )
        s.commit()

        first = sync_local_video_metrics(s, video)
        assert first["comments_added"] == 150
        comments_1 = s.query(PlatformPostComment).count()
        stats_1 = s.query(PlatformPostStat).filter(PlatformPostStat.stat_date == today_key()).count()

        second = sync_local_video_metrics(s, video)
        comments_2 = s.query(PlatformPostComment).count()
        stats_2 = s.query(PlatformPostStat).filter(PlatformPostStat.stat_date == today_key()).count()

        assert second["comments_added"] == 0
        assert comments_2 == comments_1 == 150
        assert stats_2 == stats_1 == 3
    finally:
        s.close()


# ---------- 4) 转写失败退避：重复失败计次递增、成功后清零 ----------


def test_asr_failure_backoff_counter_and_clear() -> None:
    from app.models.video import Video
    from app.services.ingest import (
        asr_backoff_reason,
        asr_fail_count,
        clear_asr_failure,
        record_asr_failure,
    )

    S = _session_factory()
    s = S()
    try:
        video = Video(title="转写退避测试", filename="asr-idem.mp4")
        s.add(video)
        s.commit()
        vid = video.id

        assert asr_fail_count(s, vid) == 0
        assert asr_backoff_reason(s, vid) == ""
        for expected in (1, 2, 3):
            record_asr_failure(s, vid, "网络连接超时")
            assert asr_fail_count(s, vid) == expected
        # 达到默认上限（3 次）后跳过自动转写
        assert "上限" in asr_backoff_reason(s, vid)

        clear_asr_failure(s, vid)
        assert asr_fail_count(s, vid) == 0
        assert asr_backoff_reason(s, vid) == ""
    finally:
        s.close()
