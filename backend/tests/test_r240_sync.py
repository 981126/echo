"""R-240 批次 1+2 同步/媒体链路测试（离线：TikHub/ASR/LLM 全部 mock，不联网）。

覆盖：
- S7 转写失败退避：失败分类（可重试/不可重试）、指数退避、次数上限、手动重试清零、
  媒体补齐对退避卡的跳过与一次性通知；
- M8 媒体全局池：`gather_media` 走进程级共享执行器（并发且单任务异常被收集）；
  队列轻卡优先（只调顺序不改结果）；转写成功后「校对 ∥ 预打标」并发；
- M3 同步按钮并行：`sync_work_posts` 多平台并发、`sync_local_video_metrics` 多绑定帖并发，
  响应/汇总语义不变；
- M9 同行播放量补采：从日更主链路改为独立任务入队（日更 message 不再拼接）、
  任务内部低并发 3、0.25s 降速保护保留。
"""

from __future__ import annotations

import sys
import threading
import time
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest
from conftest import ensure_schema, fresh_engine
from sqlalchemy.orm import sessionmaker

from app.config import get_settings
from app.core.timeutil import now as _app_now
from app.models.notification import Notification
from app.models.platform import Creator, CreatorAccount, PlatformPost
from app.models.task import BackgroundTask
from app.models.video import Transcript, Video
from app.models.work import Work
from app.services import douyin_creator_sync as creator_sync_mod
from app.services import ingest, media_ensure, platform_sync, sync_pool


@pytest.fixture()
def db(tmp_path):
    eng = fresh_engine()
    ensure_schema(eng)
    session = sessionmaker(bind=eng, autoflush=False, autocommit=False)()
    yield session
    session.close()


def _seed_owner(db, *platforms: str) -> tuple[Creator, dict[str, CreatorAccount]]:
    owner = Creator(kind="owner", name="我", is_current=True)
    db.add(owner)
    db.commit()
    accounts: dict[str, CreatorAccount] = {}
    for platform in platforms:
        acc = CreatorAccount(
            creator_id=owner.id,
            platform=platform,
            nickname=f"我的{platform}",
            platform_user_id=f"uid-{platform}",
            enabled=True,
            sync_frequency="daily",
        )
        db.add(acc)
        db.flush()
        accounts[platform] = acc
    db.commit()
    return owner, accounts


def _make_video(db, filename: str, creator_id: int | None = None) -> Video:
    video = Video(filename=filename, title="测试素材", creator_id=creator_id)
    db.add(video)
    db.commit()
    return video


# ---------- S7：转写失败退避 ----------


def test_classify_asr_failure_retryable_vs_permanent():
    assert ingest.classify_asr_failure("腾讯云转写等待超时，可在素材详情稍后重试") is True
    assert ingest.classify_asr_failure("网络异常: connection reset") is True
    assert ingest.classify_asr_failure("识别结果为空（未识别到有效语音）") is False
    assert ingest.classify_asr_failure("音频超过硅基流动单文件 50MB 限制") is False
    # 未知错误按可重试处理（次数用尽后照样跳过）
    assert ingest.classify_asr_failure("未知错误 XYZ") is True


def test_asr_backoff_exponential_retryable_and_reset(db):
    video = _make_video(db, "backoff-exp.mp4")
    assert ingest.asr_backoff_reason(db, video.id) == ""

    ingest.record_asr_failure(db, video.id, "网络异常：连接超时")
    assert ingest.asr_fail_count(db, video.id) == 1
    first = ingest.asr_retry_after(db, video.id)
    assert first is not None
    delta1 = first - _app_now()
    assert timedelta(hours=1, minutes=50) < delta1 < timedelta(hours=2, seconds=5)

    ingest.record_asr_failure(db, video.id, "网络异常：连接超时")
    second = ingest.asr_retry_after(db, video.id)
    assert second is not None
    delta2 = second - _app_now()
    assert timedelta(hours=3, minutes=50) < delta2 < timedelta(hours=4, seconds=5)
    assert "退避" in ingest.asr_backoff_reason(db, video.id)

    # 手动重试 / 转写成功路径清零
    ingest.clear_asr_failure(db, video.id)
    assert ingest.asr_fail_count(db, video.id) == 0
    assert ingest.asr_retry_after(db, video.id) is None
    assert ingest.asr_backoff_reason(db, video.id) == ""


