"""反馈学习分析（R-211）：状态流转触发 LLM 分析「这篇为什么好/差」，心得注入生成上下文。

触发节点（挂在 ``PATCH /api/drafts/{id}`` 状态流转上，不阻塞返回）：
- 进入 ``done``（待制作点完成）→ 结论=好；
- 进入 ``archived``（不采用/移入废稿）→ 结论=差；**纯手写稿豁免**（R-210：
  手写稿被放弃只是作者不想做，不代表稿子写得差，不进负向学习）。

分析输入 = 当前正文 + 带 source 归因的版本链（R-209）+ 作者评价文本（可空）；
输出 2-4 句心得写回 ``feedback.insight``，由 ``prompt_service.feedback_context`` 注入生成上下文。

非实时（R-202）：后台任务 + ``draft_status`` 状态条（卡片显示「学习分析中」，切页/刷新可恢复）；
失败留「中断」标记，不阻塞状态流转。
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from ..core.log import get_logger
from ..models.draft import Draft
from ..models.feedback import Feedback
from . import draft_status, llm_router
from .draft_versions import chains_with_sources, is_pure_manual, latest_comment_map
from .llm import LLMError

log = get_logger("feedback_analysis")

TASK_KIND = "feedback_analysis"

CONCLUSIONS = {
    "done": "好（作者完成了这篇稿，认可它）",
    "archived": "差（作者不采用这篇稿，否定了它）",
}

ANALYSIS_SYSTEM = (
    "你是作者的写作复盘助手。给你一篇稿子的结论（作者认可/否定）、作者的亲笔评价（可能有）、"
    "以及它的逐版演进（每版标注了出自谁手）。请分析**这篇稿子为什么好/差**，聚焦可迁移的经验："
    "选题角度、钩子、结构、语气、详略。输出 2-4 句中文心得，直接说以后要保持/避免什么，"
    "不要复述内容、不要客套。"
)

# 与 diff_analysis 同口径的归因规则（R-209）
_ATTRIBUTION = (
    "归因规则：标注【AI 稿】的版本由 AI 生成，AI 版本之间的差异不是作者改的；"
    "「AI 稿 → 其后的作者版本」之间的变化才是作者的真实修改；"
    "【作者回退】表示作者放弃新版恢复旧版，被回退的方向是作者否定的方向。"
)

_SOURCE_LABELS = {
    "manual": "作者定稿",
    "rollback": "作者回退（恢复旧版）",
    "ai_generate": "AI 稿",
    "ai_discuss": "AI 稿",
    "ai_rewrite": "AI 稿",
}


def _version_blocks(db: Session, draft: Draft) -> str:
    """带 source 标签的版本链（末版重复于当前正文时去掉，正文单独给）。"""
    stages = chains_with_sources(db, [draft]).get(draft.id) or []
    if not stages:
        return ""
    blocks = []
    for source, text in stages:
        who = _SOURCE_LABELS.get(source, source)
        blocks.append(f"【{who}】\n{text[:1500]}")
    return "\n\n".join(blocks)


def analyze(db: Session, draft: Draft, conclusion: str, llm=None) -> str:
    """分析一篇稿为什么好/差，返回心得文本；模型不可用抛 LLMError。"""
    label = CONCLUSIONS.get(conclusion, conclusion)
    comment = latest_comment_map(db, [draft.id]).get(draft.id, "")
    parts = [f"结论：{label}", f"作者亲笔评价：{comment or '（未写）'}"]
    versions = _version_blocks(db, draft)
    if versions:
        parts.append(f"逐版演进（按时间顺序）：\n{versions}")
    parts.append(f"当前正文：\n{(draft.script or '')[:2200]}")
    parts.append(_ATTRIBUTION)
    llm = llm or llm_router.primary_llm(db, TASK_KIND)  # R-139：模型1 主用，失败降级模型2
    text = llm.chat(
        [
            {"role": "system", "content": ANALYSIS_SYSTEM},
            {"role": "user", "content": "\n\n".join(parts)},
        ],
        temperature=0.3,
        max_tokens=600,
    )
    insight = (text or "").strip()
    if not insight:
        raise LLMError("反馈学习分析返回空心得")
    return insight[:800]


def record_insight(db: Session, draft_id: int, conclusion: str, insight: str) -> Feedback:
    """心得写回该稿最新一条 Feedback（没有则新建）；``liked`` 仅存结论快照（不参与学习查询）。"""
    row = (
        db.query(Feedback)
        .filter(Feedback.draft_id == draft_id)
        .order_by(Feedback.id.desc())
        .first()
    )
    if row is None:
        row = Feedback(draft_id=draft_id)
        db.add(row)
    row.insight = insight
    row.liked = conclusion == "done"
    db.commit()
    db.refresh(row)
    return row


def analysis_task(db: Session, payload: dict) -> dict:
    """后台任务体：分析 + 心得落库；失败留「中断」标记（R-173 机制）后抛出。"""
    draft_id = int(payload.get("draft_id") or 0)
    conclusion = str(payload.get("conclusion") or "")
    draft = db.get(Draft, draft_id)
    if draft is None:
        raise ValueError("草稿不存在")
    try:
        insight = analyze(db, draft, conclusion)
    except Exception as exc:  # noqa: BLE001 R-173：失败留标记，不永久转圈
        try:
            draft_status.set_failed(db, draft_id, f"学习分析中断：{str(exc)[:150]}", kind="feedback")
        except Exception:  # noqa: BLE001 标记失败不能掩盖原始错误
            db.rollback()
        raise
    record_insight(db, draft_id, conclusion, insight)
    draft_status.clear(db, draft_id)
    return {"draft_id": draft_id, "conclusion": conclusion, "insight": insight}


def maybe_trigger(db: Session, draft: Draft, new_status: str) -> bool:
    """状态进入 done/archived 时入队分析（纯手写稿进 archived 豁免，R-210）。返回是否入队。"""
    if new_status not in CONCLUSIONS:
        return False
    if new_status == "archived" and is_pure_manual(db, draft):
        return False
    if not (draft.script or "").strip():
        return False
    from ..tasks import find_running_task, start_task

    if find_running_task(TASK_KIND, {"draft_id": draft.id}):
        return False  # 同稿已有分析在跑，不重复烧 LLM（R-202 去重口径）
    draft_status.set_running(db, draft.id, "正在学习这篇稿的反馈…", kind="feedback")
    start_task(TASK_KIND, {"draft_id": draft.id, "conclusion": new_status}, analysis_task)
    return True


__all__ = ["CONCLUSIONS", "TASK_KIND", "analysis_task", "analyze", "maybe_trigger", "record_insight"]
