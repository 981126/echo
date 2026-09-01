"""热点与选题接口。"""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..core.pipeline import today_key
from ..db import get_db
from ..models.hot_topic import HotTopic, TopicCandidate
from ..services.topic_mining import fetch_and_store

router = APIRouter()


@router.get("/hot")
def list_hot(date: str = "", db: Session = Depends(get_db)):
    key = date or today_key()
    rows = (
        db.query(HotTopic)
        .filter(HotTopic.topic_date == key)
        .order_by(HotTopic.platform, HotTopic.id.desc())
        .all()
    )
    return {
        "date": key,
        "total": len(rows),
        "items": [
            {"platform": r.platform, "title": r.title, "heat": r.heat, "url": r.url}
            for r in rows
        ],
    }


@router.post("/refresh")
def refresh_hot(db: Session = Depends(get_db)):
    """立即抓取今日热点（真实模式需 NAS 有外网）。"""
    items = fetch_and_store(db)
    return {"fetched": len(items)}


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