def test_asr_backoff_permanent_failure_long_window_and_max_attempts(db):
    video = _make_video(db, "backoff-perm.mp4")
    ingest.record_asr_failure(db, video.id, "识别结果为空（未识别到有效语音）")
    retry_at = ingest.asr_retry_after(db, video.id)
    assert retry_at is not None
    assert retry_at - _app_now() > timedelta(days=6)  # 不可重试 → 7 天

    max_attempts = ingest._asr_max_attempts()
    for _ in range(max_attempts - 1):
        ingest.record_asr_failure(db, video.id, "识别结果为空")
    assert ingest.asr_fail_count(db, video.id) >= max_attempts
    reason = ingest.asr_backoff_reason(db, video.id)
    assert "上限" in reason and "手动重试" in reason


def test_platform_media_task_skips_transcription_in_backoff_and_notifies_once(db, tmp_path, monkeypatch):
    owner, _accounts = _seed_owner(db, "douyin")
    video = _make_video(db, "backoff-skip.mp4", creator_id=owner.id)
    (tmp_path / "backoff-skip.mp4").write_bytes(b"fake-video")
    monkeypatch.setattr(media_ensure, "_videos_dir", lambda: tmp_path)
    for _ in range(ingest._asr_max_attempts()):
        ingest.record_asr_failure(db, video.id, "网络超时")

    called: list[bool] = []

    def _boom(*_args, **_kwargs):
        called.append(True)
        raise AssertionError("退避中不应再调用 import_video_task")

    monkeypatch.setattr(ingest, "import_video_task", _boom)
    res = media_ensure.platform_media_task(db, {"video_id": video.id})
    assert res["status"] == "skipped"  # 转写退避中 → 队列计 skipped，不占 worker
    assert res["transcribed"] is False
    assert called == []
    assert db.query(Notification).count() == 1  # 达上限时一次性通知

    res2 = media_ensure.platform_media_task(db, {"video_id": video.id})
    assert res2["transcribed"] is False
    assert db.query(Notification).count() == 1  # 不重复通知


# ---------- M8：媒体全局池 + 转写后 LLM 并发 ----------


def test_gather_media_shared_executor_concurrent_and_collects_errors():
    sync_pool._reset_media_executor()
    try:
        assert sync_pool._media_executor() is sync_pool._media_executor()  # 进程级共享
        barrier = threading.Barrier(2)

        def work(n: int) -> int:
            if n == 9:
                raise ValueError("boom")
            barrier.wait(timeout=3)  # 2 个任务必须同时在跑，否则超时
            return n * 2

        start = time.monotonic()
        out = dict(sync_pool.gather_media(work, [1, 2, 9]))
        assert time.monotonic() - start < 2.0
        assert out[1] == 2 and out[2] == 4
        assert isinstance(out[9], ValueError)

        seen: list[tuple[str, int]] = []
        sync_pool.gather_media(
            lambda n: n,
            [7],
            on_result=lambda item, res: seen.append(("cb", item)),
        )
        assert ("cb", 7) in seen  # on_result 在调用线程回调
    finally:
        sync_pool._reset_media_executor()


def test_run_card_sync_queue_runs_light_cards_first(db, tmp_path, monkeypatch):
    owner, accounts = _seed_owner(db, "douyin")
    acc = accounts["douyin"]
    heavy = PlatformPost(account_id=acc.id, platform="douyin", platform_post_id="r240-heavy", title="重卡", raw="{}")
    light = PlatformPost(account_id=acc.id, platform="douyin", platform_post_id="r240-light", title="轻卡", raw="{}")
    db.add_all([heavy, light])
    db.flush()
    video = _make_video(db, "r240-light.mp4", creator_id=owner.id)
    light.local_video_id = video.id
    db.add(Transcript(video_id=video.id, transcript_text="稿", corrected_text="稿", asr_status="done"))
    task_heavy = BackgroundTask(kind="card_sync", status="running", payload="{}")
    task_light = BackgroundTask(kind="card_sync", status="running", payload="{}")
    db.add_all([task_heavy, task_light])
    db.commit()
    (tmp_path / "r240-light.mp4").write_bytes(b"x")
    monkeypatch.setattr(media_ensure, "_videos_dir", lambda: tmp_path)

    # 串行执行器替身：完整保留提交顺序，验证「轻卡优先」
    def _serial_gather_media(fn, items, on_result=None):
        results = []
        for item in list(items):
            try:
                res = fn(item)
            except Exception as exc:  # noqa: BLE001
                res = exc
            results.append((item, res))
            if on_result is not None:
                on_result(item, res)
        return results

    media_order: list[int] = []

    def _fake_comments(_session, post, **_kwargs):
        return {"added": 0, "updated": 0, "pool_added": 0}

    def _fake_media(_session, payload, update=None):
        media_order.append(int(payload.get("post_id") or 0))
        return {"status": "done", "downloaded": False, "transcribed": False}

    monkeypatch.setattr("app.services.sync_pool.gather_media", _serial_gather_media)
    monkeypatch.setattr(platform_sync, "sync_post_comments", _fake_comments)
    monkeypatch.setattr(media_ensure, "platform_media_task", _fake_media)

    stats = media_ensure.run_card_sync_queue(
        db,
        [(heavy.id, task_heavy.id), (light.id, task_light.id)],
        with_media=True,
    )
    assert media_order and media_order[0] == light.id  # 轻卡（已有文件+转写）先执行
    assert stats["comments"] == 0 and stats["errors"] == 0
    db.expire_all()
    assert db.get(BackgroundTask, task_light.id).status == "done"
    assert db.get(BackgroundTask, task_heavy.id).status == "done"


