"""R-242 复核既有缺陷修复回归。

覆盖：
1. transcripts.video_id 唯一（迁移后索引唯一、重复插入被拒、ASR 落稿重复调用只更新一行）；
2. 批量同步单条详情失败不丢同批其它作品（作品仍入库、统计缺失、不 rollback）；
3. 无主博主时 GET /api/douyin-review/plans 返回空列表而非 500；
4. 抖音创作者同步 `_charge_requests` N 次请求合并为 1 次计费事务。
"""

from __future__ import annotations

import sys
import threading
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from conftest import ensure_schema, fresh_engine  # noqa: E402
from sqlalchemy import inspect  # noqa: E402
from sqlalchemy.exc import IntegrityError  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

from app.models.platform import Creator, CreatorAccount, PlatformPost, PlatformPostStat  # noqa: E402
from app.models.video import Transcript, Video  # noqa: E402


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
        platform_user_id="u-r242",
        enabled=True,
    )
    s.add(acc)
    s.commit()
    return owner, acc


# ---------- 1) 转写稿唯一 ----------


def test_transcripts_video_id_is_unique() -> None:
    eng, S = _session_factory()
    s = S()
    try:
        indexes = {i["name"]: i for i in inspect(eng).get_indexes("transcripts")}
        assert indexes.get("ix_transcripts_video_id", {}).get("unique") is True

        video = Video(filename="r242-uniq.mp4", title="唯一性")
        s.add(video)
        s.commit()
        s.add(Transcript(video_id=video.id, transcript_text="第一份", asr_status="done"))
        s.commit()
        s.add(Transcript(video_id=video.id, transcript_text="第二份", asr_status="done"))
        try:
            s.commit()
        except IntegrityError:
            s.rollback()
        else:  # pragma: no cover
            raise AssertionError("同一视频插入第二条转写必须被唯一约束拒绝")
    finally:
        s.close()
        eng.dispose()


def test_asr_success_repeat_keeps_single_transcript(monkeypatch) -> None:
    """自动转写落稿重复执行（重试/并发）只更新同一行，不产生第二行。"""
    from app.services import ingest

    _eng, S = _session_factory()
    s = S()
    try:
        video = Video(filename="r242-asr.mp4", title="ASR 唯一")
        s.add(video)
        s.commit()
        vid = video.id
    finally:
        s.close()

    monkeypatch.setattr(ingest, "correct_transcript", lambda text, db=None: f"校对:{text}")

    class _FakePersona:
        def suggest_video_tags(self, text):  # noqa: ANN001
            return {"main_topics": ["面试"], "tags": ["干货"], "is_ad": False}

    monkeypatch.setattr(ingest, "PersonaService", _FakePersona)

    db = S()
    try:
        ingest._post_asr_llm(db, vid, "原始转写", {"mode": "mock", "model": ""})
        ingest._post_asr_llm(db, vid, "原始转写", {"mode": "mock", "model": ""})
        rows = db.query(Transcript).filter(Transcript.video_id == vid).all()
        assert len(rows) == 1, f"同一视频出现多条转写：{len(rows)}"
        assert rows[0].corrected_text == "校对:原始转写"
        assert rows[0].asr_status == "done"
    finally:
        db.close()


# ---------- 2) 批量同步单条失败不丢整批 ----------


class _FakeClient:
    """fetch_post_stats：pid=bad-* 抛错，其余返回统计。"""

    def __init__(self) -> None:
        self.calls = 0

    def fetch_post_stats(self, platform, pid, account):  # noqa: ANN001, ARG002
        self.calls += 1
        if str(pid).startswith("bad"):
            raise RuntimeError("单条详情接口抖动")
        return {"likes": 5, "comments": 1, "source": "tikhub"}


def _post_data(pid: str):
    return SimpleNamespace(
        platform_post_id=pid,
        title=f"作品 {pid}",
        desc="",
        cover_url="",
        video_url="",
        publish_time=None,
        raw={},
        tags=[],
        stats=None,
    )


