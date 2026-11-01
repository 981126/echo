"""R-244 抖音数据看板接口（薄路由，业务在 services/douyin_dashboard.py）。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from ..db import get_db
from ..schemas.douyin_dashboard import RefreshIn
from ..services import douyin_dashboard as service
from ..services.ingest import import_video_task
from ..services.douyin_creator_sync import CredentialError
from ..tasks import find_running_task, start_task

router = APIRouter()


def _call(fn):
    try:
        return fn()
    except CredentialError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/overview", response_model=dict)
def overview(
    period: int = Query(default=7, description="统计周期天数：7/14/30/90"),
    db: Session = Depends(get_db),
):
    """账号总览：诊断缓存 + 本地快照 KPI/各指标逐日曲线（无账号时返回 200 空状态）。"""
    return _call(lambda: service.overview(db, period))


@router.get("/works", response_model=dict)
def works(
    limit: int = Query(default=20, ge=1, le=50),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
):
    """近期作品列表（按发布时间倒序，本地数据）。"""
    return _call(lambda: service.list_works(db, limit, offset))


@router.get("/works/{post_id}", response_model=dict)
def work_detail(post_id: int, db: Session = Depends(get_db)):
    """单条作品分析：总览/流量/观众/评论热词/评论管理数据（缓存，6h）。"""
    return _call(lambda: service.post_detail(db, post_id))


@router.post("/overview/refresh")
def refresh_overview(db: Session = Depends(get_db)):
    """账号「更新数据」后台任务（诊断 + 投稿概览 + 作品快照，5 次 TikHub 请求）。"""

    def run():
        running = find_running_task("douyin_dashboard_overview")
        if running:
            return JSONResponse(status_code=202, content={"task_id": running, "reused": True})
        plan = service.prepare_overview_refresh(db)
        task_id = start_task("douyin_dashboard_overview", plan, service.overview_worker)
        return JSONResponse(status_code=202, content={"task_id": task_id, "reused": False})

    return _call(run)


@router.post("/works/{post_id}/transcribe")
def transcribe_work(post_id: int, db: Session = Depends(get_db)):
    """作品「ASR 转写」后台任务：复用素材库的 import_video 转写任务（需有关联本地视频）。"""

    def run():
        plan = service.prepare_transcribe(db, post_id)
        running = find_running_task("import_video", {"video_id": plan["video_id"]})
        if running:
            return JSONResponse(status_code=202, content={"task_id": running, "reused": True})
        task_id = start_task("import_video", plan, import_video_task)
        return JSONResponse(status_code=202, content={"task_id": task_id, "reused": False})

    return _call(run)


@router.post("/works/{post_id}/refresh")
def refresh_work(post_id: int, payload: RefreshIn | None = None, db: Session = Depends(get_db)):
    """作品「更新数据」后台任务（8 次 TikHub 请求）；6 小时内且非 force 直接返回 skipped。"""
    force = bool(payload.force) if payload is not None else False

    def run():
        running = find_running_task("douyin_dashboard_post", {"post_id": post_id})
        if running:
            return JSONResponse(status_code=202, content={"task_id": running, "reused": True})
        plan = service.prepare_post_refresh(db, post_id, force)
        if plan.get("skipped"):
            return plan
        task_id = start_task("douyin_dashboard_post", {**plan, "force": force}, service.post_worker)
        return JSONResponse(status_code=202, content={"task_id": task_id, "reused": False})

    return _call(run)