def test_import_video_task_runs_correction_and_tagging_concurrently(db, monkeypatch):
    video = _make_video(db, "r240-llm.mp4")

    class _FakeTranscriber:
        def __init__(self, settings=None, mode=None, model=None):
            pass

        def transcribe(self, _path):
            return "口播正文"

    active = {"n": 0, "max": 0}
    lock = threading.Lock()

    def _enter():
        with lock:
            active["n"] += 1
            active["max"] = max(active["max"], active["n"])

    def _leave():
        with lock:
            active["n"] -= 1

    def _fake_correct(text, source_text="", llm=None, db=None):
        _enter()
        time.sleep(0.15)
        _leave()
        return "校对后正文"

    def _fake_tags(self, text):
        _enter()
        time.sleep(0.15)
        _leave()
        return {"main_topics": ["求职"], "is_ad": False, "tags": ["产品"]}

    monkeypatch.setattr(ingest, "Transcriber", _FakeTranscriber)
    monkeypatch.setattr(ingest, "correct_transcript", _fake_correct)
    monkeypatch.setattr(ingest.PersonaService, "suggest_video_tags", _fake_tags)
    monkeypatch.setattr(ingest, "enqueue_persona_incremental", lambda db, video=None, creator_id=None: None)

    ingest.import_video_task(db, {"video_id": video.id})
    assert active["max"] >= 2, "校对与预打标应并发执行"
    db.expire_all()
    fresh = db.get(Video, video.id)
    assert fresh is not None
    assert fresh.transcript is not None
    assert fresh.transcript.transcript_text == "口播正文"
    assert fresh.transcript.corrected_text == "校对后正文"
    assert fresh.transcript.asr_status == "done"
    assert fresh.tags_confirmed is True
    assert "产品" in (fresh.tags or "")


# ---------- M3：同步按钮多平台/多帖并行 ----------


def test_sync_work_posts_parallelizes_platforms(db, monkeypatch):
    owner, accounts = _seed_owner(db, "douyin", "bilibili", "xiaohongshu")
    work = Work(creator_id=owner.id, title="并行同步作品")
    db.add(work)
    db.flush()
    posts = []
    for platform, acc in accounts.items():
        post = PlatformPost(
            account_id=acc.id,
            platform=platform,
            platform_post_id=f"r240-sync-{platform}",
            title="并行同步作品",
            raw="{}",
            work_id=work.id,
        )
        db.add(post)
        posts.append(post)
    db.commit()

    active = {"n": 0, "max": 0}
    lock = threading.Lock()

    def _fake_sync_one_post(_session, post):
        with lock:
            active["n"] += 1
            active["max"] = max(active["max"], active["n"])
        time.sleep(0.15)
        with lock:
            active["n"] -= 1
        return {
            "platform": post.platform,
            "post_id": post.id,
            "stats": {"likes": 1},
            "comments_added": 1,
            "comments_updated": 0,
            "pool_added": 0,
        }

    monkeypatch.setattr(platform_sync, "_sync_one_post", _fake_sync_one_post)
    res = platform_sync.sync_work_posts(db, work.id)

    assert sorted(res["platforms"]) == ["bilibili", "douyin", "xiaohongshu"]
    assert res["comments_added"] == 3
    assert res["stats"]["likes"] == 3
    assert active["max"] >= 2, "多平台帖应并发同步"
    db.expire_all()
    job = db.query(platform_sync.SyncJob).order_by(platform_sync.SyncJob.id.desc()).first()
    assert job is not None and job.status == "done" and job.scope == "work"


