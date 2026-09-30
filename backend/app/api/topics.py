"""热点与选题接口。"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..core.pipeline import today_key
from ..db import get_db
from ..models.hot_topic import HotTopic, TopicCandidate
from ..services.topic_mining import fetch_and_store
from ..tasks import find_running_task, start_task

router = APIRouter()


def _hot_refresh_task(db: Session, payload: dict) -> dict:
    items = fetch_and_store(db)
    return {"fetched": len(items)}


@router.get("/gaps")
def topic_gaps(days: int = 28, db: Session = Depends(get_db)):
    """R-030⑥ 话题缺口：最近 N 天已发布内容的话题覆盖 + 评论区在问的相关问题数。"""
    import datetime
    import json
    from ..core.topics import MAIN_TOPICS
    from ..models.hot_topic import TopicIdea
    from ..models.video import Video
    from ..services.creator_service import current_creator_id

    cid = current_creator_id(db)
    cutoff = (datetime.date.today() - datetime.timedelta(days=max(7, days))).isoformat()
    counts = {t: 0 for t in MAIN_TOPICS}
    q = db.query(Video).filter(Video.is_ad.is_(False), Video.status == "published")
    if cid:
        q = q.filter(Video.creator_id == cid)
    for v in q.all():
        published = (v.published_at or v.planned_publish_at)
        if not published or published.date().isoformat() < cutoff:
            continue
        topics = []
        try:
            topics = json.loads(v.main_topics or "[]")
        except Exception:  # noqa: BLE001
            topics = []
        for t in topics:
            counts[t] = counts.get(t, 0) + 1
    ideas = db.query(TopicIdea).filter(TopicIdea.source == "comment").all()
    rows = []
    for t in MAIN_TOPICS:
        kw = t if t != "其他" else ""
        ask = sum(1 for it in ideas if kw and kw in it.title)
        rows.append((counts.get(t, 0), ask, t))
    rows.sort(key=lambda x: (x[0], -x[1]))
    return {"items": [{"topic": t, "published": p, "asking_comments": a} for p, a, t in rows]}


@router.get("/hot")
def list_hot(date: str = "", db: Session = Depends(get_db)):
    """当日热榜（R-072：按当前人设本地打分；命中红线词剔除，其余附带 score/matched）。"""
    from ..services.ideas_service import annotate_items, persona_profile

    key = date or today_key()
    rows = (
        db.query(HotTopic)
        .filter(HotTopic.topic_date == key)
        .order_by(HotTopic.platform, HotTopic.id.desc())
        .all()
    )
    items = annotate_items(
        db,
        [{"platform": r.platform, "title": r.title, "heat": r.heat, "url": r.url} for r in rows],
        persona_profile(db),
    )
    # 命中红线词的热榜直接剔除
    items = [it for it in items if not it["redlined"]]
    return {"date": key, "total": len(items), "items": items}


@router.post("/refresh")
def refresh_hot(db: Session = Depends(get_db)):
    """立即抓取今日热点（真实模式需 NAS 有外网）。R-202：改为后台任务，返回 task_id。"""
    tid = find_running_task("hot_refresh")
    if tid:
        return {"task_id": tid}
    return {"task_id": start_task("hot_refresh", {}, _hot_refresh_task)}


@router.get("")
def list_candidates(date: str = "", db: Session = Depends(get_db)):
    key = date or today_key()
    rows = (
        db.query(TopicCandidate)
        .filter(TopicCandidate.run_date == key)
        .order_by(TopicCandidate.score.desc())
        .all()
    )
    return {
        "date": key,
        "total": len(rows),
        "items": [
            {
                "id": r.id,
                "title": r.title,
                "platform": r.platform,
                "score": r.score,
                "reason": r.reason,
                "draft_id": r.draft_id,
            }
            for r in rows
        ],
    }
