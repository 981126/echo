"""AI 提示词版本管理接口（R-021）。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..db import get_db
from ..models.notification import Notification
from ..models.prompt import AiPrompt
from ..services import prompt_service
from ..tasks import find_running_task, start_task

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


def _eval_out(row) -> dict | None:
    """评测结果摘要（R-129 M115）。"""
    if row is None:
        return None
    import json

    try:
        detail = json.loads(row.detail or "{}")
    except (TypeError, ValueError):
        detail = {}
    return {
        "candidate_version": row.candidate_version,
        "base_version": row.base_version,
        "candidate_score": row.candidate_score,
        "base_score": row.base_score,
        "supported": row.supported,
        "reason": row.reason,
        "detail": detail,
        "created_at": row.created_at.isoformat(),
    }


@router.get("/keys", response_model=list[dict])
def list_keys(db: Session = Depends(get_db)):
    """每个功能：当前启用版本 + 候选 + 最近一次评测 + 版本效果对比（R-129）。"""
    from ..services import prompt_eval

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
                "group": prompt_service.prompt_group(k),
                "enabled_version": enabled["version"] if enabled else 0,
                "content": enabled["content"] if enabled else "",
                "has_candidate": candidate is not None,
                "candidate_version": candidate["version"] if candidate else 0,
                "candidate_content": candidate["content"] if candidate else "",
                "candidate_note": candidate["note"] if candidate else "",
                "eval": _eval_out(prompt_eval.latest_eval(db, k)),
                "effect": prompt_service.version_effect(db, k),
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
                generate_draft(db, tp, snapshot=False)  # R-157：金样本自测不留版本
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
    """产出候选（R-129：按 key 语料 + 契约自检 + 自动排队金样本评测）。

    R-202：改为后台任务，点完返回 `task_id`；失败原因在 `task.error`（前端任务态提示）。
    """
    if key not in prompt_service.PROMPT_META:
        raise HTTPException(status_code=404, detail="未知提示词类别")
    tid = find_running_task("prompt_optimize", {"key": key})
    if tid:
        return {"task_id": tid}
    return {"task_id": start_task("prompt_optimize", {"key": key, "material": payload.material or ""}, prompt_service.optimize_task)}


@router.post("/optimize-rules", response_model=dict)
def optimize_rule_keys(db: Session = Depends(get_db)):
    """一键为规则型提示词（预打标/校对/改稿差异/复盘）产出候选（R-131；自动触发已取消）。"""
    from ..models.task import BackgroundTask

    dup = (
        db.query(BackgroundTask)
        .filter(BackgroundTask.kind == "prompt_rule_optimize", BackgroundTask.status.in_(["pending", "running"]))
        .first()
    )
    if dup is not None:
        raise HTTPException(status_code=409, detail="已有规则型提示词优化任务进行中，请稍候再试")
    task_id = start_task("prompt_rule_optimize", {"keys": list(prompt_service.RULE_KEYS)}, prompt_service.optimize_rule_keys_task)
    return {"task_id": task_id}


@router.post("/{key}/candidates/{version}/reject", response_model=dict)
def reject_candidate(key: str, version: int, db: Session = Depends(get_db)):
    """拒绝候选（R-129 M116）：留痕为 rejected，不再占用「待启用」入口。"""
    row = prompt_service.reject_candidate(db, key, version)
    if row is None:
        raise HTTPException(status_code=404, detail="候选不存在或已被处理")
    return _out(row)


@router.post("/{key}/eval/rerun", response_model=dict)
def rerun_eval(key: str, payload: PromptEnableIn, db: Session = Depends(get_db)):
    """重跑某候选版的金样本回放评分（R-129 M115）。"""
    from ..services import prompt_eval

    row = (
        db.query(AiPrompt)
        .filter(AiPrompt.key == key, AiPrompt.version == payload.version)
        .first()
    )
    if row is None:
        raise HTTPException(status_code=404, detail="版本不存在")
    task_id = prompt_eval.start_prompt_eval(db, key, payload.version)
    return {"task_id": task_id}
