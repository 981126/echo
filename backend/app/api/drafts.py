"""脚本草稿接口：工作台创建/改写/保存 + 反馈 + 生成。"""

from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..db import get_db
from ..models.author_generation import GenerationRun
from ..models.draft import Draft
from ..models.draft_version import DraftVersion
from ..schemas.draft import DraftCreate, DraftOut, DraftPublishIn, DraftUpdate
from ..services import draft_flow, draft_status
from ..services.creator_service import current_creator_id
from ..services.draft_meta_suggest import suggest_meta_task
from ..services.draft_versions import (
    AI_SOURCES,
    finalize_version,
    latest_comment_map,
    list_versions,
    pure_manual_map,
    version_payload,
)
from ..services.diff_analysis import diff_task
from ..services.feedback import add_feedback
from ..services.generation_pipeline import generation_run_payload
from ..tasks import find_running_task, start_task

router = APIRouter()


def _persona_version(db: Session) -> int:
    """当前人设档案版本（R-130：草稿记录生成时的人设版本）。"""
    from ..services.persona_profile import current_persona_version

    return current_persona_version(db, current_creator_id(db))


class GenerateIn(BaseModel):
    topic: str
    query_source: str = ""


class ReworkIn(BaseModel):
    angle_id: str = ""


class FeedbackIn(BaseModel):
    liked: bool | None = None
    rating: int | None = Field(default=None, ge=1, le=5)
    comment: str = ""
    hook_score: int | None = Field(default=None, ge=1, le=5)
    pace_score: int | None = Field(default=None, ge=1, le=5)
    ending_score: int | None = Field(default=None, ge=1, le=5)
    style_score: int | None = Field(default=None, ge=1, le=5)


@router.post("/generate-async", response_model=dict)
def generate_async(payload: GenerateIn, db: Session = Depends(get_db)):
    """普通生成统一入口：返回草稿、后台任务和本次生成运行 ID。"""
    topic = (payload.topic or "").strip()
    if not topic:
        raise HTTPException(status_code=400, detail="选题不能为空")
    try:
        task_id, draft_id, run_id = draft_flow.start_generation(
            db, topic, query_source=(payload.query_source or "").strip()
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"task_id": task_id, "draft_id": draft_id, "run_id": run_id}


@router.post("/{draft_id}/suggest-meta", response_model=dict)
def suggest_meta(draft_id: int, db: Session = Depends(get_db)):
    """基于脚本正文 + 人设生成标题/封面字/素材标签候选（R-224）。"""
    from ..services.creator_service import current_creator_id

    draft = db.get(Draft, draft_id)
    if draft is None:
        raise HTTPException(status_code=404, detail="草稿不存在")
    if draft.creator_id != current_creator_id(db):
        raise HTTPException(status_code=403, detail="无权访问该草稿")
    tid = find_running_task("draft_suggest_meta", {"draft_id": draft_id})
    if tid:
        return {"task_id": tid}
    task_id = start_task("draft_suggest_meta", {"draft_id": draft_id}, suggest_meta_task)
    return {"task_id": task_id}


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
def draft_rework(draft_id: int, payload: ReworkIn | None = None, db: Session = Depends(get_db)):
    """按原选题重跑，或从最近运行的备选角度重建；覆盖前先保存版本。"""
    draft = db.get(Draft, draft_id)
    if draft is None:
        raise HTTPException(status_code=404, detail="草稿不存在")
    if draft.creator_id != current_creator_id(db):
        raise HTTPException(status_code=403, detail="无权访问该草稿")
    running_id = find_running_task("generate_draft", {"draft_id": draft_id})
    if running_id:
        latest = db.query(GenerationRun).filter(GenerationRun.draft_id == draft_id).order_by(GenerationRun.id.desc()).first()
        raise HTTPException(
            status_code=409,
            detail={"message": "这篇草稿正在生成", "task_id": running_id, "run_id": latest.id if latest else None},
        )
    try:
        task_id, run_id = draft_flow.start_rework(db, draft_id, (payload.angle_id if payload else "").strip())
    except LookupError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"task_id": task_id, "run_id": run_id, "message": "已提交重新生成"}


