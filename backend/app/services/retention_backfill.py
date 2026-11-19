"""R-265：补齐历史作品的留存曲线（每条 1 次 TikHub 请求）。

只补「有 5 秒完播但 retention_trend 为空」的作品；写入该作品**最新快照行**，
`similar_author_trend` 只覆盖 retention 键（保留已有 bounce）。
"""

from __future__ import annotations

import json
import time
from datetime import date, timedelta

from sqlalchemy.orm import Session

from ..core.timeutil import now as _app_now
from ..models.kv import Kv
from ..models.platform import CreatorAccount, PlatformPost, PlatformPostStat
from ..models.video_review import DouyinPostMetric
from .douyin_account_policy import resolve_data_policy
from .douyin_creator_sync import CredentialError, _charge_requests, _cookie, _trend
from .platform.budget import BudgetExceeded
from .platform.tikhub import make_client

THROTTLE_SECONDS = 0.2
RECENT_DAYS = 7
EMPTY_MARKER_DAYS = 7  # 平台返回空趋势后 7 天内不重复请求，避免白烧额度
EMPTY_MARKER_KEY = "trend_empty:{post_id}"


def owner_account(db: Session, owner_id: int) -> CreatorAccount | None:
    return (
        db.query(CreatorAccount)
        .filter_by(creator_id=owner_id, platform="douyin", enabled=True)
        .order_by(CreatorAccount.id)
        .first()
    )


def _has_metric(db: Session, *, with_trend: bool):
    """相关子查询：该作品是否存在「有 5 秒完播」或「已有曲线」的快照。"""
    query = db.query(DouyinPostMetric.id).filter(DouyinPostMetric.post_id == PlatformPost.id)
    if with_trend:
        query = query.filter(DouyinPostMetric.retention_trend.notin_(["[]", ""]))
    else:
        query = query.filter(DouyinPostMetric.finish_5s_rate.isnot(None))
    return query.exists()


def _base_posts(db: Session, account: CreatorAccount):
    return db.query(PlatformPost).filter(
        PlatformPost.account_id == account.id,
        PlatformPost.platform == "douyin",
        _has_metric(db, with_trend=False),
        ~_has_metric(db, with_trend=True),
    )


def _empty_recently(db: Session, post_id: int) -> bool:
    row = db.get(Kv, EMPTY_MARKER_KEY.format(post_id=post_id))
    if row is None:
        return False
    try:
        marked = date.fromisoformat(str(row.value))
    except ValueError:
        return False
    return (_app_now().date() - marked).days < EMPTY_MARKER_DAYS


def _pending_ids(db: Session, account: CreatorAccount, *, scope: str = "missing") -> list[int]:
    query = _base_posts(db, account)
    if scope == "recent":
        query = query.filter(PlatformPost.publish_time >= _app_now() - timedelta(days=RECENT_DAYS))
    rows = query.order_by(PlatformPost.publish_time.desc().nulls_last(), PlatformPost.id.desc()).all()
    return [int(row.id) for row in rows]


def coverage(db: Session, account: CreatorAccount) -> dict:
    """待补数量：unsupported=平台近期明确返回空、7 天内不再重试的作品。"""
    total = (
        db.query(PlatformPost)
        .filter(
            PlatformPost.account_id == account.id,
            PlatformPost.platform == "douyin",
            _has_metric(db, with_trend=False),
        )
        .count()
    )
    pending_all = _pending_ids(db, account)
    unsupported = sum(1 for post_id in pending_all if _empty_recently(db, post_id))
    return {
        "total": total,
        "covered": max(0, total - len(pending_all)),
        "pending": max(0, len(pending_all) - unsupported),
        "unsupported": unsupported,
    }


def plan_post_ids(
    db: Session, account: CreatorAccount, *, scope: str = "missing", limit: int = 300
) -> list[int]:
    ids = [post_id for post_id in _pending_ids(db, account, scope=scope) if not _empty_recently(db, post_id)]
    return ids[: max(1, min(int(limit), 1000))]


def _mark_empty(db: Session, post_id: int) -> None:
    key = EMPTY_MARKER_KEY.format(post_id=post_id)
    row = db.get(Kv, key)
    value = _app_now().date().isoformat()
    if row is None:
        db.add(Kv(key=key, value=value))
    else:
        row.value = value
    db.commit()


