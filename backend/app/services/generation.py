"""选题生成服务：DeepSeek 生成三件套（标题/封面字/脚本）+ 平台外壳。

语气一致性：人设档案（标签+红线）+ 风格样本（本地 TF-IDF 检索）。
无密钥时输出确定性 mock 稿，保证开发/测试离线可跑。
"""

from __future__ import annotations

import json
import math
import re
import threading
from datetime import date

from sqlalchemy.orm import Session

from ..core.retrieval import TfidfIndex
from ..core.style_profile import build_style_profile, default_avoid_words, format_style_profile
from .prompt_service import get_prompt, get_prompt_version
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


_PROFILE_DICT_CACHE: dict[tuple, dict] = {}
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


def _style_samples(db: Session, topic: str, k: int | None = None) -> list[str]:
    """按选题检索风格样本；条数可配置（R-131：默认 5，范围 3~8）。"""
    if k is None:
        from ..models.kv import Kv

        row = db.get(Kv, "style_sample_count")
        try:
            k = int(row.value) if row is not None and row.value else 5
        except (TypeError, ValueError):
            k = 5
        k = max(3, min(8, k))
    return [hit["text"] for hit in _style_index(db).search(topic, top_k=k)]


def _style_anchor_ids(db: Session) -> list[int]:
    """作者指定的「风格范本」素材 id（R-131，存 app_kv）。"""
    from ..models.kv import Kv

    row = db.get(Kv, "style_anchor_video_ids")
    if row is None or not (row.value or "").strip():
        return []
    try:
        data = json.loads(row.value)
    except (TypeError, ValueError):
        return []
    out: list[int] = []
    for x in data if isinstance(data, list) else []:
        try:
            out.append(int(x))
        except (TypeError, ValueError):
            continue
    return out


def _style_anchor_samples(db: Session, limit: int = 5) -> list[str]:
    """风格范本素材的原文（必定注入，不参与检索淘汰，R-131）。"""
    ids = _style_anchor_ids(db)
    if not ids:
        return []
    from ..models.video import Video

    by_id = {v.id: v for v in db.query(Video).filter(Video.id.in_(ids)).all()}
    out: list[str] = []
    for vid in ids:
        v = by_id.get(vid)
        if v is None:
            continue
        tr = getattr(v, "transcript", None)
        text = (tr.corrected_text or tr.transcript_text or "").strip() if tr else ""
        if text:
            out.append(text)
        if len(out) >= limit:
            break
    return out


def _rewrite_examples(db: Session, limit: int = 2) -> str:
    """作者对 AI 初稿的真实修改（R-131）：最强的"像作者"信号，作为 few-shot 注入。

    优先取作者认可（高星/采用）的改稿；没有任何成对样本时返回空串（不注入、不影响生成）。
    """
    from ..models.draft import Draft
    from ..models.feedback import Feedback

    cid = _creator_filter(db)
    rated: dict[int, object] = {fb.draft_id: fb for fb in db.query(Feedback).all()}
    q = db.query(Draft).filter(Draft.source == "ai")
    if cid:
        q = q.filter(Draft.creator_id == cid)
    pairs: list[tuple[int, int, str, str]] = []
    for d in q.order_by(Draft.id.desc()).limit(60).all():
        original = (d.original_script or "").strip()
        edited = (d.script or "").strip()
        if not original or not edited or original == edited:
            continue
        fb = rated.get(d.id)
        score = 3
        if fb is not None and (bool(getattr(fb, "liked", False)) or int(getattr(fb, "rating", 0) or 0) >= 4):
            score = 5
        elif fb is not None and int(getattr(fb, "rating", 0) or 0) <= 2:
            score = 1
        pairs.append((score, d.id, original, edited))
    if not pairs:
        return ""
    pairs.sort(key=lambda x: (-x[0], -x[1]))
    blocks = [f"【AI 原稿】{o[:260]}\n【作者改后】{e[:260]}" for _s, _i, o, e in pairs[:limit]]
    return (
        "作者对 AI 初稿的真实修改（重点学他的改法：删了什么、把什么改得更口语、加了什么钩子；"
        "只学改法，不要照抄其中的具体内容）：\n" + "\n\n".join(blocks)
    )


def _style_profile(db: Session) -> dict:
    """风格画像 dict（进程内缓存：素材数量/字数变化才重算）。"""
    rows = _all_texts(db)
    texts = [text for _, text in rows]
    cid = _creator_filter(db) or 0
    key = (cid, len(texts), sum(len(t) for t in texts))
    with _PROFILE_LOCK:
        if key in _PROFILE_DICT_CACHE:
            return _PROFILE_DICT_CACHE[key]
        profile = build_style_profile(texts)
        if len(_PROFILE_DICT_CACHE) > 20:
            _PROFILE_DICT_CACHE.clear()
        _PROFILE_DICT_CACHE[key] = profile
        return profile


def _style_markers(db: Session, limit: int = 8) -> list[str]:
    """作者高频口头禅/标志用词（R-131：生成后自检「像不像」用）。"""
    try:
        return [str(x) for x in (_style_profile(db).get("top_phrases") or [])[:limit] if str(x).strip()]
    except Exception:  # noqa: BLE001
        return []


def _style_profile_lines(db: Session) -> str:
    return format_style_profile(_style_profile(db))