@router.get("/{draft_id}/generation-runs/latest", response_model=dict)
def latest_generation_run(draft_id: int, db: Session = Depends(get_db)):
    draft = db.get(Draft, draft_id)
    if draft is None:
        raise HTTPException(status_code=404, detail="草稿不存在")
    if draft.creator_id != current_creator_id(db):
        raise HTTPException(status_code=403, detail="无权访问该草稿")
    run = (
        db.query(GenerationRun)
        .filter(GenerationRun.draft_id == draft_id)
        .order_by(GenerationRun.id.desc())
        .first()
    )
    if run is None:
        raise HTTPException(status_code=404, detail="暂无创作过程")
    return generation_run_payload(run)


@router.post("/{draft_id}/discuss", response_model=dict)
def draft_discuss(draft_id: int, db: Session = Depends(get_db)):
    """仅为洗稿和历史原文讨论保留；新普通生成使用重新生成。"""
    draft = db.get(Draft, draft_id)
    if draft is None:
        raise HTTPException(status_code=404, detail="草稿不存在")
    latest = (
        db.query(GenerationRun)
        .filter(GenerationRun.draft_id == draft_id, GenerationRun.status != "legacy")
        .order_by(GenerationRun.id.desc())
        .first()
    )
    if latest is not None:
        raise HTTPException(status_code=409, detail="新普通生成请使用「重新生成」，不再进入旧讨论链路")
    try:
        task_id = draft_flow.start_discussion(db, draft_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"task_id": task_id, "message": "已提交讨论，完成后右上角通知"}


@router.get("/{draft_id}/debate-status", response_model=dict)
def debate_status(draft_id: int, db: Session = Depends(get_db)):
    """当前双模型讨论进行到哪一步（思考中提示）。

    R-173：除原有的 `status`（人类可读文案，老前端只读它做展示，语义保持不变）外，
    新增结构化字段 `state`（`running`/`failed`/`null`）+ `note/actor/phase/round/rounds/kind`，
    新前端据此画「模型名 + 三点跳动 + 第 x/y 轮」并在 `state != running` 时收尾。
    """
    state = draft_status.read(db, draft_id) or {}
    return {
        "status": state.get("note") or None,  # 兼容老前端：无任务时 null
        "state": state.get("state"),
        "kind": state.get("kind") or "",
        "note": state.get("note") or "",
        "actor": state.get("actor") or "",
        "phase": state.get("phase") or "",
        "round": state.get("round"),
        "rounds": state.get("rounds"),
    }


@router.get("/{draft_id}/discussions", response_model=list[dict])
def list_discussions(draft_id: int, db: Session = Depends(get_db)):
    """脚本讨论留痕（R-023）：按轮次返回聊天式消息。

    R-178：每条附**实际出结果**的模型（`used_slot/vendor/model_id` + 服务端算好的 `model_label`，
    如 `DeepSeek · deepseek-flash`）；历史行没记过模型 → `model_label` 为空，前端显示「未记录模型（历史）」。
    `kind='run'` 是某一次讨论的运行头（content 为 JSON：当时配置的生成方/评审方 + 轮次 + 是否降级）。
    """
    from ..models.discussion import DraftDiscussion
    from ..services.discussion_service import model_label

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
            "used_slot": r.used_slot or "",
            "vendor": r.vendor or "",
            "model_id": r.model_id or "",
            "model_label": model_label(r.vendor or "", r.model_id or ""),
            "created_at": r.created_at.isoformat(),
        }
        for r in rows
    ]


