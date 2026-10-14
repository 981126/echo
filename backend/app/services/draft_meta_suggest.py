"""草稿元信息生成：基于正文 + 人设生成标题/封面字/素材标签候选。"""

from __future__ import annotations

from sqlalchemy.orm import Session

from ..models.draft import Draft
from ..models.persona import PersonaTag
from ..services import llm_router
from ..services.llm import LLMError

SUGGEST_META_SYSTEM = (
    "你是短视频包装专家。请根据下面的脚本正文和作者人设，生成 5 条视频标题、"
    "5 条封面字、5 条素材标签。\n"
    "要求：\n"
    "1. 标题要吸睛、有爆款感，能制造好奇、冲突、利益或情绪，但不过度标题党。\n"
    "2. 封面字 3-8 字，口语化、有视觉冲击，适合直接压在视频封面上。\n"
    "3. 素材标签覆盖场景、情绪、卖点、人群等维度，每条 2-6 字。\n"
    "4. 参考作者人设，但要比人设本身更抢眼、更有传播性。\n"
    "只输出 JSON，不要解释：\n"
    '{"titles":["标题1",...],"cover_texts":["封面字1",...],"tags":["标签1",...]}'
)

MOCK_TITLES = [
    "这件事，90% 的人都想错了",
    "看完这条，你会后悔没早点知道",
    "我用了 3 年才明白的真相",
    "别急着划走，最后一句很关键",
    "为什么聪明人反而越容易踩这个坑",
]

MOCK_COVERS = ["真相来了", "别错过", "终于懂了", "人间清醒", "万万没想到"]

MOCK_TAGS = ["干货", "认知", "避坑", "成长", "职场"]


def _creator_filter(db: Session):
    """归属过滤：存在当前主博主时只学习该博主数据（多主博主隔离，D-028）。"""
    from ..services.creator_service import get_current_creator

    creator = get_current_creator(db)
    return creator.id if creator else None


def _persona_lines(db: Session) -> list[str]:
    from ..services.persona import LAYER_LABELS, LAYERS

    q = db.query(PersonaTag).filter(PersonaTag.status == "confirmed")
    cid = _creator_filter(db)
    if cid:
        q = q.filter(PersonaTag.creator_id == cid)
    tags = q.order_by(PersonaTag.category, PersonaTag.id).all()

    def _fmt(t: PersonaTag) -> str:
        dim = (getattr(t, "dimension", "") or "").strip()
        layer = (getattr(t, "layer", "") or "").strip()
        prefix = f"[{LAYER_LABELS[layer]}] " if layer in LAYER_LABELS else (f"[{dim}] " if dim else "")
        return f"{prefix}{t.label}: {t.description}"

    style_tags = [t for t in tags if t.category not in ("redline", "phrase")]
    layer_order = {name: i for i, name in enumerate(LAYERS)}
    style_tags.sort(key=lambda t: layer_order.get(getattr(t, "layer", "") or "", 9))
    return [_fmt(t) for t in style_tags]


def _clean_strings(items: list[object], max_len: int = 80) -> list[str]:
    out: list[str] = []
    for x in items:
        s = str(x).strip()
        if s:
            out.append(s[:max_len])
    return out


def _parse_result(raw: object) -> dict:
    data = raw if isinstance(raw, dict) else {}
    return {
        "titles": _clean_strings(data.get("titles") or [], max_len=120),
        "cover_texts": _clean_strings(data.get("cover_texts") or [], max_len=20),
        "tags": _clean_strings(data.get("tags") or [], max_len=20),
    }


def suggest_meta_task(db: Session, payload: dict) -> dict:
    """后台任务函数：生成标题/封面字/标签候选。"""
    draft_id = int(payload.get("draft_id") or 0)
    draft = db.get(Draft, draft_id)
    if draft is None:
        return {"titles": [], "cover_texts": [], "tags": []}

    script = (draft.script or "").strip()
    if not script:
        return {"titles": [], "cover_texts": [], "tags": []}

    parts = [f"脚本正文：\n{script}"]
    persona = _persona_lines(db)
    if persona:
        parts.append("作者人设（参考，但请输出更吸睛爆款的结果）：\n" + "\n".join(f"- {p}" for p in persona))

    messages = [
        {"role": "system", "content": SUGGEST_META_SYSTEM},
        {"role": "user", "content": "\n\n".join(parts)},
    ]

    try:
        llm = llm_router.primary_llm(db, "draft_meta")
        data = llm.chat_json(
            messages,
            temperature=0.8,
            max_tokens=2000,
            require=("titles", "cover_texts", "tags"),
        )
        result = _parse_result(data)
        if not (result["titles"] or result["cover_texts"] or result["tags"]):
            raise LLMError("模型返回空候选")
        return result
    except LLMError:
        return {
            "titles": list(MOCK_TITLES),
            "cover_texts": list(MOCK_COVERS),
            "tags": list(MOCK_TAGS),
        }


__all__ = ["suggest_meta_task"]