def _structure_templates(db: Session) -> str:
    """表现最好的内容结构模板（R-131）：开场句 + 结尾引导句，只学结构不抄内容。

    优先用作者认可（高星/采用）的草稿；没有时退回真实互动最高的素材转写稿。
    """
    from ..models.draft import Draft
    from ..models.feedback import Feedback

    cid = _creator_filter(db)
    starters: list[str] = []
    q = (
        db.query(Draft, Feedback)
        .join(Feedback, Feedback.draft_id == Draft.id)
        .filter((Feedback.rating >= 4) | (Feedback.liked.is_(True)))
    )
    if cid:
        q = q.filter(Draft.creator_id == cid)
    for d, _fb in q.order_by(Feedback.id.desc()).limit(12).all():
        script = (d.script or "").strip()
        if not script:
            continue
        sentences = [x.strip() for x in re.split(r"[。！？!?\n]+", script) if x.strip()]
        if not sentences:
            continue
        starters.append(f"《{d.title or '无题'}》开场：{sentences[0][:60]} → 结尾：{sentences[-1][:50]}")
        if len(starters) >= 3:
            break
    if not starters:
        # 无评分反馈时：用互动最高的素材转写稿的开场/结尾
        rows = sorted(_all_texts(db), key=lambda vt: _weight(db, vt[0]), reverse=True)[:3]
        for _v, text in rows:
            sentences = [x.strip() for x in re.split(r"[。！？!?\n]+", text) if x.strip()]
            if not sentences:
                continue
            starters.append(f"开场：{sentences[0][:60]} → 结尾：{sentences[-1][:50]}")
    if not starters:
        return ""
    return "表现最好的内容结构模板（只学开场与收尾的结构，内容要新）：\n" + "\n".join(f"- {x}" for x in starters)


def generation_user_message(db: Session, topic: str) -> str:
    """生成用的 user 上下文（R-129：抽出来，供「金样本回放评分」用同一份输入）。"""
    ctx = _persona_context(db)
    samples = _style_samples(db, topic)
    anchors = _style_anchor_samples(db)
    profile = _style_profile_lines(db)
    refs = benchmark_context_lines(db)
    structure = _structure_templates(db)
    rewrites = _rewrite_examples(db)
    return "\n".join(
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
            *([] if not anchors else ["", "作者指定为风格范本的素材（必须重点模仿其语气与节奏）：", *[f"--- 范本{i+1} ---\n{s[:400]}" for i, s in enumerate(anchors)]]),
            "",
            "风格样本（按选题检索的真实原文节选）：",
            *[f"--- 样本{i+1} ---\n{s[:400]}" for i, s in enumerate(samples)],
            *([] if not structure else ["", structure]),
            *([] if not rewrites else ["", rewrites]),
            *([] if not refs else ["", "对标博主风格参考（仅借鉴语气与结构，观点务必用作者自己的）：", refs]),
        ]
    )


def _self_check(db: Session, script: str) -> tuple[list[str], float]:
    """生成后自检（R-131）：红线命中 / AI 腔禁用词 / 口癖覆盖率。返回 (问题列表, 口癖覆盖率)。"""
    text = script or ""
    issues: list[str] = []
    ctx = _persona_context(db)
    for redline in ctx["redlines"]:
        if len(redline) >= 6 and redline in text:
            issues.append(f"命中红线：{redline[:20]}")
    for word in _avoid_words(db):
        if word and word in text:
            issues.append(f"用了 AI 腔词：{word}")
    markers = _style_markers(db)
    coverage = 0.0
    if markers:
        coverage = sum(1 for m in markers if m in text) / len(markers)
        if coverage == 0:
            issues.append("没有用上作者的标志性口癖/用词")
    return issues, round(coverage, 4)


def generate_draft(db: Session, topic: str, settings=None) -> Draft:
    user = generation_user_message(db, topic)
    system = get_prompt("generation", db)
    llm = DeepSeekClient(settings)
    attempts = 0
    issues: list[str] = []
    coverage = 0.0
    is_mock = False
    while attempts < 2:
        attempts += 1
        try:
            data = llm.chat_json(
                [{"role": "system", "content": system}, {"role": "user", "content": user}],
                temperature=0.8,
                max_tokens=2500,
            )
            title = str(data.get("title", "")).strip()
            cover = str(data.get("cover_text", "")).strip()
            script = str(data.get("script", "")).strip()
            shells = data.get("shells") if isinstance(data.get("shells"), dict) else {}
        except LLMError:
            is_mock = True
            issues = []
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
            break
        issues, coverage = _self_check(db, script)
        if not issues:
            break
        if attempts >= 2:
            break
        # 自检不通过：带上问题重写一次（R-131，最多 1 次）
        user = user + "\n\n上一次生成存在这些问题，请重写并避免：\n" + "\n".join(f"- {i}" for i in issues)

    cid = _creator_filter(db)
    from .persona_profile import current_persona_version

    quality = json.dumps(
        {
            "attempts": attempts,
            "issues": issues,
            "passed": not issues,
            "style_coverage": coverage,
            "mock": is_mock,
        },
        ensure_ascii=False,
    )
    draft = Draft(
        creator_id=cid,
        title=title or topic,
        cover_text=cover,
        script=script or topic,
        platform_shells=json.dumps(shells, ensure_ascii=False),
        source="ai",
        original_script=script or topic,
        prompt_version=get_prompt_version("generation", db),  # R-129 M116：按提示词版本归因
        persona_version=current_persona_version(db, cid),  # R-130：人设变化可控
        quality=quality,  # R-131：生成后自检留痕
    )
    db.add(draft)
    db.commit()
    db.refresh(draft)
    return draft
