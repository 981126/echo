"""改稿差异分析：作者把 AI 原稿/初稿改成了什么 → 提炼风格偏好（人设建议）。

R-156：从「原文 → 当前稿」两段升级为**版本链**（初稿 → … → 定稿），
让 AI 看出逐版改了哪些地方；没有版本时退回原来的两段行为。

R-209：版本链必须按 ``source`` 归因——AI 侧版本之间的改动**不是作者改的**，
只有「AI 版 → 其后的作者侧版本（manual/rollback）」才是作者的真实修改；
作者回退 AI 版 = 否定该方向。终版不是作者侧（作者还没定稿）时不分析。

R-210：链中没有任何 AI 侧版本（纯手写稿自己改自己）时不分析——手写稿只学正文。
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from ..core.diff import has_meaningful_change
from ..models.persona import PersonaTag
from . import llm_router
from .draft_versions import AI_SOURCES, AUTHOR_SOURCES
from .llm import LLMError
from .prompt_service import get_prompt

DIFF_SYSTEM = (
    "你是人设学习专家。下面给出作者同一篇稿子从初稿到定稿的逐版修改（按时间顺序，每版标注了出自谁手）。"
    "请对比各版之间的变化，提炼作者真实的风格偏好：他反复在改什么、往哪个方向改"
    "（更口语？更短？加钩子？删套话？）。只输出 JSON："
    '{"suggestions":[{"label":"简短标签(2-6字)","description":"具体偏好描述","reason":"依据哪一版的哪处修改"}]}'
    "若看不出明显偏好，返回空数组。"
)

# R-209：随 user 消息一起给的归因规则（不依赖 DB 提示词版本，保证任何情况下都生效）
ATTRIBUTION_RULES = (
    "归因规则（必须遵守）：标注【AI 稿】的版本由 AI 生成，AI 版本之间的差异**不是作者改的**，"
    "不能当作作者偏好；只有「AI 稿 → 其后的作者版本」之间的变化才是作者的真实修改；"
    "标注【作者回退】表示作者放弃了之前的版本、恢复了旧版——被回退掉的方向就是作者否定的方向。"
)

# 版本 source → 展示标签
_SOURCE_LABELS = {
    "manual": "作者定稿",
    "rollback": "作者回退（恢复旧版）",
    "ai_generate": "AI 稿",
    "ai_discuss": "AI 稿",
    "ai_rewrite": "AI 稿",
}


def normalize_stages(stages: list[str]) -> list[str]:
    """去掉空白段与相邻重复（多次定稿但正文没变）。"""
    uniq: list[str] = []
    for raw in stages or []:
        text = (raw or "").strip()
        if text and (not uniq or text != uniq[-1]):
            uniq.append(text)
    return uniq


def _normalize_sourced(stages: list[tuple[str, str]]) -> list[tuple[str, str]]:
    """带 source 的相邻去重（与 normalize_stages 同口径，保留来源标签）。"""
    uniq: list[tuple[str, str]] = []
    for source, raw in stages or []:
        text = (raw or "").strip()
        if text and (not uniq or text != uniq[-1][1]):
            uniq.append((source, text))
    return uniq


def analyzable(stages: list[tuple[str, str]]) -> bool:
    """R-209/R-210：这条版本链值不值得分析。

    - 终版必须是作者侧（作者已定稿/已回退），否则学到的是 AI 的改动而不是作者的偏好；
    - 链中必须有 AI 侧版本，否则是纯手写稿自改（R-210：手写稿只学正文）。
    """
    uniq = _normalize_sourced(stages)
    if len(uniq) < 2:
        return False
    if uniq[-1][0] not in AUTHOR_SOURCES:
        return False
    return any(source in AI_SOURCES for source, _t in uniq)


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
    return _parse_suggestions(data)


def analyze_sourced_diff(stages: list[tuple[str, str]], db: Session | None = None) -> list[dict]:
    """R-209：带 source 归因的差异分析（blocks 标注每版出自谁手 + 归因规则）。"""
    uniq = _normalize_sourced(stages)
    if len(uniq) < 2:
        return []
    if not any(has_meaningful_change(a, b) for a, b in zip([t for _s, t in uniq], [t for _s, t in uniq][1:])):
        return []
    llm = llm_router.primary_llm(db, "diff")  # R-139：模型1 主用，失败降级模型2
    blocks: list[str] = []
    for i, (source, text) in enumerate(uniq):
        who = _SOURCE_LABELS.get(source, source)
        pos = "（首版）" if i == 0 else ("（当前版）" if i == len(uniq) - 1 else "")
        blocks.append(f"【{who}{pos}】\n{text[:2200]}")
    user = (
        "同一篇稿子的逐版演进（按时间顺序，每版标注了出自谁手）：\n\n"
        + "\n\n".join(blocks)
        + "\n\n"
        + ATTRIBUTION_RULES
    )
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
    return _parse_suggestions(data)


def _parse_suggestions(data: dict) -> list[dict]:
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
    """按版本链提炼偏好并写入人设（suggested，待作者确认）。返回新增条数。

    R-209/R-210：链不可分析（终版非作者侧 / 无 AI 侧版本）时直接返回 0。
    """
    from .draft_versions import chains_with_sources

    stages = chains_with_sources(db, [draft]).get(draft.id, [])
    if not stages:
        # 兼容 R-117/R-131 的老 AI 稿（无版本留痕）：original_script=AI 原稿 → 当前稿=作者改后。
        # 仅 source="ai" 的稿可这样归因（手写稿的 original_script 语义不同，R-210 不学）。
        original = (getattr(draft, "original_script", "") or "").strip()
        current = (getattr(draft, "script", "") or "").strip()
        if getattr(draft, "source", "") == "ai" and original and current and original != current:
            stages = [("ai_generate", original), ("manual", current)]
    if not analyzable(stages):
        return 0
    suggestions = analyze_sourced_diff(stages, db=db)
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


def maybe_start_diff_analysis(db: Session, draft) -> bool:
    """R-157：只有 ≥2 版（有可看的「逐版修改」）才入队分析，首版不空跑。

    R-209/R-210：入队前先做归因检查（终版须作者侧、链中须有 AI 侧版本），不空跑。
    """
    from ..tasks import start_task
    from .draft_versions import chains_with_sources

    if not analyzable(chains_with_sources(db, [draft]).get(draft.id, [])):
        return False
    start_task("diff_analysis", {"draft_id": draft.id}, diff_task)
    return True
