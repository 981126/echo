"""人设档案接口：查看/手动添加/确认或拒绝 AI 建议/触发初始化。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..db import get_db
from ..services.creator_service import current_creator_id
from ..models.persona import PersonaCheck, PersonaTag
from ..schemas.persona import (
    PersonaCheckOut,
    PersonaDecision,
    PersonaTagCreate,
    PersonaTagOut,
    PersonaTagUpdate,
)
from ..services.ingest import persona_init_task, persona_incremental_task
from ..tasks import start_task

router = APIRouter()


@router.get("", response_model=list[PersonaTagOut])
def list_persona(status: str = "", db: Session = Depends(get_db)):
    q = db.query(PersonaTag)
    cid = current_creator_id(db)
    if cid:
        q = q.filter(PersonaTag.creator_id == cid)
    if status:
        q = q.filter(PersonaTag.status == status)
    return q.order_by(PersonaTag.category, PersonaTag.id).all()



@router.post("/confirm-all", response_model=dict)
def confirm_all_suggested(db: Session = Depends(get_db)):
    """一键把当前博主的全部「待确认建议」标记为已确认。"""
    q = db.query(PersonaTag).filter(PersonaTag.status == "suggested")
    cid = current_creator_id(db)
    if cid:
        q = q.filter(PersonaTag.creator_id == cid)
    count = q.update({"status": "confirmed"}, synchronize_session=False)
    db.commit()
    return {"ok": True, "count": count}


@router.post("/reject-all", response_model=dict)
def reject_all_suggested(db: Session = Depends(get_db)):
    """一键把当前博主的全部「待确认建议」标记为已拒绝（R-123，与单条拒绝同语义留痕）。"""
    q = db.query(PersonaTag).filter(PersonaTag.status == "suggested")
    cid = current_creator_id(db)
    if cid:
        q = q.filter(PersonaTag.creator_id == cid)
    count = q.update({"status": "rejected"}, synchronize_session=False)
    db.commit()
    return {"ok": True, "count": count}

@router.post("/tags", response_model=PersonaTagOut)
def add_manual_tag(payload: PersonaTagCreate, db: Session = Depends(get_db)):
    data = {k: v for k, v in payload.model_dump().items() if k != "source"}
    tag = PersonaTag(**data, source="manual", status="confirmed", creator_id=current_creator_id(db))
    db.add(tag)
    db.commit()
    db.refresh(tag)
    return tag


@router.post("/tags/{tag_id}/decision", response_model=PersonaTagOut)
def decide_tag(tag_id: int, payload: PersonaDecision, db: Session = Depends(get_db)):
    tag = db.get(PersonaTag, tag_id)
    if tag is None:
        raise HTTPException(status_code=404, detail="标签不存在")
    tag.status = payload.status
    db.commit()
    db.refresh(tag)
    return tag


@router.patch("/tags/{tag_id}", response_model=PersonaTagOut)
def update_tag(tag_id: int, payload: PersonaTagUpdate, db: Session = Depends(get_db)):
    """编辑人设标签（标签/描述/类别）。"""
    tag = db.get(PersonaTag, tag_id)
    if tag is None:
        raise HTTPException(status_code=404, detail="标签不存在")
    if payload.label.strip():
        tag.label = payload.label.strip()
    tag.description = payload.description
    tag.dimension = (payload.dimension or "").strip()[:30]
    tag.category = payload.category
    db.commit()
    db.refresh(tag)
    return tag


@router.delete("/tags/{tag_id}", response_model=dict)
def delete_tag(tag_id: int, db: Session = Depends(get_db)):
    """删除人设标签。"""
    tag = db.get(PersonaTag, tag_id)
    if tag is None:
        raise HTTPException(status_code=404, detail="标签不存在")
    db.delete(tag)
    db.commit()
    return {"ok": True}


class BatchDeleteIn(BaseModel):
    ids: list[int] = []


@router.post("/tags/batch-delete", response_model=dict)
def batch_delete_tags(payload: BatchDeleteIn, db: Session = Depends(get_db)):
    """批量删除人设标签（已确认档案多选删除，R-123）。只删当前博主的标签，找不到的忽略。"""
    ids = [int(x) for x in (payload.ids or [])]
    if not ids:
        return {"ok": True, "deleted": 0}
    q = db.query(PersonaTag).filter(PersonaTag.id.in_(ids))
    cid = current_creator_id(db)
    if cid:
        q = q.filter(PersonaTag.creator_id == cid)
    rows = q.all()
    for tag in rows:
        db.delete(tag)
    db.commit()
    return {"ok": True, "deleted": len(rows)}


@router.get("/phrases/suggest", response_model=dict)
def suggest_phrases(limit: int = 12, db: Session = Depends(get_db)):
    """像我金句库（R-030③）：从高表现素材提取短句候选，供作者一键收为风格锚点。"""
    from ..services.persona import suggest_phrase_candidates

    items = suggest_phrase_candidates(db, limit=max(1, min(limit, 30)))
    return {"items": items}


@router.post("/init")
def init_persona(db: Session = Depends(get_db)):
    """用全部历史转写稿初始化/刷新人设档案（后台任务，建议非广告视频转写完成后调用）。

    R-125：已有进行中(pending/running)的 persona_init 时拒绝重复入队，防连点/重复点击重复生成。
    """
    from ..models.task import BackgroundTask

    dup = (
        db.query(BackgroundTask)
        .filter(BackgroundTask.kind == "persona_init", BackgroundTask.status.in_(["pending", "running"]))
        .order_by(BackgroundTask.id.desc())
        .first()
    )
    if dup is not None:
        raise HTTPException(status_code=409, detail="已有「用历史转写稿初始化人设」任务进行中，请稍候再试")
    cid = current_creator_id(db)
    task_id = start_task("persona_init", {"creator_id": cid}, persona_init_task)
    return {"task_id": task_id}


# ---------- 增量 vs 全量 5% 对齐校验（R-128） ----------
@router.get("/check/latest", response_model=PersonaCheckOut | None)
def latest_persona_check(db: Session = Depends(get_db)):
    """返回当前博主最近一次「增量 vs 全量」对齐校验结果（无则 null）。"""
    q = db.query(PersonaCheck)
    cid = current_creator_id(db)
    if cid:
        q = q.filter(PersonaCheck.creator_id == cid)
    return q.order_by(PersonaCheck.id.desc()).first()


@router.post("/recheck", response_model=dict)
def recheck_persona(db: Session = Depends(get_db)):
    """手动重跑一次增量人设校验（增量 + 全量重算对照），进行中拒绝重复入队（R-128）。"""
    from ..models.task import BackgroundTask

    dup = (
        db.query(BackgroundTask)
        .filter(BackgroundTask.kind == "persona_incremental", BackgroundTask.status.in_(["pending", "running"]))
        .order_by(BackgroundTask.id.desc())
        .first()
    )
    if dup is not None:
        raise HTTPException(status_code=409, detail="已有「人设增量校验」任务进行中，请稍候再试")
    cid = current_creator_id(db)
    task_id = start_task(
        "persona_incremental", {"creator_id": cid, "video_id": 0, "manual": True}, persona_incremental_task
    )
    return {"task_id": task_id}


# ---------- 表达风格（R-057）：画像查看 + AI 腔禁用词编辑 ----------
@router.get("/style", response_model=dict)
def style_overview(db: Session = Depends(get_db)):
    """返回自动统计的作者语言习惯 + 当前 AI 腔禁用词清单 + 表现最好的素材节选。"""
    import json

    from ..core.style_profile import build_style_profile, default_avoid_words, format_style_profile
    from ..services.generation import _all_texts, _weight
    from ..models.kv import Kv

    rows = _all_texts(db)
    texts = [t for _, t in rows]
    profile = build_style_profile(texts)
    row = db.get(Kv, "ai_no_words")
    avoid = []
    if row is not None:
        try:
            avoid = [str(x).strip() for x in json.loads(row.value or "[]") if str(x).strip()]
        except (TypeError, ValueError):
            avoid = []
    weighted = sorted(rows, key=lambda vt: _weight(db, vt[0]), reverse=True)[:3]
    return {
        "count": len(texts),
        "profile": format_style_profile(profile),
        "avoid_words": avoid or default_avoid_words(),
        "top_weighted": [
            {"title": v.title or "", "text": text[:300]} for v, text in weighted
        ],
    }


@router.put("/style", response_model=dict)
def save_style_words(payload: dict, db: Session = Depends(get_db)):
    """保存 AI 腔禁用/少用词（存 [] 表示关闭内置清单）。"""
    import json

    from ..models.kv import Kv

    words = payload.get("avoid_words")
    if not isinstance(words, list):
        raise HTTPException(status_code=400, detail="avoid_words 必须是数组")
    cleaned = [str(x).strip() for x in words if str(x).strip()]
    row = db.get(Kv, "ai_no_words")
    if row is None:
        row = Kv(key="ai_no_words", value=json.dumps(cleaned, ensure_ascii=False))
        db.add(row)
    else:
        row.value = json.dumps(cleaned, ensure_ascii=False)
    db.commit()
    return {"ok": True, "avoid_words": cleaned}

