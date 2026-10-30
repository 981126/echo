"""R-241 读路径收尾（S5 卡片精确失效/单飞/by-post 直查/列瘦身 + creator-summary 批量）。

覆盖：
- `cards_version` 精确化：videos.updated_at（视频原地编辑）、platform_post_stats.updated_at
  （同日统计原地更新）都会改变版本键；stats 组按 creator 作用域（别人更新不让本 creator 失效）；
  仍为 4 条便宜聚合；
- 端到端「编辑后下一次 GET 立即新值」（视频标题 / 同日统计），不再等 20s TTL；
- 单飞：缓存过期瞬间 N 并发只重建 1 次；等待超时降级各自构建；构建异常清理 inflight 不死锁；
  命中返回浅拷贝；
- `/api/works/by-post/{id}` 直查（不重建全量 list_works），输出与旧「list_works + 扫描」逐字段一致；
- `_cloud_cards` 列瘦身：不加载 platform_posts.raw 等大字段，输出与全列加载完全一致；
- `creator-summary`：703 条 N+1 → 5 条批量 SQL，输出与旧实现逐字段一致（含账号顺序/median/爆款数）。
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
from sqlalchemy.orm import Load, sessionmaker

from app.api.platform import creator_summary
from app.models.platform import (
    Creator,
    CreatorAccount,
    CreatorAccountSnapshot,
    PlatformPost,
    PlatformPostStat,
)
from app.models.video import Video
from app.models.work import Work
from app.services import library_service, works_service


@pytest.fixture()
def db(tmp_path):
    eng = fresh_engine()
    ensure_schema(eng)
    session = sessionmaker(bind=eng, autoflush=False, autocommit=False)()
    yield session
    session.close()


@pytest.fixture(autouse=True)
def _clear_process_caches(monkeypatch):
    """进程内卡片缓存跨用例共享：用例前后清空缓存 + inflight + 等待上限恢复默认。"""

    def _clear() -> None:
        library_service._CARD_CACHE.clear()
        works_service._CARD_CACHE.clear()
        works_service._WORKS_CACHE.clear()
        works_service._INFLIGHT.clear()
        monkeypatch.setattr(works_service, "_INFLIGHT_WAIT", 2.0)

    _clear()
    yield
    _clear()


@contextmanager
def _capture_sql(db):
    """捕获上下文内执行的 SQL 语句列表（R-241 验收：查询数/列瘦身）。"""
    statements: list[str] = []
    bind = db.get_bind()

    def _before(_conn, _cursor, statement, _parameters, _context, _executemany):
        statements.append(statement)

    event.listen(bind, "before_cursor_execute", _before)
    try:
        yield statements
    finally:
        event.remove(bind, "before_cursor_execute", _before)


def _creator(db, name="我", *, kind="owner", parent_id=None, is_current=False) -> Creator:
    creator = Creator(kind=kind, name=name, parent_id=parent_id, is_current=is_current)
    db.add(creator)
    db.commit()
    return creator


def _account(db, creator: Creator, platform: str = "douyin", *, enabled: bool = True, nickname: str = "") -> CreatorAccount:
    account = CreatorAccount(
        creator_id=creator.id, platform=platform, nickname=nickname or f"{creator.name}-{platform}", enabled=enabled
    )
    db.add(account)
    db.commit()
    return account


def _post(db, account: CreatorAccount, pid: str, *, publish_time: datetime | None = None, title: str = "", work_id: int | None = None, **kw) -> PlatformPost:
    post = PlatformPost(
        account_id=account.id,
        platform=kw.pop("platform", account.platform),
        platform_post_id=pid,
        title=title or f"标题-{pid}",
        publish_time=publish_time or datetime(2026, 9, 1, 12, 0, 0),
        work_id=work_id,
        raw=kw.pop("raw", "{}"),
        **kw,
    )
    db.add(post)
    db.commit()
    return post


def _stat(db, post: PlatformPost, *, stat_date: str = "2026-09-02", plays: int = 1000, likes: int = 10) -> PlatformPostStat:
    stat = PlatformPostStat(post_id=post.id, stat_date=stat_date, plays=plays, likes=likes, comments=1)
    db.add(stat)
    db.commit()
    return stat


def _video(db, creator_id: int, filename: str, *, title: str = "", **kw) -> Video:
    video = Video(filename=filename, creator_id=creator_id, title=title or filename, **kw)
    db.add(video)
    db.commit()
    return video


# ---------- S5：版本键精确化 ----------


def test_cards_version_detects_video_in_place_edit(db):
    """视频标题/标签等原地编辑（id/条数不变）也必须改变版本键（videos.updated_at）。"""
    owner = _creator(db)
    _video(db, owner.id, "v1.mp4", title="旧标题")
    owner_id = owner.id  # 先取标量：避免在 SQL 捕获里触发主 Session 的 expire 懒加载而多出一条 SELECT
    with _capture_sql(db) as statements:
        before = works_service.cards_version(db, owner_id)
    assert len(statements) == 4, "版本键应保持 4 条便宜聚合"
    assert before[4] == 1 and before[6] is not None and before[7] is not None  # videos count/created/updated

    video = db.query(Video).filter(Video.filename == "v1.mp4").one()
    video.title = "新标题"
    db.commit()
    after = works_service.cards_version(db, owner_id)
    assert after != before
    assert after[7] != before[7], "videos.updated_at 组必须前进"


def test_cards_version_detects_same_day_stat_update_and_is_creator_scoped(db):
    """同日统计原地更新精确失效；stats 组按 creator 作用域，别人更新不影响本 creator。"""
    owner = _creator(db)
    bm = _creator(db, "对标", kind="benchmark", parent_id=owner.id)
    owner_acc = _account(db, owner, "douyin")
    bm_acc = _account(db, bm, "douyin")
    owner_post = _post(db, owner_acc, "own-1")
    bm_post = _post(db, bm_acc, "bm-1")
    owner_stat = _stat(db, owner_post, stat_date="2026-10-01", plays=100)
    bm_stat = _stat(db, bm_post, stat_date="2026-10-01", plays=200)

    owner_version = works_service.cards_version(db, owner.id)
    global_version = works_service.cards_version(db, None)
    bm_version = works_service.cards_version(db, bm.id)

    # 同一 creator 的同一日统计原地更新 → 精确失效（stats_updated 前进）
    owner_stat.plays = 999
    db.commit()
    owner_after = works_service.cards_version(db, owner.id)
    assert owner_after != owner_version
    assert owner_after[11] != owner_version[11], "platform_post_stats.updated_at 组必须前进"
    assert owner_after[10] == owner_version[10], "stats 计数不变，变化的应是 updated_at"

    # 别的 creator 更新统计 → 本 creator 版本不变（按 creator 作用域），全局版本变化
    bm_stat.plays = 888
    db.commit()
    assert works_service.cards_version(db, owner.id) == owner_after
    assert works_service.cards_version(db, bm.id) != bm_version
    assert works_service.cards_version(db, None) != global_version


def test_library_page_reflects_edits_immediately(db):
    """编辑视频标题 / 同日统计后，下一次 GET 立即返回新值（不再有 20s TTL 盲区）。"""
    owner = _creator(db)
    acc = _account(db, owner, "douyin")
    video = _video(db, owner.id, "v1.mp4", title="旧标题")
    post = _post(db, acc, "p-1", title="云端作品", publish_time=datetime(2026, 9, 2, 12, 0, 0))
    stat = _stat(db, post, stat_date="2026-09-03", plays=100, likes=1)

    first = library_service.page(db, creator_id=owner.id, limit=20)
    titles = [item["title"] for item in first["items"]]
    assert "旧标题" in titles
    cloud = next(item for item in first["items"] if item["key"] == f"p{post.id}")
    assert cloud["cloudPosts"][0]["latest_stat"]["likes"] == 1

    # 视频原地编辑（id/条数不变）
    video.title = "新标题"
    db.commit()
    second = library_service.page(db, creator_id=owner.id, limit=20)
    assert "新标题" in [item["title"] for item in second["items"]]
    assert "旧标题" not in [item["title"] for item in second["items"]]

    # 同日统计原地更新（数量不变）
    stat.likes = 500
    db.commit()
    third = library_service.page(db, creator_id=owner.id, limit=20)
    cloud = next(item for item in third["items"] if item["key"] == f"p{post.id}")
    assert cloud["cloudPosts"][0]["latest_stat"]["likes"] == 500


# ---------- S5：缓存单飞 ----------


def test_library_cache_single_flight_rebuilds_once(db, monkeypatch):
    """缓存过期瞬间 6 个并发请求只全量重建 1 次，其余等缓存；结果一致。"""
    owner = _creator(db)
    _account(db, owner, "douyin")
    _video(db, owner.id, "v1.mp4", title="素材一")

    calls = {"n": 0}
    orig_build = library_service._build_cards
    barrier = threading.Barrier(6)

    def _slow_build(session, creator_id=0):
        calls["n"] += 1
        time.sleep(0.15)
        return orig_build(session, creator_id)

    monkeypatch.setattr(library_service, "_build_cards", _slow_build)
    owner_id = owner.id  # 先取标量：worker 线程不能通过主 Session 触发 expire 懒加载
    maker = sessionmaker(bind=db.get_bind())
    results: list[list[dict] | None] = [None] * 6
    errors: list[BaseException] = []

    def _worker(index: int) -> None:
        session = maker()
        try:
            barrier.wait()
            results[index] = library_service.build_cards(session, owner_id)
        except BaseException as exc:  # noqa: BLE001 收集线程异常供断言
            errors.append(exc)
        finally:
            session.close()

    threads = [threading.Thread(target=_worker, args=(index,), name=f"r241-sf-{index}") for index in range(6)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)

    assert not errors, errors
    assert calls["n"] == 1, f"并发过期应只重建 1 次，实际 {calls['n']}"
    assert all(result == results[0] for result in results)
    assert works_service._INFLIGHT == {}


def test_cached_cards_wait_timeout_falls_back(monkeypatch):
    """等待超时后各自降级构建（fail-open）：不阻塞请求、结果一致、无 inflight 残留。"""
    monkeypatch.setattr(works_service, "_INFLIGHT_WAIT", 0.05)
    cache: dict[tuple, tuple[float, list[dict]]] = {}
    calls = {"n": 0}
    barrier = threading.Barrier(3)

    def _build():
        calls["n"] += 1
        time.sleep(0.2)
        return [{"value": 42}]

    results: list[list[dict] | None] = [None] * 3

    def _worker(index: int) -> None:
        barrier.wait()
        results[index] = works_service.cached_cards(cache, ("timeout",), _build)

    threads = [threading.Thread(target=_worker, args=(index,)) for index in range(3)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)

    assert calls["n"] >= 2, "等待超时后等待者应自行构建，而不是卡死"
    assert all(result == [{"value": 42}] for result in results)
    assert works_service._INFLIGHT == {}


def test_cached_cards_clears_inflight_on_build_error():
    """构建异常要清理 inflight，避免后续请求永久等待/inflight 泄漏。"""
    cache: dict[tuple, tuple[float, list[dict]]] = {}

    def _boom():
        raise RuntimeError("build failed")

    with pytest.raises(RuntimeError):
        works_service.cached_cards(cache, ("boom",), _boom)
    assert works_service._INFLIGHT == {}
    assert cache == {}

    # 异常后可正常重建
    assert works_service.cached_cards(cache, ("boom",), lambda: [{"ok": True}]) == [{"ok": True}]


# ---------- by-post 直查 ----------


def test_work_item_for_post_matches_list_works_and_is_direct(db, monkeypatch):
    """by-post 直查输出与旧「list_works + 扫描」完全一致，且不再全量重建。"""
    owner = _creator(db, is_current=True)
    bm = _creator(db, "对标A", kind="benchmark", parent_id=owner.id)
    owner_acc = _account(db, owner, "douyin")
    bm_acc = _account(db, bm, "bilibili")
    disabled_acc = _account(db, owner, "xiaohongshu", enabled=False)
    work = Work(creator_id=owner.id, title="跨平台作品")
    db.add(work)
    db.commit()
    p_owner = _post(db, owner_acc, "w-douyin", platform="douyin", work_id=work.id, title="抖音作品")
    p_bm = _post(db, bm_acc, "w-bili", platform="bilibili", work_id=work.id, title="B站作品")
    single = _post(db, owner_acc, "single", title="单条作品")
    disabled_post = _post(db, disabled_acc, "disabled", title="禁用账号的作品")
    _stat(db, p_owner, stat_date="2026-09-02", plays=100, likes=3)
    _stat(db, p_bm, stat_date="2026-09-02", plays=200, likes=4)
    _stat(db, single, stat_date="2026-09-02", plays=50, likes=1)
    library_service._CARD_CACHE.clear()
    works_service._WORKS_CACHE.clear()

    for post, creator_id in ((p_owner, owner.id), (p_bm, bm.id), (single, owner.id)):
        items = works_service._list_works(db, creator_id)
        expected = next(
            (item for item in items if any(member["id"] == post.id for member in item["posts"])),
            None,
        )
        assert expected is not None
        assert works_service.work_item_for_post(db, post.id) == expected

    # 不再全量重建：把 _list_works 换成爆炸桩后仍能返回
    monkeypatch.setattr(works_service, "_list_works", lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("不应全量重建")))
    assert works_service.work_item_for_post(db, p_owner.id) is not None
    with _capture_sql(db) as statements:
        assert works_service.work_item_for_post(db, p_bm.id) is not None
    assert len(statements) <= 10, f"by-post 直查应 ≤10 条 SQL，实际 {len(statements)}"

    # 帖子/账号/work 缺失 → None（路由层转 404，语义同旧实现）
    assert works_service.work_item_for_post(db, disabled_post.id) is None
    assert works_service.work_item_for_post(db, 10**9) is None


# ---------- DB 列瘦身 ----------


def test_library_cloud_cards_excludes_raw_and_matches_full_load(db, monkeypatch):
    """素材库云卡片不加载 platform_posts.raw，输出与全列加载完全一致。"""
    owner = _creator(db)
    acc = _account(db, owner, "douyin")
    work = Work(creator_id=owner.id, title="合并作品")
    db.add(work)
    db.commit()
    p1 = _post(db, acc, "p1", work_id=work.id, title="作品一", raw='{"share_url": "https://example.com/p1"}', tags='["面试"]')
    _post(db, acc, "p2", work_id=work.id, platform="bilibili", title="作品二", raw='{"bvid": "BV1xx"}')
    single = _post(db, acc, "p3", title="单条", raw="{}")
    _stat(db, p1, stat_date="2026-09-02", plays=1000, likes=10)
    video = _video(db, owner.id, "bound.mp4", main_topics='["求职"]', tags='["求职技巧"]')
    p1.local_video_id = video.id
    db.commit()

    with _capture_sql(db) as statements:
        slim, linked = library_service._cloud_cards(db, owner.id)
    assert not any("platform_posts.raw" in statement for statement in statements), "素材库卡片查询不应拉取 raw"
    assert linked == {video.id}

    # 全列加载（第二个 Session，避免 identity map 已加载列干扰）后输出必须一致
    full_db = sessionmaker(bind=db.get_bind())()
    try:
        monkeypatch.setattr(library_service, "_CLOUD_POST_FIELDS", Load(PlatformPost))
        monkeypatch.setattr(library_service, "_BOUND_VIDEO_FIELDS", Load(Video))
        full, full_linked = library_service._cloud_cards(full_db, owner.id)
    finally:
        full_db.close()
    assert full_linked == linked
    assert json.dumps(slim, sort_keys=True, default=str) == json.dumps(full, sort_keys=True, default=str)
    assert {item["key"] for item in slim} >= {f"w{work.id}", f"p{single.id}"}


# ---------- creator-summary 批量 ----------


def _legacy_creator_summary(db) -> dict:
    """R-241 改动前的实现（逐 creator/账号/帖子查询），作为等价性基线。"""
    creators = db.query(Creator).order_by(Creator.id).all()
    out = []
    for c in creators:
        accounts = db.query(CreatorAccount).filter(CreatorAccount.creator_id == c.id).all()
        totals = {"followers": 0, "posts": 0, "plays": 0, "likes": 0, "favorites": 0, "comments": 0}
        account_info = []
        for a in accounts:
            snap = (
                db.query(CreatorAccountSnapshot)
                .filter(CreatorAccountSnapshot.account_id == a.id)
                .order_by(CreatorAccountSnapshot.snapshot_date.desc())
                .first()
            )
            posts = (
                db.query(PlatformPost)
                .filter(PlatformPost.account_id == a.id)
                .order_by(PlatformPost.publish_time.desc())
                .limit(50)
                .all()
            )
            stat_rows = []
            for p in posts:
                st = (
                    db.query(PlatformPostStat)
                    .filter(PlatformPostStat.post_id == p.id)
                    .order_by(PlatformPostStat.stat_date.desc())
                    .first()
                )
                if st:
                    stat_rows.append(st)
            followers = snap.followers if snap else 0
            plays_list = [s.plays for s in stat_rows]
            med_plays = sorted(plays_list)[len(plays_list) // 2] if plays_list else 0
            hot_count = sum(1 for s in stat_rows if s.plays >= 100000)
            totals["followers"] += followers
            totals["posts"] += len(stat_rows) or len(posts)
            totals["plays"] += sum(plays_list)
            totals["likes"] += sum(s.likes for s in stat_rows)
            totals["favorites"] += sum(s.favorites for s in stat_rows)
            totals["comments"] += sum(s.comments for s in stat_rows)
            account_info.append(
                {
                    "platform": a.platform,
                    "nickname": snap.nickname if snap else a.nickname,
                    "followers": followers,
                    "posts": len(posts),
                    "median_plays": med_plays,
                    "hot_posts": hot_count,
                }
            )
        out.append(
            {
                "creator": {"id": c.id, "kind": c.kind, "parent_id": c.parent_id, "name": c.name, "is_current": c.is_current},
                "totals": totals,
                "accounts": account_info,
            }
        )
    return {"items": out}


def test_creator_summary_batches_sql_and_matches_legacy(db):
    """creator-summary 703 条 N+1 → 5 条批量 SQL，输出与旧实现逐字段一致。"""
    owner = _creator(db, is_current=True)
    bm = _creator(db, "对标A", kind="benchmark", parent_id=owner.id)
    owner_acc = _account(db, owner, "douyin")
    owner_bili = _account(db, owner, "bilibili")
    bm_acc = _account(db, bm, "douyin")
    base = datetime(2026, 9, 1, 12, 0, 0)
    # 主博主抖音：60 条作品（>50 验证「最近 50 帖」截断）+ 全部有统计，覆盖 median/爆款
    posts = [
        PlatformPost(
            account_id=owner_acc.id,
            platform="douyin",
            platform_post_id=f"own-{index}",
            title=f"作品{index}",
            publish_time=base - timedelta(hours=index),
            raw="{}",
        )
        for index in range(60)
    ]
    db.add_all(posts)
    db.flush()
    stats = [
        PlatformPostStat(
            post_id=post.id,
            stat_date="2026-09-02",
            plays=200000 if index == 0 else 1000 + index,
            likes=10 + index,
            favorites=3,
            comments=1,
        )
        for index, post in enumerate(posts)
    ]
    db.add_all(stats)
    # 主博主 B 站：3 条作品无统计（totals.posts 走 len(posts) 兜底）
    bili_posts = [
        PlatformPost(
            account_id=owner_bili.id,
            platform="bilibili",
            platform_post_id=f"bili-{index}",
            title=f"B站{index}",
            publish_time=base - timedelta(days=index + 1),
            raw="{}",
        )
        for index in range(3)
    ]
    db.add_all(bili_posts)
    bm_post = PlatformPost(
        account_id=bm_acc.id,
        platform="douyin",
        platform_post_id="bm-1",
        title="对标作品",
        publish_time=base,
        raw="{}",
    )
    db.add(bm_post)
    db.flush()
    db.add(PlatformPostStat(post_id=bm_post.id, stat_date="2026-09-02", plays=500, likes=5))
    db.add_all(
        [
            CreatorAccountSnapshot(account_id=owner_acc.id, snapshot_date="2026-09-01", nickname="旧昵称", followers=100),
            CreatorAccountSnapshot(account_id=owner_acc.id, snapshot_date="2026-09-02", nickname="新昵称", followers=91170),
            CreatorAccountSnapshot(account_id=bm_acc.id, snapshot_date="2026-09-02", nickname="对标昵称", followers=5000),
        ]
    )
    db.commit()

    with _capture_sql(db) as statements:
        new = creator_summary(db=db)
    assert len(statements) <= 6, f"creator-summary 应为批量 SQL（≤6），实际 {len(statements)}"
    legacy = _legacy_creator_summary(db)
    assert new == legacy

    owner_item = next(item for item in new["items"] if item["creator"]["id"] == owner.id)
    assert owner_item["totals"]["followers"] == 91170
    assert owner_item["totals"]["posts"] == 50 + 3, "抖音取最近 50 帖（全有统计），B 站 3 帖无统计走 posts 兜底"
    assert owner_item["accounts"][0]["median_plays"] > 0
    assert owner_item["accounts"][0]["hot_posts"] == 1
    bm_item = next(item for item in new["items"] if item["creator"]["id"] == bm.id)
    assert bm_item["totals"]["followers"] == 5000 and bm_item["totals"]["posts"] == 1
