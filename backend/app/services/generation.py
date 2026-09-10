"""选题生成服务：DeepSeek 生成三件套（标题/封面字/脚本）+ 平台外壳。

语气一致性：人设档案（标签+红线）+ 风格样本（本地 TF-IDF 检索）。
无密钥时输出确定性 mock 稿，保证开发/测试离线可跑。
"""

from __future__ import annotations

import json
import math
import threading
from datetime import date

from sqlalchemy.orm import Session

from ..core.retrieval import TfidfIndex
from ..core.style_profile import build_style_profile, default_avoid_words, format_style_profile
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


def _avoid_words(db: Session) -> list[str]:
    """AI 腔禁用/少用词：默认内置清单，Persona 风格接口可覆盖（存 [] 表示关闭）。"""
    from ..models.kv import Kv

    row = db.get(Kv, "ai_no_words")
    if row is None:
        return default_avoid_words()
    try:
        val = json.loads(row.value or "[]")
        return [str(x).strip() for x in val if str(x).strip()]
    except (TypeError, ValueError):
        return default_avoid_words()


def _persona_context(db: Session) -> dict:
    q = db.query(PersonaTag).filter(PersonaTag.status == "confirmed")
    cid = _creator_filter(db)
    if cid:
        q = q.filter(PersonaTag.creator_id == cid)
    tags = q.order_by(PersonaTag.category, PersonaTag.id).all()

    def _fmt(t: PersonaTag) -> str:
        dim = (getattr(t, "dimension", "") or "").strip()
        prefix = f"[{dim}] " if dim else ""
        return f"{prefix}{t.label}: {t.description}"

    return {
        "tags": [_fmt(t) for t in tags if t.category not in ("redline", "phrase")],
        "anchors": [t.label for t in tags if t.category == "phrase"],
        "redlines": [t.label for t in tags if t.category == "redline"],
    }


_PROFILE_CACHE: dict[tuple, str] = {}
_PROFILE_LOCK = threading.Lock()


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


def _best_practice_lines(db: Session) -> str:
    """R-030④：把近期表现最好的草稿共性（标题/开头/结尾）注入生成，模仿结构不抄内容。"""
    from ..models.draft import Draft
    from ..models.feedback import Feedback
    from .creator_service import get_current_creator

    creator = get_current_creator(db)
    q = (
        db.query(Draft, Feedback)
        .join(Feedback, Feedback.draft_id == Draft.id)
        .filter((Feedback.rating >= 4) | (Feedback.liked.is_(True)))
        .order_by(Feedback.id.desc())
        .limit(12)
    )
    if creator:
        q = q.filter(Draft.creator_id == creator.id)
    rows = q.all()
    lines: list[str] = []
    for d, _f in rows[:3]:
        if not d.script:
            continue
        first = next((x.strip() for x in d.script.split("\n") if x.strip()), d.script)[:80]
        tail = [x.strip() for x in d.script.split("\n") if x.strip()]
        ending = tail[-1][:60] if tail else ""
        lines.append(f"《{d.title or '无题'}》 开头：{first} … 结尾引导：{ending}")
    if not lines:
        return ""
    return "\n".join(f"- {x}" for x in lines)


_INDEX_CACHE: dict[tuple, "TfidfIndex"] = {}
_INDEX_LOCK = threading.Lock()


def _material_version(db: Session) -> tuple:
    """轻量版本号：转写素材/指标/反馈/草稿变化时检索索引自动失效。"""
    from ..models.video import Transcript

    cid = _creator_filter(db) or 0
    q = (
        db.query(Transcript.id)
        .join(Video, Video.id == Transcript.video_id)
        .filter(Video.is_ad.is_(False))
    )
    if cid:
        q = q.filter(Video.creator_id == cid)
    ids = [r[0] for r in q.all()]
    t_max = max(ids) if ids else 0
    from ..models.draft import Draft
    from ..models.feedback import Feedback

    return (
        cid,
        len(ids),
        t_max,
        db.query(MetricsSnapshot).count(),
        db.query(Feedback).count(),
        db.query(Draft).filter(Draft.script != "").count(),
    )


def _build_style_index(db: Session) -> "TfidfIndex":
    """构建过程与旧 _style_samples 完全一致（文档+权重+黄金样本），仅移入缓存。"""
    rows = _all_texts(db)
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
    return TfidfIndex().build(docs, weights)


def _style_index(db: Session) -> "TfidfIndex":
    """进程内缓存 TF-IDF 检索索引（素材版本变化才重建，结果与原来一致）。"""
    version = _material_version(db)
    with _INDEX_LOCK:
        if version in _INDEX_CACHE:
            return _INDEX_CACHE[version]
        index = _build_style_index(db)
        if len(_INDEX_CACHE) > 10:
            _INDEX_CACHE.clear()
        _INDEX_CACHE[version] = index
        return index


def _style_samples(db: Session, topic: str, k: int = 3) -> list[str]:
    return [hit["text"] for hit in _style_index(db).search(topic, top_k=k)]


def _style_profile_lines(db: Session) -> str:
    """风格画像文本（进程内缓存：素材数量/字数变化才重算；结果与原来完全一致）。"""
    rows = _all_texts(db)
    texts = [text for _, text in rows]
    cid = _creator_filter(db) or 0
    key = (cid, len(texts), sum(len(t) for t in texts))
    with _PROFILE_LOCK:
        if key in _PROFILE_CACHE:
            return _PROFILE_CACHE[key]
        out = format_style_profile(build_style_profile(texts))
        if len(_PROFILE_CACHE) > 20:
            _PROFILE_CACHE.clear()
        _PROFILE_CACHE[key] = out
        return out


def generate_draft(db: Session, topic: str, settings=None) -> Draft:
    ctx = _persona_context(db)
    samples = _style_samples(db, topic)
    profile = _style_profile_lines(db)
    refs = benchmark_context_lines(db)
    best = _best_practice_lines(db)
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
            *([] if not _avoid_words(db) else ["", "这些表达尽量别用（AI 腔/套话，用了会不像真人）：", "、".join(_avoid_words(db)[:20])]),
            "",
            "风格样本（模仿语气的原文节选）：",
            *[f"--- 样本{i+1} ---\n{s[:400]}" for i, s in enumerate(samples)],
            *([] if not refs else ["", "对标博主风格参考（仅借鉴语气与结构，观点务必用作者自己的）：", refs]),
            *([] if not best else ["", "你近期表现最好的草稿共性（学它的结构和收束方式，内容要新）：", best]),
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