def test_sync_local_video_metrics_parallelizes_bound_posts(db, monkeypatch):
    owner, accounts = _seed_owner(db, "douyin", "bilibili", "xiaohongshu")
    video = _make_video(db, "r240-local.mp4", creator_id=owner.id)
    for platform, acc in accounts.items():
        post = PlatformPost(
            account_id=acc.id,
            platform=platform,
            platform_post_id=f"r240-local-{platform}",
            title="本地素材",
            raw="{}",
            local_video_id=video.id,
        )
        db.add(post)
    db.commit()

    active = {"n": 0, "max": 0}
    lock = threading.Lock()

    def _fake_isolated(_session, job):
        with lock:
            active["n"] += 1
            active["max"] = max(active["max"], active["n"])
        time.sleep(0.15)
        with lock:
            active["n"] -= 1
        return {
            "ok": True,
            "used_source": "public",
            "blocked": False,
            "nickname": job["platform"],
            "added": 1,
            "updated": 0,
        }

    monkeypatch.setattr(platform_sync, "_sync_local_post_isolated", _fake_isolated)
    res = platform_sync.sync_local_video_metrics(db, video)

    assert sorted(res["platforms"]) == ["bilibili", "douyin", "xiaohongshu"]
    assert res["comments_added"] == 3
    assert res["errors"] == [] and res["warnings"] == []
    assert active["max"] >= 2, "多绑定帖应并发同步"


def test_sync_local_video_metrics_blocked_account_makes_no_request(db, monkeypatch):
    from app.services.douyin_creator_sync import CredentialError

    owner, accounts = _seed_owner(db, "douyin")
    acc = accounts["douyin"]
    video = _make_video(db, "r240-blocked.mp4", creator_id=owner.id)
    post = PlatformPost(
        account_id=acc.id,
        platform="douyin",
        platform_post_id="r240-blocked",
        title="失效账号素材",
        raw="{}",
        local_video_id=video.id,
    )
    db.add(post)
    db.commit()

    def _boom(*_args, **_kwargs):
        raise AssertionError("blocked 账号不应发起第三方请求")

    monkeypatch.setattr(platform_sync, "make_source", _boom)
    monkeypatch.setattr(creator_sync_mod, "make_client", _boom)
    from app.models.video_review import DouyinCreatorCredential

    db.add(
        DouyinCreatorCredential(
            account_id=acc.id,
            cookie_value="encrypted-placeholder",
            status="invalid",
            enabled=True,
        )
    )
    db.commit()
    with pytest.raises(CredentialError):
        platform_sync.sync_local_video_metrics(db, video)


# ---------- M9：同行播放量补采移出主链路 + 低并发 ----------


def _seed_benchmarks_with_posts(db, owner: Creator, accounts_n: int = 3, posts_per_account: int = 2) -> int:
    for index in range(accounts_n):
        bm = Creator(kind="benchmark", parent_id=owner.id, name=f"对标{index}")
        db.add(bm)
        db.flush()
        acc = CreatorAccount(creator_id=bm.id, platform="douyin", nickname=f"对标{index}", enabled=True)
        db.add(acc)
        db.flush()
        for pindex in range(posts_per_account):
            db.add(
                PlatformPost(
                    account_id=acc.id,
                    platform="douyin",
                    platform_post_id=f"peer-{index}-{pindex}",
                    title=f"同行视频 {index}-{pindex}",
                    publish_time=_app_now() - timedelta(days=2),
                    raw="{}",
                )
            )
    db.commit()
    return accounts_n * posts_per_account


class _PeerStatsClient:
    """真实接口形状的假 TikHub 客户端（记录并发度，不联网）。"""

    mode = "real"

    def __init__(self) -> None:
        self.requests_used = 0
        self.active = 0
        self.max_active = 0
        self.lock = threading.Lock()

    def fetch_douyin_video_statistics(self, item_ids) -> dict:
        with self.lock:
            self.active += 1
            self.max_active = max(self.max_active, self.active)
        try:
            self.requests_used += 1
            time.sleep(0.1)  # 模拟网络耗时，制造并发窗口
            ids = item_ids if isinstance(item_ids, str) else ",".join(item_ids)
            items = [
                {
                    "aweme_id": item,
                    "play_count": 50000 + idx * 1000,
                    "digg_count": 100,
                    "comment_count": 2,
                    "share_count": 1,
                }
                for idx, item in enumerate(ids.split(","))
            ]
            return {"data": {"statistics_list": items}}
        finally:
            with self.lock:
                self.active -= 1


