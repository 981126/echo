"""复盘接口：生成报告 / 查看最新 / 赛道雷达。"""

from __future__ import annotations

import datetime

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..db import get_db
from ..services.review import generate_report, latest_report, _radar

router = APIRouter()


@router.post("/generate")
def generate(run_date: str = "", db: Session = Depends(get_db)):
    key = run_date or datetime.date.today().isoformat()
    report = generate_report(db, key)
    return {"report_id": report.id, "run_date": report.run_date}


@router.get("/report")
def get_report(db: Session = Depends(get_db)):
    return latest_report(db)


@router.get("/radar")
def radar(db: Session = Depends(get_db)):
    return {"radar": _radar(db)}
