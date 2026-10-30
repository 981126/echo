"""博主对标（R-097）：前3+最新展示（R-174，原 R-152 前2+最新） + 可讲分析 + 按人设洗稿存草稿。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..db import get_db
from ..models.platform import Creator
from ..services.benchmark import (
    analyze_worker,
    benchmarks_of_owner,
    benchmarks_top,
    prepare_worker,
    rerun_worker,
    resolve_rewrite_source,
    rewrite_worker,
)
from ..services.creator_service import get_current_creator
from ..tasks import find_running_task, start_task

router = APIRouter()


def _owner(db: Session) -> Creator:
    owner = get_current_creator(db)
    if owner is None:
        raise HTTPException(status_code=400, detail="请先创建并切换到主博主")
    return owner


@router.get("/top", response_model=dict)
def benchmark_top(db: Session = Depends(get_db)):
    """每个对标博主：最新15条里按互动分取前3 + 第四篇=该对标最新一篇（R-174，原 R-152 前2+最新）。

    尚未转写的可先展示占位，需先 prepare；展示时仍「有文案优先」（R-106）。
    R-240 S1：候选/文案/统计/分析各一次批量预取，SQL 数不随对标数增长（数据与排序口径不变）。
    """
    return benchmarks_top(db, _owner(db))


class PrepareIn(BaseModel):
    benchmark_id: int


@router.post("/prepare", response_model=dict)
def benchmark_prepare(payload: PrepareIn, db: Session = Depends(get_db)):
    """对某个对标博主补齐文案（前3+最新缺转写自动下载+转写，无文案顺延）。

    R-202：改为后台任务（转写耗时可能几分钟），点完即返回 `task_id`，前端任务态显示进行中；
    完成后刷新 `/top` 即可（结果已落库）。
    """
    owner = _owner(db)
    bm = db.get(Creator, payload.benchmark_id)
    if bm is None or bm.kind != "benchmark" or bm.parent_id != owner.id:
        raise HTTPException(status_code=404, detail="对标博主不存在")
    tid = find_running_task("benchmark_prepare", {"benchmark_id": bm.id})
    if tid:
        return {"task_id": tid}
    return {"task_id": start_task("benchmark_prepare", {"benchmark_id": bm.id, "owner_id": owner.id}, prepare_worker)}


class TextIn(BaseModel):
    title: str = ""
    text: str = ""
    key: str = ""
    benchmark_name: str = ""
    post_id: int | None = None
    work_id: int | None = None
    tags: list[str] = []


@router.post("/analyze", response_model=dict)
def benchmark_analyze(payload: TextIn, db: Session = Depends(get_db)):
    owner = _owner(db)
    task_id = start_task(
        "benchmark_analyze",
        {"owner_id": owner.id, "key": payload.key, "title": payload.title, "text": payload.text},
        analyze_worker,
    )
    return {"task_id": task_id}


@router.post("/rewrite", response_model=dict)
def benchmark_rewrite(payload: TextIn, db: Session = Depends(get_db)):
    owner = _owner(db)
    task_id = start_task(
        "benchmark_rewrite",
        {
            "owner_id": owner.id,
            "key": payload.key,
            "title": payload.title,
            "text": payload.text,
            "benchmark_name": payload.benchmark_name,
            "post_id": payload.post_id,
            "work_id": payload.work_id,
            "tags": payload.tags,
        },
        rewrite_worker,
    )
    return {"task_id": task_id}


class RewriteSourceIn(BaseModel):
    video_id: int | None = None
    post_id: int | None = None
    work_id: int | None = None


@router.post("/rewrite-source", response_model=dict)
def benchmark_rewrite_source(payload: RewriteSourceIn, db: Session = Depends(get_db)):
    """R-152：素材库非主博主素材一键洗稿——服务端按素材取 ASR 文案，走同一洗稿链路。

    入参三选一：本地素材 video_id / 云端作品 work_id / 云端单条 post_id。
    """
    owner = _owner(db)
    try:
        src = resolve_rewrite_source(
            db,
            owner,
            video_id=int(payload.video_id or 0),
            post_id=int(payload.post_id or 0),
            work_id=int(payload.work_id or 0),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    task_id = start_task("benchmark_rewrite", {"owner_id": owner.id, **src}, rewrite_worker)
    return {"task_id": task_id}


@router.post("/rerun", response_model=dict)
def benchmark_rerun(db: Session = Depends(get_db)):
    """R-102/R-104/R-109/R-152：页面顶部「重新对标」——重跑当前主博主所有对标：重捞最新15条 + 自动补「前3+最新」文案。

    长任务（含同步与转写，可能较久）：落后台任务+进度+完成通知，返回 task_id 供前端轮询。
    """
    owner = _owner(db)
    if not benchmarks_of_owner(db, owner):
        raise HTTPException(status_code=400, detail="还没有对标博主，先去「博主管理」添加")
    task_id = start_task("benchmark_rerun", {"owner_id": owner.id}, rerun_worker)
    return {"task_id": task_id}
