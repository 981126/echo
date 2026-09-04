"""脚本草稿接口：工作台创建/改写/保存 + 反馈 + 生成。"""

from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..db import get_db
from ..models.draft import Draft
from ..schemas.draft import DraftCreate, DraftOut, DraftUpdate
from ..services.diff_analysis import apply_diff_suggestions
from ..services.feedback import add_feedback
from ..services.generation import generate_draft
from ..tasks import start_task

router = APIRouter()


class GenerateIn(BaseModel):
    topic: str


class FeedbackIn(BaseModel):
    liked: bool | None = None
    rating: int | None = Field(default=None, ge=1, le=5)
    comment: str = ""


def _diff_task(db: Session, payload: dict) -> None:
    draft = db.get(Draft, int(payload["draft_id"]))
    if draft:
        apply_diff_suggestions(db, draft)


@router.post("/generate", response_model=DraftOut)
def generate(payload: GenerateIn, db: Session = Depends(get_db)):
    """根据选题生成三件套（标题/封面字/脚本）+ 平台外壳。"""
    return generate_draft(db, payload.topic)


@router.post("/generate-async", response_model=dict)
def generate_async(payload: GenerateIn, db: Session = Depends(get_db)):
    """双模型讨论生成（R-023）：先建占位草稿，后台 初稿→5轮讨论→定稿；完成后通知跳转草稿。"""
    from ..services.debate import run_debate_draft

    topic = (payload.topic or "").strip()
    if not topic:
        raise HTTPException(status_code=400, detail="选题不能为空")
    draft = Draft(title=topic, cover_text="", script="（双模型讨论生成中…）", source="ai")
    db.add(draft)
    db.commit()
    db.refresh(draft)
    task_id = start_task(
        "generate_draft",
        {"draft_id": draft.id, "topic": topic},
        run_debate_draft,
    )
    return {"task_id": task_id, "draft_id": draft.id}


@router.get("/{draft_id}/debate-status", response_model=dict)
def debate_status(draft_id: int, db: Session = Depends(get_db)):
    """当前双模型讨论进行到哪一步（思考中提示）。"""
    from ..models.kv import Kv

    row = db.get(Kv, f"debate:{draft_id}")
    return {"status": row.value if row else None}


@router.get("/{draft_id}/discussions", response_model=list[dict])
def list_discussions(draft_id: int, db: Session = Depends(get_db)):
    """脚本讨论留痕（R-023）：按轮次返回聊天式消息。"""
    from ..models.discussion import DraftDiscussion

    rows = (
        db.query(DraftDiscussion)
        .filter(DraftDiscussion.draft_id == draft_id)
        .order_by(DraftDiscussion.id)
        .all()
    )
    return [
        {
            "id": r.id,
            "round": r.round,
            "actor": r.actor,
            "kind": r.kind,
            "content": r.content,
            "created_at": r.created_at.isoformat(),
        }
        for r in rows
    ]


@router.post("/{draft_id}/feedback", response_model=dict)
def feedback(draft_id: int, payload: FeedbackIn, db: Session = Depends(get_db)):
    if db.get(Draft, draft_id) is None:
        raise HTTPException(status_code=404, detail="草稿不存在")
    row = add_feedback(db, draft_id, payload.liked, payload.rating, payload.comment)
    return {"id": row.id, "liked": row.liked, "rating": row.rating}


@router.get("", response_model=list[DraftOut])
def list_drafts(status: str = "", limit: int = 100, db: Session = Depends(get_db)):
    q = db.query(Draft)
    if status:
        q = q.filter(Draft.status == status)
    return q.order_by(Draft.updated_at.desc()).limit(limit).all()


@router.post("", response_model=DraftOut)
def create_draft(payload: DraftCreate, db: Session = Depends(get_db)):
    data = payload.model_dump()
    data["platform_shells"] = json.dumps(data.get("platform_shells") or {}, ensure_ascii=False)
    draft = Draft(**data)
    db.add(draft)
    db.commit()
    db.refresh(draft)
    return draft


@router.get("/{draft_id}", response_model=DraftOut)
def get_draft(draft_id: int, db: Session = Depends(get_db)):
    draft = db.get(Draft, draft_id)
    if draft is None:
        raise HTTPException(status_code=404, detail="草稿不存在")
    return draft


@router.patch("/{draft_id}", response_model=DraftOut)
def update_draft(draft_id: int, payload: DraftUpdate, db: Session = Depends(get_db)):
    draft = db.get(Draft, draft_id)
    if draft is None:
        raise HTTPException(status_code=404, detail="草稿不存在")
    data = payload.model_dump(exclude_unset=True)
    if "platform_shells" in data:
        data["platform_shells"] = json.dumps(data["platform_shells"] or {}, ensure_ascii=False)
    for field, value in data.items():
        setattr(draft, field, value)
    db.commit()
    db.refresh(draft)
    # 改稿差异分析（异步，学习作者的改写偏好）
    if draft.original_script and draft.script and draft.script != draft.original_script:
        start_task("diff_analysis", {"draft_id": draft.id}, _diff_task)
    return draft