def test_backfill_peer_plays_low_concurrency_keeps_speed_guard(db, monkeypatch):
    owner = Creator(kind="owner", name="我", is_current=True)
    db.add(owner)
    db.commit()
    total = _seed_benchmarks_with_posts(db, owner, accounts_n=3, posts_per_account=2)
    fake_client = _PeerStatsClient()
    monkeypatch.setattr(creator_sync_mod, "make_client", lambda: fake_client)
    sleep_calls: list[float] = []
    monkeypatch.setattr(
        creator_sync_mod,
        "time",
        SimpleNamespace(sleep=lambda seconds: sleep_calls.append(seconds)),
    )

    result = creator_sync_mod.backfill_peer_plays(db, owner, force=True, concurrency=3)

    assert result["updated"] == total
    assert result["requests"] == 3  # 每批 2 个 id → 3 批
    assert fake_client.max_active >= 2, "低并发 3 应实际并行"
    assert fake_client.max_active <= 3
    assert 0.25 in sleep_calls, "必须保留 0.25s 降速保护"


def test_run_daily_sync_all_enqueues_peer_plays_task(db, monkeypatch):
    owner, _accounts = _seed_owner(db, "douyin")
    monkeypatch.setattr(get_settings(), "tikhub_mode", "real")  # mock 模式不投递补采任务
    benchmark = Creator(kind="benchmark", parent_id=owner.id, name="对标A")
    db.add(benchmark)
    db.commit()
    db.add(
        CreatorAccount(
            creator_id=benchmark.id,
            platform="douyin",
            nickname="对标A",
            platform_user_id="bm-uid",
            enabled=True,
            sync_frequency="daily",
        )
    )
    db.commit()

    monkeypatch.setattr(
        platform_sync,
        "run_sync",
        lambda _db, **kw: {"job_id": 1, "message": "ok", "accounts": [], "posts": 0, "comments": 0},
    )
    monkeypatch.setattr(
        "app.services.benchmark.maybe_start_benchmark_rerun",
        lambda _db, refetch=True: "no_sync",
    )
    started: list[dict] = []

    def _fake_start_task(kind: str, payload: dict, fn) -> int:
        started.append({"kind": kind, "payload": payload, "fn": getattr(fn, "__name__", "")})
        return 123

    monkeypatch.setattr("app.tasks.start_task", _fake_start_task)
    monkeypatch.setattr("app.tasks.find_running_task", lambda kind, payload_match=None: None)

    res = platform_sync.run_daily_sync_all(db)

    peer_tasks = [item for item in started if item["kind"] == "peer_plays_backfill"]
    assert len(peer_tasks) == 1
    assert peer_tasks[0]["payload"]["owner_id"] == owner.id
    assert peer_tasks[0]["fn"] == "peer_plays_worker"
    assert "同行播放量" not in res["message"]  # 补采结果不再进日更 message
    assert res["peer_plays"]["queued"] is True


def test_run_daily_sync_all_dedupes_running_peer_plays_task(db, monkeypatch):
    owner, _accounts = _seed_owner(db, "douyin")
    monkeypatch.setattr(get_settings(), "tikhub_mode", "real")  # mock 模式不投递补采任务

    monkeypatch.setattr(
        platform_sync,
        "run_sync",
        lambda _db, **kw: {"job_id": 1, "message": "ok", "accounts": [], "posts": 0, "comments": 0},
    )
    monkeypatch.setattr(
        "app.services.benchmark.maybe_start_benchmark_rerun",
        lambda _db, refetch=True: "no_sync",
    )
    started: list[str] = []
    monkeypatch.setattr(
        "app.tasks.start_task",
        lambda kind, payload, fn: started.append(kind) or 1,
    )
    # douyin_creator_backfill 不会触发（无创作者 Cookie → 该账号跳过），这里只让 peer 命中
    monkeypatch.setattr(
        "app.tasks.find_running_task",
        lambda kind, payload_match=None: 999 if kind == "peer_plays_backfill" else None,
    )

    res = platform_sync.run_daily_sync_all(db)

    assert "peer_plays_backfill" not in started
    assert res["peer_plays"] == {"queued": False, "dedup": True, "task_id": 999}
