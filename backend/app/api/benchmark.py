"""博主对标（R-097）：Top3 展示 + 可讲分析 + 按人设洗稿存草稿。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..db import get_db
from ..models.platform import Creator
from ..services.benchmark import (
    _stats_map,
    _unit_text,
    benchmarks_of_owner,
    candidates,
    ensure_top3_with_text,
    score_unit,
    unit_payload,
    analyze_text,
    rerun_worker,
    rewrite_text,
    set_analysis,
)
from ..services.creator_service import get_current_creator
from ..tasks import start_task

router = APIRouter()


def _owner(db: Session) -> Creator:
    owner = get_current_creator(db)
    if owner is None:
        raise HTTPException(status_code=400, detail="请先创建并切换到主博主")
    return owner


@router.get("/top", response_model=dict)
def benchmark_top(db: Session = Depends(get_db)):
    """每个对标博主：最新15条里按互动分取前3（R-109：10 → 15；尚未转写的可先展示占位，需先 prepare）。"""
    owner = _owner(db)
    out = []
    for bm in benchmarks_of_owner(db, owner):
        units = candidates(db, bm, limit=15)
        stats_map = _stats_map(db, units)
        ranked = sorted(units, key=lambda u: score_unit(db, u, stats_map), reverse=True)
        # R-106：有文案（含转写）的优先占位；空文案/空转写由下一条有文案的顶上，
        # 仍不足 3 条时才用分数最高的无文案项补位展示（提示“暂无文案”）
        with_text = [u for u in ranked if _unit_text(db, u)]
        without_text = [u for u in ranked if not _unit_text(db, u)]
        ordered = with_text + without_text
        items = [unit_payload(db, u, stats_map, owner_id=owner.id) for u in ordered[:3]]
        out.append({"benchmark_id": bm.id, "name": bm.name, "note": bm.note or "", "items": items})
    return {"owner_id": owner.id, "owner_name": owner.name, "benchmarks": out}


class PrepareIn(BaseModel):
    benchmark_id: int


@router.post("/prepare", response_model=dict)
def benchmark_prepare(payload: PrepareIn, db: Session = Depends(get_db)):
    """对某个对标博主补齐文案（缺转写自动下载+转写，无文案顺延），返回有文案的 Top3。

    同步执行，转写耗时可能几分钟；前端给 loading 提示。
    """
    owner = _owner(db)
    bm = db.get(Creator, payload.benchmark_id)
    if bm is None or bm.kind != "benchmark" or bm.parent_id != owner.id:
        raise HTTPException(status_code=404, detail="对标博主不存在")
    picked = ensure_top3_with_text(db, bm, limit_candidates=15)  # R-109：10 → 15
    items = []
    for u in picked:
        items.append(unit_payload(db, u, owner_id=owner.id))
    return {"benchmark_id": bm.id, "name": bm.name, "items": items}


class TextIn(BaseModel):
    title: str = ""
    text: str = ""
    key: str = ""


@router.post("/analyze", response_model=dict)
def benchmark_analyze(payload: TextIn, db: Session = Depends(get_db)):
    owner = _owner(db)
    res = analyze_text(db, owner, payload.text)
    res["ok"] = not res.get("reason", "").startswith("AI 分析暂不可用")
    if payload.key:
        set_analysis(
            db,
            owner.id,
            payload.key,
            {
                "can": bool(res.get("can")),
                "reason": str(res.get("reason") or ""),
                "suggestion": str(res.get("suggestion") or ""),
            },
        )
    return res


@router.post("/rewrite", response_model=dict)
def benchmark_rewrite(payload: TextIn, db: Session = Depends(get_db)):
    owner = _owner(db)
    try:
        res = rewrite_text(db, owner, payload.title, payload.text)
        res["ok"] = True
        return res
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/rerun", response_model=dict)
def benchmark_rerun(db: Session = Depends(get_db)):
    """R-102/R-104/R-109：页面顶部「重新对标」——重跑当前主博主所有对标：重捞最新15条 + 自动补 Top3 文案。

    长任务（含同步与转写，可能较久）：落后台任务+进度+完成通知，返回 task_id 供前端轮询。
    """
    owner = _owner(db)
    if not benchmarks_of_owner(db, owner):
        raise HTTPException(status_code=400, detail="还没有对标博主，先去「博主管理」添加")
    task_id = start_task("benchmark_rerun", {"owner_id": owner.id}, rerun_worker)
    return {"task_id": task_id}