def _save_trend(db: Session, post: PlatformPost, current: list, similar: list) -> None:
    row = (
        db.query(DouyinPostMetric)
        .filter_by(post_id=post.id)
        .order_by(DouyinPostMetric.snapshot_date.desc(), DouyinPostMetric.captured_at.desc())
        .first()
    )
    if row is None:
        raise RuntimeError("该作品没有指标快照，跳过")
    row.retention_trend = json.dumps(current, ensure_ascii=False, default=str)
    try:
        merged = json.loads(row.similar_author_trend or "{}")
    except (TypeError, ValueError):
        merged = {}
    if not isinstance(merged, dict):
        merged = {}
    merged["retention"] = similar
    row.similar_author_trend = json.dumps(merged, ensure_ascii=False, default=str)
    stat = (
        db.query(PlatformPostStat)
        .filter_by(post_id=post.id)
        .order_by(PlatformPostStat.stat_date.desc())
        .first()
    )
    plays = int(stat.plays or 0) if stat is not None else 0
    row.trend_reliable = bool(plays >= 200 and current)
    db.commit()


def run_backfill(db: Session, payload: dict, update=None) -> dict:
    """后台任务：逐条补曲线；单条失败不中断，全失败向上抛（任务判 failed）。"""
    account = db.get(CreatorAccount, int(payload.get("account_id") or 0))
    if account is None:
        raise RuntimeError("抖音账号不存在")
    post_ids = [int(value) for value in payload.get("post_ids") or []]
    if not post_ids:
        return {"ok": 0, "failed": 0, "message": "没有需要补齐的作品"}

    policy = resolve_data_policy(db, account)
    if policy.is_blocked:
        raise CredentialError(policy.reason)
    if not policy.is_creator:
        raise CredentialError("当前账号未启用创作者数据，无法补齐留存曲线")

    client = make_client()
    cookie = _cookie(db, account.id, client)
    ok = 0
    failures: list[dict] = []
    total = len(post_ids)
    for index, post_id in enumerate(post_ids, start=1):
        post = db.get(PlatformPost, post_id)
        if post is None:
            failures.append({"post_id": post_id, "title": "", "error": "作品不存在"})
        else:
            before = client.requests_used
            try:
                raw = client.fetch_douyin_watch_trend(
                    cookie=cookie, item_id=post.platform_post_id, analysis_type=1
                )
                current, similar = _trend(raw)
                if not current:
                    _mark_empty(db, post.id)
                    failures.append(
                        {"post_id": post.id, "title": (post.title or "")[:60], "error": "平台未提供观看趋势", "empty": True}
                    )
                    if update is not None and (index % 5 == 0 or index == total):
                        update(int(index / total * 100), f"补齐留存曲线 {index}/{total}")
                    if index < total:
                        time.sleep(THROTTLE_SECONDS)
                    continue
                _save_trend(db, post, current, similar)
                _charge_requests(db, client, before)
                ok += 1
            except BudgetExceeded:
                db.rollback()
                raise
            except Exception as exc:  # noqa: BLE001 单条失败不中断整批
                db.rollback()
                failures.append(
                    {"post_id": post.id, "title": (post.title or "")[:60], "error": str(exc)[:120], "empty": False}
                )
        if update is not None and (index % 5 == 0 or index == total):
            update(int(index / total * 100), f"补齐留存曲线 {index}/{total}")
        if index < total:
            time.sleep(THROTTLE_SECONDS)

    empty = [item for item in failures if item.get("empty")]
    real = [item for item in failures if not item.get("empty")]
    if ok == 0 and real:
        raise RuntimeError(f"留存曲线补齐全部失败：{real[0]['error']}")
    if ok == 0 and not real:
        return {
            "ok": 0,
            "failed": 0,
            "unsupported": len(empty),
            "message": f"平台未提供 {len(empty)} 条作品的观看趋势，已标记 7 天内不重复请求",
            "failures": [],
        }
    message = f"成功 {ok}、平台无趋势 {len(empty)}、失败 {len(real)}"
    if real:
        message += "（" + "；".join(f"{item['title'] or item['post_id']}：{item['error']}" for item in real[:5]) + "）"
    return {
        "ok": ok,
        "failed": len(real),
        "unsupported": len(empty),
        "message": message,
        "failures": real[:5],
    }
