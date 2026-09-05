"""选题生成服务：DeepSeek 生成三件套（标题/封面字/脚本）+ 平台外壳。

语气一致性：人设档案（标签+红线）+ 风格样本（本地 TF-IDF 检索）。
无密钥时输出确定性 mock 稿，保证开发/测试离线可跑。
"""

from __future__ import annotations

import json
import math
from datetime import date

from sqlalchemy.orm import Session

from ..core.retrieval import TfidfIndex
from ..core.style_profile import build_style_profile, format_style_profile
from .prompt_service import get_prompt
from ..models.draft import Draft
from ..models.metrics import MetricsSnapshot
from ..models.persona import PersonaTag
from ..models.video import Video
from .llm import DeepSeekClient, LLMError

GENERATION_SYSTEM = (
    "你是短视频口播脚本创作专家。严格模仿作者的语气与用词习惯，"
    "结合人设档案与风格样本，围绕给定选题创作。"
    "只输出 JSON："
    '{"title":"视频标题（抓眼球但不过度）","cover_text":"封面字（与标题不同，3-8字，适合压在图上的大字）",'
    '"script":"完整口播脚本（1-2分钟，约200-400字，口语化，有钩子有结尾互动）",'
    '"shells":{"douyin":"抖音发布文案+话题标签","bilibili":"B站简介","xiaohongshu":"小红书笔记正文（含emoji与话题）"}}'
)


def _creator_filter(db: Session):
    """归属过滤：存在当前主博主时只学习该博主数据（多主博主隔离，D-028）。"""
    from .creator_service import get_current_creator

    creator = get_current_creator(db)
    return creator.id if creator else None


def benchmark_context_lines(db: Session) -> str:
    """当前主博主挂的对标博主风格参考（R-030⑤：仅参考，不污染主博主语料）。"""
    from ..models.platform import Creator
    from .creator_service import get_current_creator

    creator = get_current_creator(db)
    if creator is None:
        return ""
    rows = (
        db.query(Creator)
        .filter(Creator.kind == "benchmark", Creator.parent_id == creator.id, Creator.note != "")
        .all()
    )
    return "\n".join(f"- 对标「{c.name}」：{c.note}" for c in rows)


def _persona_context(db: Session) -> dict:
    q = db.query(PersonaTag).filter(PersonaTag.status == "confirmed")
    cid = _creator_filter(db)
    if cid:
        q = q.filter(PersonaTag.creator_id == cid)
    tags = q.order_by(PersonaTag.category, PersonaTag.id).all()
    return {
        "tags": [f"{t.label}: {t.description}" for t in tags if t.category not in ("redline", "phrase")],
        "anchors": [t.label for t in tags if t.category == "phrase"],
        "redlines": [t.label for t in tags if t.category == "redline"],
    }


def _all_texts(db: Session) -> list[tuple[Video, str]]:
    """全部非广告素材的可用文案（corrected 优先），保证全量参与学习。"""
    rows = []
    q = db.query(Video).filter(Video.is_ad.is_(False))
    cid = _creator_filter(db)
    if cid:
        q = q.filter(Video.creator_id == cid)
    for v in q.all():
        if v.transcript and (v.transcript.corrected_text or v.transcript.transcript_text):
            rows.append((v, v.transcript.corrected_text or v.transcript.transcript_text))
    return rows


def _engagement(db: Session, video: Video) -> float:
    latest = (
        db.query(MetricsSnapshot)
        .filter(MetricsSnapshot.video_id == video.id)
        .order_by(MetricsSnapshot.snapshot_date.desc())
        .first()
    )
    if latest is None:
        return 0.0
    return float(latest.plays + latest.likes * 5 + latest.favorites * 3 + latest.comments * 10)


def _weight(db: Session, video: Video) -> float:
    """样本权重 = 表现加权 * 时间衰减（近的、数据好的样本更该被模仿）。"""
    engage = _engagement(db, video)
    base = video.published_at.date() if video.published_at else video.created_at.date()
    age = max((date.today() - base).days, 0)
    return (1.0 + math.log1p(engage)) * math.exp(-age / 500.0)


