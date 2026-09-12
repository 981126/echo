"""改稿差异分析：作者把 AI 原稿改成了什么 → 提炼风格偏好（人设建议）。"""

from __future__ import annotations

from sqlalchemy.orm import Session

from ..core.diff import has_meaningful_change
from ..models.persona import PersonaTag
from . import llm_router
from .llm import LLMError
from .prompt_service import get_prompt

DIFF_SYSTEM = (
    "你是人设学习专家。对比作者对 AI 脚本的改写，提炼作者真实的风格偏好。"
    "只输出 JSON："
    '{"suggestions":[{"label":"简短标签(2-6字)","description":"具体偏好描述","reason":"依据哪处改写"}]}'
    "若看不出明显偏好，返回空数组。"
)


def analyze_diff(original: str, edited: str, llm=None, db: Session | None = None) -> list[dict]:
    if not has_meaningful_change(original, edited):
        return []
    llm = llm or llm_router.primary_llm(db, "diff")  # R-139：模型1 主用，失败降级模型2
    user = f"AI 原稿：\n{original}\n\n作者改后：\n{edited}"
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
    """将改稿差异建议写入人设（suggested，待作者确认）。返回新增条数。"""
    if not draft.original_script or not draft.script:
        return 0
    suggestions = analyze_diff(draft.original_script, draft.script, db=db)
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
