"""内容机会引擎（R-185）：评论聚类选题榜 + 选题账本 + 每周灵感包。

纯本地统计，不调 LLM：
- 把灵感池里「未使用」的评论按语义相似聚成「观众提问」簇（同一问题被多人问 = 强需求）；
- 与「已讲过」的话题（草稿 used/done + 已发布素材标题）做近义匹配，标注重复、提示缺口；
- 综合 需求强度 × 人设相关 × 热度 × 新鲜度 × 缺口 打分，产出「每周灵感包」。
"""

from __future__ import annotations

import math
import re
import time
from datetime import datetime
from difflib import SequenceMatcher

from sqlalchemy.orm import Session

from ..models.hot_topic import TopicIdea

_SIM_THRESHOLD = 0.5
_COVERED_THRESHOLD = 0.62
_SCAN_LIMIT = 500  # 只对互动最高的一批评论聚类，避免 O(n²) 卡死
_CACHE_TTL = 120.0
_CACHE: dict[str, tuple[float, object]] = {}


def _cached(key: str, fn):
    now = time.monotonic()
    hit = _CACHE.get(key)
    if hit and now - hit[0] < _CACHE_TTL:
        return hit[1]
    value = fn()
    _CACHE[key] = (now, value)
    if len(_CACHE) > 32:
        _CACHE.clear()
    return value
_EMOJI_TAG = re.compile(r"\[[^\]]{1,8}\]")
_AT_RE = re.compile(r"@\S+")
_QUESTION_HINTS = ("怎么", "如何", "能不能", "是不是", "为什么", "吗", "？", "?", "求", "想问", "请教")


def _clean(text: str) -> str:
    """去掉表情标签/[话题]、@提及与首尾标点，得到适合展示与聚类的问题文本。"""
    t = _EMOJI_TAG.sub("", text or "")
    t = _AT_RE.sub("", t)
    return t.strip(" \t\r\n，。！？!?、,.~—·")


def _norm(text: str) -> str:
    return re.sub(r"[\s\W_]+", "", _clean(text).lower())


def _is_question(text: str) -> bool:
    return any(h in (text or "") for h in _QUESTION_HINTS)