def _style_samples(db: Session, topic: str, k: int = 3) -> list[str]:
    rows = _all_texts(db)
    if not rows:
        return []
    docs, weights, seen = [], [], set()
    for v, text in rows:
        key = text.strip()[:200]
        if key in seen:
            continue  # 去重：同一文案只算一次
        seen.add(key)
        docs.append(text)
        weights.append(round(_weight(db, v), 6))
    # R-022：作者认可的高分/采用稿 = 黄金样本，更高权重
    from ..models.draft import Draft
    from ..models.feedback import Feedback

    approved = (
        db.query(Feedback.draft_id)
        .filter((Feedback.rating >= 4) | (Feedback.liked.is_(True)))
        .distinct()
        .all()
    )
    draft_ids = [r[0] for r in approved][:5]
    if draft_ids:
        dq = db.query(Draft).filter(Draft.id.in_(draft_ids), Draft.script != "")
        cid = _creator_filter(db)
        if cid:
            dq = dq.filter(Draft.creator_id == cid)
        for d in dq.all():
            key = (d.script or "").strip()[:200]
            if key in seen:
                continue
            seen.add(key)
            docs.append(d.script)
            weights.append(6.0)
    index = TfidfIndex().build(docs, weights)
    return [hit["text"] for hit in index.search(topic, top_k=k)]


def _style_profile_lines(db: Session) -> str:
    rows = _all_texts(db)
    texts = [text for _, text in rows]
    return format_style_profile(build_style_profile(texts))


def generate_draft(db: Session, topic: str, settings=None) -> Draft:
    ctx = _persona_context(db)
    samples = _style_samples(db, topic)
    profile = _style_profile_lines(db)
    refs = benchmark_context_lines(db)
    user = "\n".join(
        [
            f"选题：{topic}",
            "",
            "作者人设：",
            *[f"- {t}" for t in ctx["tags"] or ["（暂无）"]],
            "",
            "红线（不要违反）：",
            *[f"- {r}" for r in ctx["redlines"] or ["（无）"]],
            "",
            *([] if not ctx.get("anchors") else ["", "作者金句锚点（用它的短句语气，不要整句照搬）：", *[f"- {a}" for a in ctx["anchors"]]]),
            "作者语言习惯（从全部素材统计，必须模仿）：",
            profile,
            "",
            "风格样本（模仿语气的原文节选）：",
            *[f"--- 样本{i+1} ---\n{s[:400]}" for i, s in enumerate(samples)],
            *([] if not refs else ["", "对标博主风格参考（仅借鉴语气与结构，观点务必用作者自己的）：", refs]),
        ]
    )

    llm = DeepSeekClient(settings)
    try:
        data = llm.chat_json(
            [
                {"role": "system", "content": get_prompt("generation", db)},
                {"role": "user", "content": user},
            ],
            temperature=0.8,
            max_tokens=2500,
        )
        title = str(data.get("title", "")).strip()
        cover = str(data.get("cover_text", "")).strip()
        script = str(data.get("script", "")).strip()
        shells = data.get("shells") if isinstance(data.get("shells"), dict) else {}
    except LLMError:
        title = f"{topic}（mock 标题）"
        cover = (topic or "今日话题")[:8]
        script = (
            f"[mock 脚本] 大家好，今天想聊聊{topic}。"
            "很多人对这件事有误区，其实只要抓住三个关键点，结果会完全不一样。"
            "第一，先想清楚目标；第二，小步快跑试错；第三，持续复盘优化。"
            "如果你也有类似困惑，评论区告诉我，我们下期见。"
        )
        shells = {
            "douyin": f"#{topic} 短视频 干货分享",
            "bilibili": f"{topic} | 亲测有效的 3 个方法",
            "xiaohongshu": f"🔥 {topic}，建议收藏！",
        }

    draft = Draft(
        creator_id=_creator_filter(db),
        title=title or topic,
        cover_text=cover,
        script=script or topic,
        platform_shells=json.dumps(shells, ensure_ascii=False),
        source="ai",
        original_script=script or topic,
    )
    db.add(draft)
    db.commit()
    db.refresh(draft)
    return draft
