"""脚本草稿接口：工作台创建/改写/保存 + 反馈 + 生成。"""

from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..db import get_db
from ..services import draft_status
from ..services.creator_service import current_creator_id
from ..models.draft import Draft
from ..models.draft_version import DraftVersion
from ..schemas.draft import DraftCreate, DraftOut, DraftUpdate
from ..services import draft_flow
from ..services.draft_versions import finalize_version, list_versions, version_payload
from ..services.diff_analysis import diff_task
from ..services.feedback import add_feedback
from ..services.generation import generate_draft
from ..services.persona import PersonaService
from ..tasks import start_task

router = APIRouter()


def _persona_version(db: Session) -> int:
    """当前人设档案版本（R-130：草稿记录生成时的人设版本）。"""
    from ..services.persona_profile import current_persona_version

    return current_persona_version(db, current_creator_id(db))


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


def _rework_task(db: Session, payload: dict) -> dict:
    """一键回炉（R-030⑦）：按原选题重新生成，并把内容替换回原草稿（保留 id/反馈/讨论记录）。

    R-157：中间 fresh 稿不留版，回炉结果记到**原稿**上。
    R-173：回炉期间在**原稿**上写 AI 状态（卡片显示「正在回炉重写…」），失败留中断标记。
    """
    from .generation import generate_draft
    from ..services.draft_versions import finalize_version

    draft_id = int(payload.get("draft_id") or 0)
    draft = db.get(Draft, draft_id)
    if draft is None:
        return {"draft_id": 0}
    topic = (payload.get("topic") or draft.title or "").strip() or "重新生成一条口播脚本"
    draft_status.set_running(db, draft_id, "正在回炉重写…", kind="rework")
    try:
        fresh = generate_draft(db, topic, snapshot=False)
    except Exception as exc:  # noqa: BLE001 R-173：留中断标记后原样抛出
        try:
            draft_status.set_failed(db, draft_id, f"回炉中断：{str(exc)[:150]}", kind="rework")
        except Exception:  # noqa: BLE001
            db.rollback()
        raise
    draft = db.get(Draft, draft_id) or draft
    draft.title = fresh.title or draft.title
    draft.cover_text = fresh.cover_text or draft.cover_text
    draft.script = fresh.script or draft.script
    draft.platform_shells = fresh.platform_shells or draft.platform_shells
    draft.original_script = fresh.original_script or draft.original_script
    draft.source = "ai"
    db.delete(fresh)
    db.commit()
    finalize_version(db, draft, source="ai_generate", note="一键回炉")
    draft_status.clear(db, draft_id)
    return {"draft_id": draft.id, "title": draft.title}


@router.post("/generate", response_model=DraftOut)
def generate(payload: GenerateIn, db: Session = Depends(get_db)):
    """根据选题生成三件套（标题/封面字/脚本）+ 平台外壳。"""
    return generate_draft(db, payload.topic)


# R-147：讨论任务体与占位稿创建抽到 services/draft_flow，供「AI 生成」按钮与 AI 对话的
# agent 写操作共用（原来只写在 API 层，别处复用不了）。
_debate_task = draft_flow.debate_task


@router.post("/generate-async", response_model=dict)
def generate_async(payload: GenerateIn, db: Session = Depends(get_db)):
    """双模型讨论生成（R-023）：先建占位草稿，后台 初稿→5轮讨论→定稿；完成后通知跳转草稿。"""
    topic = (payload.topic or "").strip()
    if not topic:
        raise HTTPException(status_code=400, detail="选题不能为空")
    task_id, draft_id = draft_flow.start_generation(db, topic)
    return {"task_id": task_id, "draft_id": draft_id}


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
        data = persona.call_json(
            "ideas",
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



@router.post("/{draft_id}/discuss", response_model=dict)
def draft_discuss(draft_id: int, db: Session = Depends(get_db)):
    """R-155：基于原文（洗稿稿＝洗稿素材 ASR 文案 / 自建稿＝正文）跑双模型多轮讨论。

    完成后更新 正文+标题+封面字+标签（标签合并去重）并写回 original_script 供【原文对照】；
    讨论留痕追加、不清空旧记录。
    """
    if db.get(Draft, draft_id) is None:
        raise HTTPException(status_code=404, detail="草稿不存在")
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
    from ..services.debate import model_label

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
    rows = q.order_by(Draft.updated_at.desc()).limit(limit).all()
    # R-173：一次批量查询带上「AI 长任务状态」，卡片据此显示讨论中动画（无 N+1）
    states = draft_status.read_many(db, [r.id for r in rows])
    out = []
    for r in rows:
        item = DraftOut.model_validate(r)
        item.debate = states.get(r.id)
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


@router.get("/{draft_id}", response_model=DraftOut)
def get_draft(draft_id: int, db: Session = Depends(get_db)):
    draft = db.get(Draft, draft_id)
    if draft is None:
        raise HTTPException(status_code=404, detail="草稿不存在")
    item = DraftOut.model_validate(draft)
    item.debate = draft_status.read(db, draft_id)  # R-173：抽屉刷新正文时也能拿到状态
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
    # 改稿差异分析（异步，学习作者的改写偏好；R-156 起按版本链分析）
    if draft.original_script and draft.script and draft.script != draft.original_script:
        start_task("diff_analysis", {"draft_id": draft.id}, diff_task)
    return draft


class FinalizeIn(BaseModel):
    title: str = ""
    cover_text: str = ""
    script: str = ""
    tags: list[str] = []
    video_id: int | None = None


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
    return {"ok": True, "draft_id": draft.id, "version": version_payload(version)}


@router.post("/{draft_id}/versions/{version_id}/rollback", response_model=dict)
def draft_version_rollback(draft_id: int, version_id: int, db: Session = Depends(get_db)):
    """R-157：回滚到此版本——把该版本快照（正文/标题/封面字/标签）覆盖写回当前草稿并保存。

    按作者口径：**只覆盖保存**，不额外留痕、不改草稿状态。
    """
    draft = db.get(Draft, draft_id)
    if draft is None:
        raise HTTPException(status_code=404, detail="草稿不存在")
    ver = db.get(DraftVersion, version_id)
    if ver is None or ver.draft_id != draft_id:
        raise HTTPException(status_code=404, detail="版本不存在")
    draft.title = ver.title or ""
    draft.cover_text = ver.cover_text or ""
    draft.script = ver.script or ""
    draft.tags = ver.tags or "[]"
    db.commit()
    db.refresh(draft)
    return {"ok": True, "draft_id": draft.id, "rolled_back_to": ver.id}
