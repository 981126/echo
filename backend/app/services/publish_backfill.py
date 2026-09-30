"""历史发布回填（R-197）：把已发布草稿自动关联到作品，让表现归因有历史数据。

策略：按「规范化标题相似度 ≥ 0.8」把 status ∈ used/done 的草稿匹配到当前主博主的 works；
匹配后写 work_id（有本地素材则一并写 video_id）与发布平台/链接/时间，再刷新表现。
所有自动关联的草稿 id 记在 app_kv（`publish_backfill_applied`），可一键撤销。
"""

from __future__ import annotations

import json
import re
from difflib import SequenceMatcher

from sqlalchemy.orm import Session

from ..models.draft import Draft
from ..models.kv import Kv
from ..models.platform import PlatformPost
from ..models.work import Work
from .creator_service import current_creator_id

MATCH_THRESHOLD = 0.8
_APPLIED_KEY = "publish_backfill_applied"
_EMOJI_TAG = re.compile(r"\[[^\]]{1,8}\]")


def _norm(title: str) -> str:
    t = _EMOJI_TAG.sub("", title or "")
    t = re.sub(r"[#＃][^\s#＃，。！？!?、]+", "", t)
    return re.sub(r"[\s\W_]+", "", t.lower())


def preview(db: Session, limit: int = 200) -> dict:
    """列出高置信度的「草稿 ↔ 作品」候选（未应用）。"""
    cid = current_creator_id(db)
    dq = db.query(Draft).filter(
        Draft.status.in_(["used", "done"]),
        Draft.video_id.is_(None),
        Draft.work_id.is_(None),
    )
    if cid:
        dq = dq.filter(Draft.creator_id == cid)
    drafts = [d for d in dq.all() if len(_norm(d.title)) >= 6]
    wq = db.query(Work)
    if cid:
        wq = wq.filter(Work.creator_id == cid)
    works = [(_norm(w.title), w) for w in wq.all() if len(_norm(w.title)) >= 6]
    pairs: list[dict] = []
    for d in drafts:
        nd = _norm(d.title)
        best = None
        best_score = 0.0
        for nw, w in works:
            sc = SequenceMatcher(None, nd, nw).ratio()
            if sc > best_score:
                best_score, best = sc, w
        if best is not None and best_score >= MATCH_THRESHOLD:
            pairs.append(
                {"draft_id": d.id, "draft_title": d.title, "work_id": best.id, "work_title": best.title, "score": round(best_score, 3)}
            )
    pairs.sort(key=lambda x: x["score"], reverse=True)
    return {"pairs": pairs[:limit], "total": len(pairs)}


def apply_links(db: Session) -> dict:
    """应用高置信度匹配：写 work_id/video_id 与发布信息 → 刷新表现 → 记账（可撤销）。"""
    from ..models.video import Video
    from .draft_performance import refresh_published_performance

    pv = preview(db, limit=1000)
    applied: list[int] = []
    for p in pv["pairs"]:
        d = db.get(Draft, p["draft_id"])
        if d is None:
            continue
        work = db.get(Work, p["work_id"])
        if work is None:
            continue
        d.work_id = work.id
        v = db.query(Video).filter(Video.work_id == work.id).first()
        if v is not None:
            d.video_id = v.id
        post = db.query(PlatformPost).filter(PlatformPost.work_id == work.id).first()
        if post is not None:
            from ..core.platform_links import build_platform_page_url

            d.publish_platform = post.platform or d.publish_platform
            url = build_platform_page_url(post.platform, post.platform_post_id, post.raw or "")
            if url:
                d.publish_url = url
            if post.publish_time and not d.published_at:
                d.published_at = post.publish_time
        applied.append(d.id)
    db.commit()
    _remember(db, applied)
    updated = refresh_published_performance(db)
    return {"linked": len(applied), "with_performance": updated}


def revert(db: Session) -> dict:
    """撤销上一次自动关联（只清它写过的草稿，不动手工数据）。"""
    ids = _applied_ids(db)
    n = 0
    for did in ids:
        d = db.get(Draft, did)
        if d is None:
            continue
        d.work_id = None
        d.video_id = None
        d.publish_url = ""
        d.publish_platform = ""
        d.published_at = None
        d.performance = "{}"
        n += 1
    _remember(db, [])
    db.commit()
    return {"reverted": n}


def _applied_ids(db: Session) -> list[int]:
    row = db.get(Kv, _APPLIED_KEY)
    if row is None:
        return []
    try:
        return [int(x) for x in json.loads(row.value or "[]")]
    except (TypeError, ValueError):
        return []


def _remember(db: Session, ids: list[int]) -> None:
    value = json.dumps(ids)
    row = db.get(Kv, _APPLIED_KEY)
    if row is None:
        db.add(Kv(key=_APPLIED_KEY, value=value))
    else:
        row.value = value
    db.commit()


# ---------- R-202：回填历史发布改为后台任务 ----------

def apply_task(db: Session, payload: dict) -> dict:
    return apply_links(db)
