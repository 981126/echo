"""改稿差异分析：作者把 AI 原稿/初稿改成了什么 → 提炼风格偏好（人设建议）。

R-156：从「原文 → 当前稿」两段升级为**版本链**（初稿 → … → 定稿），
让 AI 看出逐版改了哪些地方；没有版本时退回原来的两段行为。
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from ..core.diff import has_meaningful_change
from ..models.persona import PersonaTag
from . import llm_router
from .llm import LLMError
from .prompt_service import get_prompt

DIFF_SYSTEM = (
    "你是人设学习专家。下面给出作者同一篇稿子从初稿到定稿的逐版修改（按时间顺序）。"
    "请对比各版之间的变化，提炼作者真实的风格偏好：他反复在改什么、往哪个方向改"
    "（更口语？更短？加钩子？删套话？）。只输出 JSON："
    '{"suggestions":[{"label":"简短标签(2-6字)","description":"具体偏好描述","reason":"依据哪一版的哪处修改"}]}'
    "若看不出明显偏好，返回空数组。"
)


def normalize_stages(stages: list[str]) -> list[str]:
    """去掉空白段与相邻重复（多次定稿但正文没变）。"""
    uniq: list[str] = []
    for raw in stages or []:
        text = (raw or "").strip()
        if text and (not uniq or text != uniq[-1]):
            uniq.append(text)
    return uniq


def analyze_diff(stages: list[str], llm=None, db: Session | None = None) -> list[dict]:
    """stages：按时间正序的稿子（≥2 段，含中间版本）。返回待确认的人设建议。"""
    uniq = normalize_stages(stages)
    if len(uniq) < 2:
        return []
    if not any(has_meaningful_change(a, b) for a, b in zip(uniq, uniq[1:])):
        return []
    llm = llm or llm_router.primary_llm(db, "diff")  # R-139：模型1 主用，失败降级模型2
    blocks: list[str] = []
    for i, text in enumerate(uniq):
        label = "初稿" if i == 0 else ("定稿" if i == len(uniq) - 1 else f"第 {i + 1} 稿")
        blocks.append(f"【{label}】\n{text[:2200]}")
    user = "作者对同一篇稿子的逐版修改（按时间顺序）：\n\n" + "\n\n".join(blocks)
    try:
        data = llm.chat_json(
            [
                {"role": "system", "content": get_prompt("diff")},
                {"role": "user", "content": user},
            ],
            temperature=0.3,
        )
    except LLMError:
        return []
    suggestions = []
    for item in data.get("suggestions") or []:
        label = str(item.get("label", "")).strip() if isinstance(item, dict) else ""
        if label:
            suggestions.append(
                {
                    "label": label,
                    "description": str(item.get("description", "")).strip(),
                    "reason": str(item.get("reason", "")).strip(),
                }
            )
    return suggestions


def apply_diff_suggestions(db: Session, draft) -> int:
    """按版本链提炼偏好并写入人设（suggested，待作者确认）。返回新增条数。"""
    from .draft_versions import version_stages

    stages = version_stages(db, draft)
    if len(stages) < 2:
        return 0
    suggestions = analyze_diff(stages, db=db)
    if not suggestions:
        return 0
    current_version = 1
    latest = db.query(PersonaTag).order_by(PersonaTag.version.desc()).first()
    if latest:
        current_version = latest.version
    added = 0
    for s in suggestions:
        dup = (
            db.query(PersonaTag)
            .filter(PersonaTag.label == s["label"], PersonaTag.status.in_(["suggested", "confirmed"]))
            .first()
        )
        if dup:
            continue
        description = s["description"]
        if s.get("reason"):
            description = f"{description}（依据：{s['reason']}）"
        db.add(
            PersonaTag(
                label=s["label"],
                description=description,
                category="style",
                source="ai",
                status="suggested",
                version=current_version,
            )
        )
        added += 1
    if added:
        db.commit()
    return added


def diff_task(db: Session, payload: dict) -> int:
    """后台任务体（R-156）：按版本链分析改稿偏好；草稿不存在返回 0。"""
    from ..models.draft import Draft

    draft = db.get(Draft, int(payload.get("draft_id") or 0))
    if draft is None:
        return 0
    return apply_diff_suggestions(db, draft)

