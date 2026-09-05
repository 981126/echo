"""脚本草稿接口：工作台创建/改写/保存 + 反馈 + 生成。"""

from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..db import get_db
from ..services.creator_service import current_creator_id
from ..models.draft import Draft
from ..schemas.draft import DraftCreate, DraftOut, DraftUpdate
from ..services.diff_analysis import apply_diff_suggestions
from ..services.feedback import add_feedback
from ..services.generation import generate_draft
from ..services.persona import PersonaService
from ..tasks import start_task

router = APIRouter()


class GenerateIn(BaseModel):
    topic: str


class AnglesIn(BaseModel):
    topic: str
    platform: str = ""


class FeedbackIn(BaseModel):
    liked: bool | None = None
    rating: int | None = Field(default=None, ge=1, le=5)
    comment: str = ""
    hook_score: int | None = Field(default=None, ge=1, le=5)
    pace_score: int | None = Field(default=None, ge=1, le=5)
    ending_score: int | None = Field(default=None, ge=1, le=5)
    style_score: int | None = Field(default=None, ge=1, le=5)


def _diff_task(db: Session, payload: dict) -> None:
    draft = db.get(Draft, int(payload["draft_id"]))
    if draft:
        apply_diff_suggestions(db, draft)


def _rework_task(db: Session, payload: dict) -> dict:
    """一键回炉（R-030⑦）：按原选题重新生成，并把内容替换回原草稿（保留 id/反馈/讨论记录）。"""
    from .generation import generate_draft

    draft = db.get(Draft, int(payload.get("draft_id") or 0))
    if draft is None:
        return {"draft_id": 0}
    topic = (payload.get("topic") or draft.title or "").strip() or "重新生成一条口播脚本"
    fresh = generate_draft(db, topic)
    draft.title = fresh.title or draft.title
    draft.cover_text = fresh.cover_text or draft.cover_text
    draft.script = fresh.script or draft.script
    draft.platform_shells = fresh.platform_shells or draft.platform_shells
    draft.original_script = fresh.original_script or draft.original_script
    draft.source = "ai"
    db.delete(fresh)
    db.commit()
    return {"draft_id": draft.id, "title": draft.title}


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


@router.post("/angles", response_model=dict)
def suggest_angles(payload: AnglesIn, db: Session = Depends(get_db)):
    """选题→角度→草稿 三级流水（R-030）：给 3 个切入角度，作者点选后直接生成。"""
    from ..services.generation import benchmark_context_lines

    topic = (payload.topic or "").strip()
    if not topic:
        raise HTTPException(status_code=400, detail="topic 不能为空")
    persona = PersonaService()
    refs = benchmark_context_lines(db)
    system = (
        "你是短视频选题策划。针对作者给出的选题，输出 3 个不同的切入角度。"
        "每个角度要：标题抓人但不标题党、开头钩子一句能留住人、贴合作者口播风格。"
        "只输出 JSON："
        '{"angles":[{"title":"完整选题标题(直接可用于生成脚本)","hook":"开头钩子句","reason":"为什么这个角度能火"}]}'
    )
    user_parts = [f"选题：{topic}"]
    if payload.platform:
        user_parts.append(f"目标平台：{payload.platform}")
    if refs:
        user_parts.append("参考风格（仅借鉴语气/结构，观点用你自己的）：\n" + refs)
    try:
        data = persona.llm.chat_json(
            [{"role": "system", "content": system}, {"role": "user", "content": "\n".join(user_parts)}],
            temperature=0.8,
        )
        angles = []
        for a in data.get("angles") or []:
            if isinstance(a, dict) and str(a.get("title", "")).strip():
                angles.append({
                    "title": str(a["title"]).strip(),
                    "hook": str(a.get("hook", "")).strip(),
                    "reason": str(a.get("reason", "")).strip(),
                })
        if angles:
            return {"topic": topic, "angles": angles}
    except Exception:  # noqa: BLE001 无密钥/超时走启发式兜底
        pass
    return {
        "topic": topic,
        "angles": [
            {"title": f"{topic}：大多数人没想明白的 3 件事", "hook": f"关于{topic}，先说一个反常识的结论。", "reason": "反常识钩子 + 清单结构"},
            {"title": f"我亲测过{topic}，结果和你想的不一样", "hook": "一开始我也不信，直到自己踩了坑。", "reason": "第一人称故事 + 反转"},
            {"title": f"聊{topic}前，先避开这 3 个坑", "hook": "如果你正在这个话题上，这条一定要看完。", "reason": "避坑清单，实用转发高"},
        ],
    }


@router.get("/{draft_id}/check", response_model=dict)
def draft_check(draft_id: int, db: Session = Depends(get_db)):
    """脚本体检（R-030⑦）：红线/钩子/结尾引导/篇幅。"""
    draft = db.get(Draft, draft_id)
    if draft is None:
        raise HTTPException(status_code=404, detail="草稿不存在")
    from ..core.draft_check import check_script
    from ..models.persona import PersonaTag
    from ..services.creator_service import current_creator_id

    q = db.query(PersonaTag).filter(PersonaTag.category == "redline", PersonaTag.status == "confirmed")
    cid = current_creator_id(db)
    if cid:
        q = q.filter(PersonaTag.creator_id == cid)
    redlines = [t.label for t in q.all()]
    result = check_script(draft.script, redlines, draft.title)
    return {"draft_id": draft_id, **result}


@router.post("/{draft_id}/rework", response_model=dict)
def draft_rework(draft_id: int, db: Session = Depends(get_db)):
    """一键回炉（R-030⑦）：按原选题重新异步生成一轮，完成后替换草稿。"""
    draft = db.get(Draft, draft_id)
    if draft is None:
        raise HTTPException(status_code=404, detail="草稿不存在")
    task_id = start_task(
        "generate_draft",
        {"draft_id": draft.id, "topic": draft.title or ""},
        _rework_task,
    )
    return {"task_id": task_id, "message": "已提交回炉生成，完成后右上角通知"}



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
    row = add_feedback(
        db,
        draft_id,
        payload.liked,
        payload.rating,
        payload.comment,
        hook_score=payload.hook_score,
        pace_score=payload.pace_score,
        ending_score=payload.ending_score,
        style_score=payload.style_score,
    )
    return {
        "id": row.id,
        "liked": row.liked,
        "rating": row.rating,
        "hook_score": row.hook_score,
        "pace_score": row.pace_score,
        "ending_score": row.ending_score,
        "style_score": row.style_score,
    }


@router.get("", response_model=list[DraftOut])
def list_drafts(
    status: str = "",
    video_id: int | None = None,
    limit: int = 100,
    db: Session = Depends(get_db),
):
    q = db.query(Draft)
    cid = current_creator_id(db)
    if cid:
        q = q.filter(Draft.creator_id == cid)
    if status:
        q = q.filter(Draft.status == status)
    if video_id is not None:
        q = q.filter(Draft.video_id == video_id)
    return q.order_by(Draft.updated_at.desc()).limit(limit).all()


@router.post("", response_model=DraftOut)
def create_draft(payload: DraftCreate, db: Session = Depends(get_db)):
    data = payload.model_dump()
    data["platform_shells"] = json.dumps(data.get("platform_shells") or {}, ensure_ascii=False)
    data["creator_id"] = current_creator_id(db)
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