@router.post("/{draft_id}/feedback", response_model=dict)
def feedback(draft_id: int, payload: FeedbackIn, db: Session = Depends(get_db)):
    draft = db.get(Draft, draft_id)
    if draft is None:
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
    if not pure_manual_map(db, [draft]).get(draft.id, False):
        from ..services.generation_feedback import generation_feedback_task

        start_task(
            "generation_feedback",
            {"draft_id": draft.id, "comment": payload.comment or ""},
            generation_feedback_task,
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
    include_deleted: bool = False,
    db: Session = Depends(get_db),
):
    """草稿列表。R-243：默认排除逻辑删除（status='deleted'）——工作台不展示，
    旧行为下它们占响应约 79% 字节；需要排查时传 include_deleted=true 或 status=deleted。"""
    q = db.query(Draft)
    cid = current_creator_id(db)
    if cid:
        q = q.filter(Draft.creator_id == cid)
    if status:
        q = q.filter(Draft.status == status)
    elif not include_deleted:
        q = q.filter(Draft.status != "deleted")
    if video_id is not None:
        q = q.filter(Draft.video_id == video_id)
    rows = q.order_by(Draft.updated_at.desc()).limit(limit).all()
    # R-173：一次批量查询带上「AI 长任务状态」，卡片据此显示讨论中动画（无 N+1）
    states = draft_status.read_many(db, [r.id for r in rows])
    # R-210：批量判定「纯手写」；R-211：批量带最新评价文本（卡片记反馈预填）
    pm = pure_manual_map(db, rows)
    comments = latest_comment_map(db, [r.id for r in rows])
    out = []
    for r in rows:
        item = DraftOut.model_validate(r)
        item.debate = states.get(r.id)
        item.pure_manual = pm.get(r.id, False)
        item.feedback_comment = comments.get(r.id, "")
        out.append(item)
    return out


@router.post("", response_model=DraftOut)
def create_draft(payload: DraftCreate, db: Session = Depends(get_db)):
    data = payload.model_dump()
    # R-154：空白草稿不落库（前端保存前已拦截，这里兜底其它调用方）
    if not (
        (data.get("title") or "").strip()
        or (data.get("cover_text") or "").strip()
        or (data.get("script") or "").strip()
        or data.get("tags")
        or data.get("video_id")
    ):
        raise HTTPException(status_code=400, detail="草稿内容为空，未创建")
    data["platform_shells"] = json.dumps(data.get("platform_shells") or {}, ensure_ascii=False)
    data["tags"] = json.dumps(data.get("tags") or [], ensure_ascii=False)  # R-154：新建也可带标签
    data["creator_id"] = current_creator_id(db)
    draft = Draft(**data)
    db.add(draft)
    db.commit()
    db.refresh(draft)
    return draft


@router.get("/publish-links/preview", response_model=dict)
def publish_links_preview(db: Session = Depends(get_db)):
    """R-197：列出「已发布草稿 ↔ 作品」的高置信度自动关联候选。"""
    from ..services.publish_backfill import preview

    return preview(db)


@router.post("/publish-links/apply", response_model=dict)
def publish_links_apply(db: Session = Depends(get_db)):
    """R-197：应用自动关联并回填历史表现（可撤销）。R-202：改为后台任务，返回 task_id。"""
    tid = find_running_task("publish_backfill")
    if tid:
        return {"task_id": tid}
    from ..services.publish_backfill import apply_task

    return {"task_id": start_task("publish_backfill", {}, apply_task)}


@router.post("/publish-links/revert", response_model=dict)
def publish_links_revert(db: Session = Depends(get_db)):
    """R-197：撤销上一次自动关联。"""
    from ..services.publish_backfill import revert

    return revert(db)


@router.get("/publish-candidates", response_model=dict)
def publish_candidates(query: str = "", limit: int = 20, db: Session = Depends(get_db)):
    """R-267：绑定作品选择器——当前主博主账号下按标题搜索的作品。"""
    from ..services import draft_publish

    try:
        items = draft_publish.candidates(db, query=query, limit=limit)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"items": items}


@router.post("/{draft_id}/publish", response_model=dict)
def publish_draft(draft_id: int, payload: DraftPublishIn, db: Session = Depends(get_db)):
    """R-267：绑定作品（+ 可选本地视频）并立即回填发布效果。"""
    from ..services import draft_publish

    draft = db.get(Draft, draft_id)
    if draft is None:
        raise HTTPException(status_code=404, detail="草稿不存在")
    try:
        performance = draft_publish.bind(
            db, draft, post_id=payload.post_id, video_id=payload.video_id, publish_url=payload.publish_url
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"draft_id": draft.id, "post_id": draft.post_id, "performance": performance}


