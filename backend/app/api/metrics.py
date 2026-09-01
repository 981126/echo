"""指标接口：手动录入 / 批量导入 / 抓取触发 / 查询。"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..db import get_db
from ..models.video import Video
from ..services.metrics import fetch_daily, import_snapshots, series_for_video, summary, upsert_snapshot

router = APIRouter()


class MetricIn(BaseModel):
    video_id: int
    snapshot_date: str
    plays: int = 0
    likes: int = 0
    favorites: int = 0
    comments: int = 0
    followers_gained: int = 0


class ImportIn(BaseModel):
    rows: list[MetricIn]


@router.get("/summary")
def get_summary(db: Session = Depends(get_db)):
    return summary(db)


@router.get("/video/{video_id}")
def get_series(video_id: int, db: Session = Depends(get_db)):
    if db.get(Video, video_id) is None:
        raise HTTPException(status_code=404, detail="视频不存在")
    return {"video_id": video_id, "series": series_for_video(db, video_id)}


@router.post("")
def add_metric(payload: MetricIn, db: Session = Depends(get_db)):
    if db.get(Video, payload.video_id) is None:
        raise HTTPException(status_code=404, detail="视频不存在")
    row = upsert_snapshot(db, payload.video_id, payload.snapshot_date, payload.model_dump(), source="manual")
    return {"id": row.id, "video_id": row.video_id, "snapshot_date": row.snapshot_date}


@router.post("/import")
def import_metrics(payload: ImportIn, db: Session = Depends(get_db)):
    count = import_snapshots(db, [r.model_dump() for r in payload.rows])
    return {"imported": count}


@router.post("/fetch")
def trigger_fetch(db: Session = Depends(get_db)):
    """每日 cookie 抓取（best-effort）；mock 模式不造假数据。"""
    return fetch_daily(db)
