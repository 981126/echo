"""每日流水线接口：手动触发 + 状态查看。"""
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..db import get_db
from ..models.pipeline import PipelineRun
from ..services.pipeline import run_daily_pipeline
from ..tasks import start_task

router = APIRouter()


class RunIn(BaseModel):
    force: bool = False


def _pipeline_task(db: Session, payload: dict) -> None:
    run_daily_pipeline(db, force=bool(payload.get("force")))


@router.post("/run")
def trigger_pipeline(payload: RunIn = RunIn(), db: Session = Depends(get_db)):
    task_id = start_task("daily_pipeline", {"force": payload.force}, _pipeline_task)
    return {"task_id": task_id}


@router.get("/status")
def pipeline_status(db: Session = Depends(get_db)):
    run = db.query(PipelineRun).order_by(PipelineRun.id.desc()).first()
    if run is None:
        return {"run_date": "", "status": "never", "generated_count": 0, "error": ""}
    return {
        "run_date": run.run_date,
        "status": run.status,
        "candidates_count": run.candidates_count,
        "generated_count": run.generated_count,
        "error": run.error,
    }