@router.delete("/{draft_id}/publish", response_model=dict)
def unpublish_draft(draft_id: int, db: Session = Depends(get_db)):
    """R-267：解除绑定（幂等）。"""
    from ..services import draft_publish

    draft = db.get(Draft, draft_id)
    if draft is None:
        raise HTTPException(status_code=404, detail="草稿不存在")
    draft_publish.unbind(db, draft)
    return {"draft_id": draft.id, "unbound": True}


@router.get("/{draft_id}/publish", response_model=dict)
def get_publish(draft_id: int, refresh: bool = False, db: Session = Depends(get_db)):
    """R-267：绑定信息 + 发布效果（refresh=true 忽略 6h 缓存）。"""
    from ..services import draft_publish

    draft = db.get(Draft, draft_id)
    if draft is None:
        raise HTTPException(status_code=404, detail="草稿不存在")
    if not draft.post_id:
        return {"draft_id": draft.id, "post_id": None, "performance": None}
    performance = draft_publish.refresh(db, draft, force=refresh)
    return {"draft_id": draft.id, "post_id": draft.post_id, "performance": performance}


@router.get("/{draft_id}", response_model=DraftOut)
def get_draft(draft_id: int, db: Session = Depends(get_db)):
    draft = db.get(Draft, draft_id)
    if draft is None:
        raise HTTPException(status_code=404, detail="草稿不存在")
    item = DraftOut.model_validate(draft)
    item.debate = draft_status.read(db, draft_id)  # R-173：抽屉刷新正文时也能拿到状态
    item.pure_manual = pure_manual_map(db, [draft]).get(draft.id, False)  # R-210
    item.feedback_comment = latest_comment_map(db, [draft.id]).get(draft.id, "")  # R-211
    return item


@router.patch("/{draft_id}", response_model=DraftOut)
def update_draft(draft_id: int, payload: DraftUpdate, db: Session = Depends(get_db)):
    draft = db.get(Draft, draft_id)
    if draft is None:
        raise HTTPException(status_code=404, detail="草稿不存在")
    data = payload.model_dump(exclude_unset=True)
    if "platform_shells" in data:
        data["platform_shells"] = json.dumps(data["platform_shells"] or {}, ensure_ascii=False)
    if "tags" in data:
        data["tags"] = json.dumps(data["tags"] or [], ensure_ascii=False)
    for field, value in data.items():
        setattr(draft, field, value)
    db.commit()
    db.refresh(draft)
    # 改稿差异分析（异步，学习作者的改写偏好；R-156 起按版本链分析，R-209 起按 source 归因）
    if draft.original_script and draft.script and draft.script != draft.original_script:
        start_task("diff_analysis", {"draft_id": draft.id}, diff_task)
    # R-211：状态流转 = 反馈信号——进 done/archived 触发「为什么好/差」学习分析（异步，不阻塞）
    new_status = data.get("status")
    if new_status in ("done", "archived"):
        from ..services import feedback_analysis

        feedback_analysis.maybe_trigger(db, draft, str(new_status))
    if new_status in ("done", "archived", "deleted") and not pure_manual_map(db, [draft]).get(draft.id, False):
        from ..services.generation_feedback import generation_feedback_task

        start_task("generation_feedback", {"draft_id": draft.id}, generation_feedback_task)
    return draft


class FinalizeIn(BaseModel):
    title: str = ""
    cover_text: str = ""
    script: str = ""
    tags: list[str] = []
    video_id: int | None = None


@router.get("/{draft_id}/performance", response_model=dict)
def draft_performance(draft_id: int, db: Session = Depends(get_db)):
    """R-184：已发布稿件的表现（绑定素材存在时，返回各平台最新互动聚合）。

    未关联素材 / 无平台数据时返回 platforms=[]，前端提示「先关联素材并同步」。
    """
    draft = db.get(Draft, draft_id)
    if draft is None:
        raise HTTPException(status_code=404, detail="草稿不存在")
    if not draft.video_id:
        return {"draft_id": draft_id, "video_id": None, "platforms": [], "totals": None}
    from ..models.video import Video
    from ..services.metrics import _platform_breakdown

    video = db.get(Video, draft.video_id)
    if video is None:
        return {"draft_id": draft_id, "video_id": draft.video_id, "platforms": [], "totals": None}
    rows = _platform_breakdown(db, video)
    totals = {"plays": 0, "likes": 0, "favorites": 0, "comments": 0}
    for r in rows:
        totals["plays"] += int(r.get("plays") or 0)
        totals["likes"] += int(r.get("likes") or 0)
        totals["favorites"] += int(r.get("favorites") or 0)
        totals["comments"] += int(r.get("comments") or 0)
    return {
        "draft_id": draft_id,
        "video_id": draft.video_id,
        "video_title": video.title or "",
        "platforms": rows,
        "totals": totals,
    }


