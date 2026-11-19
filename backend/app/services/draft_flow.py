"""普通生成入队与洗稿/历史原文讨论入队（R-263）。"""

from __future__ import annotations

import json

from sqlalchemy.orm import Session

from ..models.author_generation import GenerationRun
from ..models.draft import Draft
from ..tasks import start_task
from . import draft_status
from .creator_service import current_creator_id
from .rewrite_debate import run_source_discussion
from .generation_pipeline import (
    GENERATION_PLACEHOLDER,
    create_generation_run,
    run_generation_pipeline,
)
from .generation_validators import json_dict


def generation_task(db: Session, payload: dict) -> dict:
    draft_id = int(payload.get("draft_id") or 0)
    run_id = int(payload.get("run_id") or 0)
    draft = db.get(Draft, draft_id)
    run = db.get(GenerationRun, run_id)
    if draft is None or run is None or run.draft_id != draft.id:
        raise ValueError("生成运行或草稿不存在")
    try:
        result = run_generation_pipeline(
            db,
            run,
            draft,
            selected_angle_id=str(payload.get("angle_id") or ""),
        )
    except Exception as exc:
        db.rollback()
        draft = db.get(Draft, draft_id) or draft
        run = db.get(GenerationRun, run_id) or run
        run.status = "failed"
        run.quality_passed = False
        run.error = str(exc)[:1000]
        if (draft.script or "") == GENERATION_PLACEHOLDER:
            draft.script = ""
        draft.quality = json.dumps(
            {"run_id": run.id, "passed": False, "review_executed": False, "error": run.error},
            ensure_ascii=False,
        )
        db.commit()
        draft_status.set_failed(db, draft_id, f"生成失败：{run.error[:150]}", kind="generate", phase=run.stage)
        raise
    if result.get("status") == "succeeded":
        from .draft_versions import finalize_version

        finalize_version(db, draft, source="ai_generate", note="AI 生成")
        draft_status.clear(db, draft_id)
    else:
        label = "待补信息" if result.get("status") == "needs_input" else "待作者修改"
        draft_status.set_failed(
            db,
            draft_id,
            f"{label}：{str(result.get('message') or '')[:150]}",
            kind="generate",
            phase=run.stage,
        )
    return result


def create_placeholder_draft(db: Session, topic: str) -> Draft:
    from .persona_profile import current_persona_version

    creator_id = current_creator_id(db)
    if creator_id is None:
        raise ValueError("请先选择当前主博主")
    draft = Draft(
        title=topic.strip(),
        cover_text="",
        script=GENERATION_PLACEHOLDER,
        source="ai",
        creator_id=creator_id,
        persona_version=current_persona_version(db, creator_id),
    )
    db.add(draft)
    db.commit()
    db.refresh(draft)
    return draft


def start_generation(db: Session, topic: str, query_source: str = "") -> tuple[int, int, int]:
    clean_topic = (topic or "").strip()
    if not clean_topic:
        raise ValueError("选题不能为空")
    draft = create_placeholder_draft(db, clean_topic)
    run = create_generation_run(
        db,
        creator_id=int(draft.creator_id or 0),
        draft_id=draft.id,
        topic=clean_topic,
        query_source=query_source.strip(),
    )
    draft_status.set_running(db, draft.id, f"正在生成《{clean_topic[:20]}》…", kind="generate", phase="queued")
    task_id = start_task(
        "generate_draft",
        {"draft_id": draft.id, "run_id": run.id},
        generation_task,
    )
    return task_id, draft.id, run.id


def start_rework(db: Session, draft_id: int, angle_id: str = "") -> tuple[int, int]:
    draft = db.get(Draft, draft_id)
    if draft is None:
        raise ValueError("草稿不存在")
    latest = (
        db.query(GenerationRun)
        .filter(GenerationRun.draft_id == draft.id, GenerationRun.status != "legacy")
        .order_by(GenerationRun.id.desc())
        .first()
    )
    topic = latest.topic if latest is not None else (draft.title or "").strip()
    if not topic:
        raise ValueError("这篇草稿没有可重跑的选题")
    if angle_id:
        if latest is None:
            raise ValueError("没有可复用的生成角度")
        angles = json.loads(latest.angles_json or "[]")
        angle = next((item for item in angles if item.get("angle_id") == angle_id), None)
        if angle is None or angle.get("reject_reasons") or float(angle.get("total_score") or 0) < 65:
            raise LookupError("角度不属于最近生成的合格备选角度")
    from .draft_versions import finalize_version

    finalize_version(db, draft, source="manual", note="重新生成前")
    run = create_generation_run(
        db,
        creator_id=int(draft.creator_id or current_creator_id(db) or 0),
        draft_id=draft.id,
        topic=topic,
        query_source=str(json_dict(latest.input_context).get("query_source") or "") if latest else "",
    )
    if angle_id and latest is not None:
        run.angles_json = latest.angles_json
        run.evidence_json = latest.evidence_json
        db.commit()
    draft_status.set_running(db, draft.id, "正在重新生成…", kind="rework", phase="queued")
    task_id = start_task(
        "generate_draft",
        {"draft_id": draft.id, "run_id": run.id, "angle_id": angle_id},
        generation_task,
    )
    return task_id, run.id


def resolve_discussion_source(db: Session, draft: Draft) -> tuple[str, str]:
    source = (draft.original_script or "").strip()
    if source:
        title = (draft.title or "").strip()
        try:
            ref = json.loads(draft.source_ref or "{}")
        except (TypeError, ValueError):
            ref = {}
        if isinstance(ref, dict) and ref.get("source_title"):
            title = str(ref["source_title"]).strip()
        return source, title
    return (draft.script or "").strip(), (draft.title or "").strip()


def discussion_task(db: Session, payload: dict) -> dict:
    from .draft_versions import finalize_version, list_versions

    draft_id = int(payload.get("draft_id") or 0)
    draft = db.get(Draft, draft_id)
    if draft is None:
        raise ValueError("草稿不存在")
    if draft.creator_id is None:
        draft.creator_id = current_creator_id(db)
    if not list_versions(db, draft.id):
        finalize_version(db, draft, source="ai_discuss", note="讨论前")
    source_text = str(payload.get("source_text") or "")
    source_title = str(payload.get("source_title") or "")
    topic = (draft.title or "").strip() or source_title or "重新讨论"
    try:
        result = run_source_discussion(db, draft, topic, source_text=source_text, source_title=source_title)
    except Exception as exc:
        try:
            draft_status.set_failed(db, draft_id, f"讨论中断：{str(exc)[:150]}", kind="discuss")
        except Exception:  # noqa: BLE001 标记失败不能掩盖原始错误
            db.rollback()
        raise
    finalize_version(db, draft, source="ai_discuss", note="讨论后")
    return result


def start_discussion(db: Session, draft_id: int) -> int:
    draft = db.get(Draft, draft_id)
    if draft is None:
        raise ValueError("草稿不存在")
    source_text, source_title = resolve_discussion_source(db, draft)
    if not source_text:
        raise ValueError("这篇草稿没有可讨论的原文或正文")
    draft_status.set_running(db, draft.id, "正在准备讨论…", kind="discuss", phase="queued")
    return start_task(
        "draft_discuss",
        {"draft_id": draft.id, "source_text": source_text, "source_title": source_title},
        discussion_task,
    )


__all__ = [
    "create_placeholder_draft",
    "discussion_task",
    "generation_task",
    "resolve_discussion_source",
    "start_discussion",
    "start_generation",
    "start_rework",
]