def test_ensure_post_batch_failure_keeps_other_posts() -> None:
    from app.services.platform_sync import _ensure_post

    _eng, S = _session_factory()
    s = S()
    try:
        _owner, acc = _seed_creator(s)
        client = _FakeClient()
        account = SimpleNamespace(id=acc.id, platform="douyin")
        existing: dict = {}

        first = _post_data("ok-1")
        row1 = _ensure_post(s, account, first, client, commit=False, existing=existing)
        assert row1.id is not None
        # 第二条详情失败：不应 rollback 掉第一条/当前作品，只丢统计
        second = _post_data("bad-1")
        row2 = _ensure_post(s, account, second, client, commit=False, existing=existing)
        s.commit()

        posts = s.query(PlatformPost).all()
        assert {p.platform_post_id for p in posts} == {"ok-1", "bad-1"}, "批量失败后作品丢失"
        assert row2.id is not None
        stats = s.query(PlatformPostStat).all()
        assert len(stats) == 1 and stats[0].post_id == row1.id
    finally:
        s.close()


def test_ensure_post_single_failure_still_saves_post() -> None:
    """单帖模式详情失败：作品仍入库（旧行为会把当前作品一起 rollback 掉）。"""
    from app.services.platform_sync import _ensure_post

    _eng, S = _session_factory()
    s = S()
    try:
        _owner, acc = _seed_creator(s)
        account = SimpleNamespace(id=acc.id, platform="douyin")
        row = _ensure_post(s, account, _post_data("bad-single"), _FakeClient(), commit=True)
        assert row.id is not None
        assert s.query(PlatformPost).filter(PlatformPost.id == row.id).count() == 1
        assert s.query(PlatformPostStat).count() == 0
    finally:
        s.close()


# ---------- 3) 无主博主 plans 返回空列表 ----------


def test_plans_without_creator_returns_empty_list() -> None:
    from app.api.douyin_review import plans

    _eng, S = _session_factory()
    s = S()
    try:
        assert plans(post_id=None, limit=20, db=s) == {"items": []}
    finally:
        s.close()


# ---------- 4) 预算计费合并为单次事务 ----------


def test_charge_requests_merges_into_single_charge(monkeypatch) -> None:
    from app.services import douyin_creator_sync as dcs
    from app.services.platform import budget as budget_mod

    _eng, S = _session_factory()
    s = S()
    try:
        calls: list[int] = []
        monkeypatch.setattr(dcs, "_charge", lambda db, count=1: calls.append(int(count)))
        monkeypatch.setattr(
            budget_mod, "get_budget", lambda db: {"limit": 100, "used": 0, "remaining": 50}
        )
        client = SimpleNamespace(mode="real", requests_used=7)
        dcs._charge_requests(s, client, before=0)
        assert calls == [7], f"应合并为 1 次计费，实际 {calls}"

        # 超出剩余额度：只计剩余一次，并告警（不超发）
        calls.clear()
        monkeypatch.setattr(
            budget_mod, "get_budget", lambda db: {"limit": 100, "used": 97, "remaining": 3}
        )
        client = SimpleNamespace(mode="real", requests_used=10)
        dcs._charge_requests(s, client, before=0)
        assert calls == [3]

        # 无请求增量：不调用计费
        calls.clear()
        client = SimpleNamespace(mode="real", requests_used=5)
        dcs._charge_requests(s, client, before=5)
        assert calls == []
    finally:
        s.close()


# ---------- 兼容：并发落稿串行化（行锁）不冲突 ----------


def test_asr_concurrent_store_keeps_single_row(monkeypatch) -> None:
    from app.services import ingest

    _eng, S = _session_factory()
    s = S()
    try:
        video = Video(filename="r242-race.mp4", title="并发落稿")
        s.add(video)
        s.commit()
        vid = video.id
    finally:
        s.close()

    monkeypatch.setattr(ingest, "correct_transcript", lambda text, db=None: text)

    class _FakePersona:
        def suggest_video_tags(self, text):  # noqa: ANN001
            return {"main_topics": [], "tags": [], "is_ad": False}

    monkeypatch.setattr(ingest, "PersonaService", _FakePersona)
    errors: list[BaseException] = []

    def _run() -> None:
        db = S()
        try:
            ingest._post_asr_llm(db, vid, "同一段转写", {"mode": "mock", "model": ""})
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)
        finally:
            db.close()

    threads = [threading.Thread(target=_run) for _ in range(3)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(15)

    db = S()
    try:
        assert not errors, [f"{type(e).__name__}: {e}" for e in errors]
        assert db.query(Transcript).filter(Transcript.video_id == vid).count() == 1
    finally:
        db.close()