def _sim(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    if a in b or b in a:
        return 1.0
    return SequenceMatcher(None, a, b).ratio()


def covered_titles(db: Session, limit: int = 400) -> list[str]:
    """「已讲过」的话题标题（选题账本的事实源）：已完成/待制作草稿 + 已发布素材。"""
    from ..models.draft import Draft
    from ..models.video import Video
    from .creator_service import current_creator_id

    cid = current_creator_id(db)
    titles: list[str] = []
    dq = db.query(Draft).filter(Draft.status.in_(["used", "done"]))
    if cid:
        dq = dq.filter(Draft.creator_id == cid)
    for d in dq.order_by(Draft.id.desc()).limit(limit).all():
        if (d.title or "").strip():
            titles.append(d.title.strip())
    vq = db.query(Video)
    if cid:
        vq = vq.filter(Video.creator_id == cid)
    for v in vq.order_by(Video.id.desc()).limit(limit).all():
        if (v.title or "").strip():
            titles.append(v.title.strip())
    out: list[str] = []
    for t in titles:
        if t not in out:
            out.append(t)
    return out


def _is_covered(title: str, covered_norm: list[str]) -> bool:
    n = _norm(title)
    return any(_sim(n, c) >= _COVERED_THRESHOLD for c in covered_norm)


def _unused_ideas(db: Session, source: str, limit: int | None = None) -> list[TopicIdea]:
    q = (
        db.query(TopicIdea)
        .filter(TopicIdea.source == source, TopicIdea.used.is_(False))
        .order_by(TopicIdea.likes.desc(), TopicIdea.id.desc())
    )
    if limit:
        q = q.limit(limit)
    return q.all()


def _cid(db: Session) -> int | None:
    from .creator_service import current_creator_id

    return current_creator_id(db)


def comment_clusters(db: Session, limit: int = 15) -> dict:
    """观众提问榜（带 120s 缓存）：把未使用评论按近义聚簇，返回按需求分排序的簇列表。"""
    cid = _cid(db) or 0
    return _cached(f"cc:{cid}:{limit}", lambda: _comment_clusters(db, limit))


def _comment_clusters(db: Session, limit: int) -> dict:
    from . import ideas_service

    rows = _unused_ideas(db, "comment", _SCAN_LIMIT)
    if not rows:
        return {"clusters": [], "total_comments": 0}
    ann = {a["id"]: a for a in ideas_service.annotate_items(db, [{"id": r.id, "title": r.title} for r in rows])}
    clusters: list[dict] = []
    for r in rows:
        title = _clean(r.title)
        n = _norm(title)
        if len(n) < 4:
            continue
        for c in clusters:
            if _sim(n, c["_norm"]) >= _SIM_THRESHOLD:
                c["count"] += 1
                c["likes"] += int(r.likes or 0)
                if len(c["samples"]) < 4 and r.post_title:
                    c["samples"].append(r.post_title[:60])
                if ann.get(r.id, {}).get("matched"):
                    c["matched"] = True
                break
        else:
            clusters.append(
                {
                    "title": title[:120],
                    "count": 1,
                    "likes": int(r.likes or 0),
                    "samples": [r.post_title[:60]] if r.post_title else [],
                    "matched": bool(ann.get(r.id, {}).get("matched")),
                    "question": _is_question(title),
                    "_norm": n,
                }
            )
    out: list[dict] = []
    for c in clusters:
        c.pop("_norm", None)
        c["score"] = (
            c["count"] * 10
            + round(math.log1p(c["likes"]) * 5)
            + (20 if c["matched"] else 0)
            + (8 if c.get("question") else 0)
        )
        out.append(c)
    out.sort(key=lambda c: c["score"], reverse=True)
    return {"clusters": out[:limit], "total_comments": len(rows)}


def weekly_pack(db: Session, limit: int = 20) -> dict:
    """每周灵感补给包（带 120s 缓存）：评论簇 + 热榜，去重/去已讲，综合打分。"""
    cid = _cid(db) or 0
    return _cached(f"wp:{cid}:{limit}", lambda: _weekly_pack(db, limit))


def _weekly_pack(db: Session, limit: int) -> dict:
    from . import ideas_service

    covered = [_norm(t) for t in covered_titles(db)]
    items: list[dict] = []

    cc = comment_clusters(db, limit=40)
    for c in cc["clusters"]:
        items.append(
            {
                "title": c["title"],
                "slot": "comment",
                "demand": c["count"],
                "likes": c["likes"],
                "matched": c["matched"],
                "samples": c["samples"],
                "reason": f"评论区被问 {c['count']} 次" + ("（贴合人设）" if c["matched"] else ""),
            }
        )

    hots = ideas_service.annotate_items(
        db, [{"id": r.id, "title": r.title} for r in _unused_ideas(db, "hot")]
    )
    seen = {_norm(i["title"]) for i in items}
    for h in hots:
        n = _norm(h["title"])
        if not n or any(_sim(n, s) >= _SIM_THRESHOLD for s in seen):
            continue
        seen.add(n)
        items.append(
            {
                "title": h["title"],
                "slot": "hot",
                "demand": 1,
                "likes": 0,
                "matched": h.get("matched", False),
                "samples": [],
                "reason": "今日热榜" + ("·人设匹配" if h.get("matched") else "·人设相关度低"),
            }
        )

    out: list[dict] = []
    for it in items:
        duplicate = _is_covered(it["title"], covered)
        score = (
            it["demand"] * 10
            + round(math.log1p(it["likes"]) * 5)
            + (20 if it["matched"] else 0)
            + (15 if not duplicate else -40)
        )
        it["duplicate"] = duplicate
        it["score"] = max(0, score)
        out.append(it)
    out.sort(key=lambda x: x["score"], reverse=True)
    kept = [x for x in out if not x["duplicate"]][:limit]
    return {"items": kept, "covered_count": len(covered), "generated_at": datetime.now().isoformat()}


def ledger(db: Session, limit: int = 50) -> dict:
    """选题账本（带 120s 缓存）：已讲过的话题 + 未使用灵感里被判为「可能已讲」的条目。"""
    cid = _cid(db) or 0
    return _cached(f"led:{cid}:{limit}", lambda: _ledger(db, limit))


def _ledger(db: Session, limit: int) -> dict:
    covered = covered_titles(db)
    cc = comment_clusters(db, limit=limit)
    covered_norm = [_norm(t) for t in covered]
    dup = [c for c in cc["clusters"] if _is_covered(c["title"], covered_norm)]
    return {
        "covered": covered[:limit],
        "covered_count": len(covered),
        "maybe_repeated": dup,
        "pool_comments": cc["total_comments"],
    }
