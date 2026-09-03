"""AI 提示词版本管理接口（R-021）。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..db import get_db
from ..models.notification import Notification
from ..models.prompt import AiPrompt
from ..services import prompt_service
from ..tasks import start_task

router = APIRouter()


class PromptSaveIn(BaseModel):
    content: str


class PromptEnableIn(BaseModel):
    version: int


class PromptOptimizeIn(BaseModel):
    material: str = ""


def _out(row: AiPrompt) -> dict:
    return {
        "id": row.id,
        "key": row.key,
        "version": row.version,
        "content": row.content,
        "status": row.status,
        "note": row.note,
        "created_at": row.created_at.isoformat(),
    }


@router.get("/keys", response_model=list[dict])
def list_keys(db: Session = Depends(get_db)):
    """每个功能：当前启用版本摘要 + 是否有候选。"""
    rows = db.query(AiPrompt).order_by(AiPrompt.key, AiPrompt.version.desc()).all()
    by_key: dict[str, dict] = {}
    for r in rows:
        k = r.key
        if k not in by_key:
            by_key[k] = {"key": k, "label": prompt_service.label(k), "versions": []}
        by_key[k]["versions"].append(_out(r))
    out = []
    for k, item in by_key.items():
        enabled = next((v for v in item["versions"] if v["status"] == "enabled"), None)
        candidate = next((v for v in item["versions"] if v["status"] == "candidate"), None)
        out.append(
            {
                "key": k,
                "label": item["label"],
                "enabled_version": enabled["version"] if enabled else 0,
                "content": enabled["content"] if enabled else "",
                "has_candidate": candidate is not None,
                "candidate_version": candidate["version"] if candidate else 0,
                "versions": item["versions"][:30],
            }
        )
    return out


@router.get("/{key}/versions", response_model=list[dict])
def list_versions(key: str, db: Session = Depends(get_db)):
    rows = (
        db.query(AiPrompt)
        .filter(AiPrompt.key == key)
        .order_by(AiPrompt.version.desc())
        .all()
    )
    return [_out(r) for r in rows]


def _selfcheck_task(db: Session, payload: dict) -> None:
    """启用新版生成提示词后，用金样本选题自动生成一轮供作者打分（R-022）。"""
    from ..models.feedback import Feedback
    from ..models.hot_topic import TopicCandidate
    from ..services.generation import generate_draft

    version = payload.get("version", 0)
    try:
        ids = [
            r[0]
            for r in db.query(Feedback.draft_id)
            .filter((Feedback.rating >= 4) | (Feedback.liked.is_(True)))
            .distinct()
            .limit(5)
            .all()
        ]
        topics = []
        if ids:
            topics = [
                r.title
                for r in db.query(TopicCandidate)
                .filter(TopicCandidate.draft_id.in_(ids))
                .order_by(TopicCandidate.id.desc())
                .limit(3)
                .all()
            ]
        if not topics:
            return  # 暂无金样本，跳过自测
        made = 0
        for tp in topics:
            try:
                generate_draft(db, tp)
                made += 1
            except Exception:  # noqa: BLE001 单条失败不影响其余
                db.rollback()
        db.add(
            Notification(
                kind="prompt_selfcheck",
                status="done",
                title=f"提示词 v{version} 已启用 · 自测完成",
                message=f"已按金样本选题生成 {made} 篇，请到脚本工作台打分",
                target="/drafts",
            )
        )
        db.commit()
    except Exception:  # noqa: BLE001
        db.rollback()


@router.post("/{key}/save", response_model=dict)
def save_prompt(key: str, payload: PromptSaveIn, db: Session = Depends(get_db)):
    if key not in prompt_service.PROMPT_META:
        raise HTTPException(status_code=404, detail="未知提示词类别")
    row = prompt_service.save_new_version(db, key, payload.content)
    if key == "generation":
        start_task("prompt_selfcheck", {"version": row.version}, _selfcheck_task)
    return _out(row)


@router.post("/{key}/enable", response_model=dict)
def enable_prompt(key: str, payload: PromptEnableIn, db: Session = Depends(get_db)):
    row = prompt_service.enable_version(db, key, payload.version)
    if row is None:
        raise HTTPException(status_code=404, detail="版本不存在")
    if key == "generation":
        start_task("prompt_selfcheck", {"version": row.version}, _selfcheck_task)
    return _out(row)


@router.post("/{key}/optimize", response_model=dict)
def optimize_prompt(key: str, payload: PromptOptimizeIn, db: Session = Depends(get_db)):
    if key not in prompt_service.PROMPT_META:
        raise HTTPException(status_code=404, detail="未知提示词类别")
    row = prompt_service.optimize(db, key, payload.material or "")
    if row is None:
        raise HTTPException(status_code=502, detail="优化失败（AI 服务不可用或结果为空），当前版本保持不变")
    return _out(row)