@router.get("/{draft_id}/versions", response_model=list[dict])
def draft_versions(draft_id: int, db: Session = Depends(get_db)):
    """R-156：草稿的定稿版本留痕（时间正序，含正文供前端本地做两版 diff）。"""
    if db.get(Draft, draft_id) is None:
        raise HTTPException(status_code=404, detail="草稿不存在")
    return [version_payload(v) for v in list_versions(db, draft_id)]


@router.post("/{draft_id}/finalize", response_model=dict)
def draft_finalize(draft_id: int, payload: FinalizeIn, db: Session = Depends(get_db)):
    """R-156：定稿——先保存当前编辑，再记一条版本（正文+标题+封面字+标签），并异步分析版本链偏好。"""
    draft = db.get(Draft, draft_id)
    if draft is None:
        raise HTTPException(status_code=404, detail="草稿不存在")
    if not (
        (payload.title or "").strip()
        or (payload.cover_text or "").strip()
        or (payload.script or "").strip()
        or payload.tags
        or payload.video_id
    ):
        raise HTTPException(status_code=400, detail="草稿内容为空，未定稿")
    draft.title = payload.title
    draft.cover_text = payload.cover_text
    draft.script = payload.script
    draft.tags = json.dumps(payload.tags or [], ensure_ascii=False)
    draft.video_id = payload.video_id
    db.commit()
    db.refresh(draft)
    version = finalize_version(db, draft, source="manual")  # R-157：≥2 版才触发差异分析
    if not pure_manual_map(db, [draft]).get(draft.id, False):
        from ..services.generation_feedback import generation_feedback_task

        start_task("generation_feedback", {"draft_id": draft.id}, generation_feedback_task)
    return {"ok": True, "draft_id": draft.id, "version": version_payload(version)}


@router.post("/{draft_id}/versions/{version_id}/rollback", response_model=dict)
def draft_version_rollback(draft_id: int, version_id: int, db: Session = Depends(get_db)):
    """回滚到此版本——把该版本快照（正文/标题/封面字/标签）覆盖写回当前草稿并保存。

    R-209（推翻 R-157「只覆盖保存、不留痕」）：回退**留一版**（`source="rollback"`），
    版本链终点反映真实内容——否则差异分析/改稿样本会把 AI 讨论的产出错当「作者定稿」。
    若回退跨过了 AI 侧版本（= 否定了 AI 的产出），同时把最近讨论运行头回填 `reverted: true`。
    """
    draft = db.get(Draft, draft_id)
    if draft is None:
        raise HTTPException(status_code=404, detail="草稿不存在")
    ver = db.get(DraftVersion, version_id)
    if ver is None or ver.draft_id != draft_id:
        raise HTTPException(status_code=404, detail="版本不存在")
    # 回退前版本链的最新一版：若是 AI 侧且比目标版新，说明作者否掉了 AI 的产出
    prior = list_versions(db, draft_id)
    crossed_ai = bool(
        prior and prior[-1].id > ver.id and (prior[-1].source or "") in AI_SOURCES
    )
    draft.title = ver.title or ""
    draft.cover_text = ver.cover_text or ""
    draft.script = ver.script or ""
    draft.tags = ver.tags or "[]"
    db.commit()
    db.refresh(draft)
    new_ver = finalize_version(db, draft, source="rollback", note=f"回退到版本 #{ver.id}")
    if crossed_ai:
        from ..services.discussion_service import mark_latest_run_reverted

        mark_latest_run_reverted(db, draft_id)
        from ..services.generation_feedback import mark_assets_feedback

        mark_assets_feedback(db, draft, "reverted")
    return {"ok": True, "draft_id": draft.id, "rolled_back_to": ver.id, "version": version_payload(new_ver)}
