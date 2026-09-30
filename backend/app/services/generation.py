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

from ..config import get_settings
from ..core.retrieval import TfidfIndex
from ..core.style_profile import build_style_profile, default_avoid_words, format_style_profile
from .prompt_service import get_prompt_version
from ..models.draft import Draft
from ..models.metrics import MetricsSnapshot
from ..models.persona import PersonaTag
from ..models.video import Video
from .llm import LLMError

GENERATION_SYSTEM = (
    "你是这位作者的代笔，写出来要像他本人对着镜头说话：真实、具体、口语，"
    "不要 AI 腔、不要书面套话、不要正确但没用的空话。\n"
    "怎么写由「作者人设 + 本次创作模式 + 风格样本」决定，不要套固定模板；"
    "观点必须用作者自己的，例子优先用作者真实经历；给方向也可以，但别喂到嘴里。\n"
    "严格按末尾的输出契约返回，不输出额外文字。\n"
    "输出契约（系统固定，不得改动字段名与结构）：\n"
    '只输出 JSON：{"title":"视频标题","cover_text":"封面字","script":"完整口播脚本（1-2 分钟，约200-400字，口语化，有钩子有收尾）",'
    '"shells":{"douyin":"抖音发布文案+话题标签","bilibili":"B站简介","xiaohongshu":"小红书笔记正文（含emoji与话题）"}}'
)

# R-183：创作模式——把「是否犀利/独白/追热点/做实验」从提示词里拿出来，改成显式参数。
CREATION_MODES: dict[str, dict[str, str]] = {
    "sharp": {
        "label": "犀利干货",
        "guide": "以犀利干货为主：直接给判断和可执行动作，先破后立、观点鲜明，少铺垫。",
    },
    "monologue": {
        "label": "个人独白",
        "guide": "以个人独白为主：第一人称讲自己的经历、状态与感受，真诚、具体，不强行升华。",
    },
    "commentary": {
        "label": "热点评论",
        "guide": "以热点评论为主：借热点事件表达作者的鲜明立场，联系自己的经验，观点用作者自己的。",
    },
    "experiment": {
        "label": "实验复盘",
        "guide": "以实验复盘为主：把一件事当实验，讲清做法、过程与结果，结论留有余地。",
    },
}


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
    from .persona import LAYER_LABELS, LAYERS

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
    return {
        "tags": [_fmt(t) for t in style_tags],
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
    # R-022：作者认可的稿 = 黄金样本，更高权重
    # R-211：认可口径从「评分/点赞」改为 status 驱动——完成（done）即认可（历史 rating/liked 弃用）
    from ..models.draft import Draft

    dq = db.query(Draft).filter(Draft.status == "done", Draft.script != "")
    cid0 = _creator_filter(db)
    if cid0:
        dq = dq.filter(Draft.creator_id == cid0)
    for d in dq.order_by(Draft.id.desc()).limit(5).all():
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
    """作者对初稿的真实修改（R-131）：最强的"像作者"信号，作为 few-shot 注入。

    R-209：版本链按 source 归因——配对 = 「最后一个**作者侧**版本（manual/rollback）← 它的前一版」。
    这样「AI 讨论后被作者回退」会正确产出【AI 稿 → 作者改回的原稿】（= 作者否定该讨论方向），
    而不是反过来把 AI 讨论稿当成「作者改后」。没有任何作者侧版本时退回
    `original_script → script`（老行为，仅 source="ai" 的稿有 original_script 语义）。
    R-211：样本权重从评分/点赞改为 status 驱动（done=5 / archived=1 / 其它=3）。
    """
    from ..models.draft import Draft
    from .draft_versions import AUTHOR_SOURCES, chains_with_sources

    cid = _creator_filter(db)
    q = db.query(Draft).filter(Draft.source == "ai")
    if cid:
        q = q.filter(Draft.creator_id == cid)
    drafts = q.order_by(Draft.id.desc()).limit(60).all()
    chains = chains_with_sources(db, drafts)
    pairs: list[tuple[int, int, str, str, str]] = []
    for d in drafts:
        original, edited = "", ""
        orig_label = "初稿"
        stages = chains.get(d.id) or []
        author_idx = max((i for i, (src, _t) in enumerate(stages) if src in AUTHOR_SOURCES), default=None)
        if author_idx is not None and author_idx > 0:
            prev_src, prev_text = stages[author_idx - 1]
            original, edited = prev_text, stages[author_idx][1]
            orig_label = "AI 稿" if prev_src not in AUTHOR_SOURCES else "作者上一版"
        else:
            # 无版本链（或链上无作者定稿）时的老行为：original_script=AI 原稿 → 当前稿
            o = (d.original_script or "").strip()
            e = (d.script or "").strip()
            if o and e:
                original, edited, orig_label = o, e, "AI 原稿"
        if not original or not edited or original == edited:
            continue
        if d.status == "done":
            score = 5
        elif d.status == "archived":
            score = 1
        else:
            score = 3
        pairs.append((score, d.id, orig_label, original, edited))
    if not pairs:
        return ""
    pairs.sort(key=lambda x: (-x[0], -x[1]))
    blocks = [f"【{label}】{o[:260]}\n【作者改后】{e[:260]}" for _s, _i, label, o, e in pairs[:limit]]
    return (
        "作者对初稿的真实修改（重点学他的改法：删了什么、把什么改得更口语、加了什么钩子；"
        "被作者改回旧版的方向就是他否定的方向；只学改法，不要照抄其中的具体内容）：\n" + "\n\n".join(blocks)
    )


def _reverted_lessons(db: Session, limit: int = 3) -> str:
    """R-209：「讨论后作者又改回了自己的原稿」= 被否定的讨论方向，作为反面信号注入。

    检测口径：版本链中某作者侧版本的正文与更早一版相同、且两版之间有 AI 侧版本
    （= AI 改了一轮，作者最终恢复旧版）。手稿讨论后被回退是最典型场景。
    """
    from ..models.draft import Draft
    from .draft_versions import AI_SOURCES, AUTHOR_SOURCES, chains_with_sources

    cid = _creator_filter(db)
    q = db.query(Draft).filter(Draft.status != "deleted")
    if cid:
        q = q.filter(Draft.creator_id == cid)
    drafts = q.order_by(Draft.id.desc()).limit(60).all()
    lessons: list[tuple[int, str, str]] = []
    for d in drafts:
        stages = chains_with_sources(db, [d]).get(d.id) or []
        for i in range(len(stages) - 1, 0, -1):
            src_i, text_i = stages[i]
            if src_i not in AUTHOR_SOURCES:
                continue
            for j in range(i - 1, -1, -1):
                if stages[j][1] != text_i:
                    continue
                between = stages[j + 1 : i]
                ai_between = [t for s, t in between if s in AI_SOURCES]
                if ai_between:
                    lessons.append((d.id, ai_between[-1], text_i))
                break
            else:
                continue
            break  # 每篇稿只取最近一次回退
    if not lessons:
        return ""
    blocks = [f"【AI 讨论稿】{ai[:220]}\n【作者改回自己的原稿】{orig[:220]}" for _i, ai, orig in lessons[:limit]]
    return (
        "作者讨论后又改回了自己原来的稿子——他不喜欢 AI 的这个讨论方向，以后避免这样改：\n"
        + "\n\n".join(blocks)
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

    优先用作者认可的稿；没有时退回真实互动最高的素材转写稿。
    R-211：认可口径改 status 驱动——完成（done）即认可（历史 rating/liked 弃用）。
    """
    from ..models.draft import Draft

    cid = _creator_filter(db)
    starters: list[str] = []
    q = db.query(Draft).filter(Draft.status == "done", Draft.script != "")
    if cid:
        q = q.filter(Draft.creator_id == cid)
    for d in q.order_by(Draft.updated_at.desc()).limit(12).all():
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


def author_style_context(db: Session, topic: str = "", mode: str = "") -> str:
    """作者人设 + 语言习惯 + 样本/范本/结构/分节范例/对标参考的共享上下文。

    R-181：生成与「参考改写（洗稿）」共用同一份上下文，避免洗稿只拿到简化人设、
    不像作者本人。`topic` 非空时按选题检索风格样本；`mode`（R-183）为创作模式。
    """
    ctx = _persona_context(db)
    samples = _style_samples(db, topic) if topic else _style_samples(db, "")
    anchors = _style_anchor_samples(db)
    profile = _style_profile_lines(db)
    refs = benchmark_context_lines(db)
    structure = _structure_templates(db)
    rewrites = _rewrite_examples(db)
    reverted = _reverted_lessons(db)  # R-209：被作者改回原稿的讨论方向（反面信号）
    avoid = _avoid_words(db)
    mode_info = CREATION_MODES.get((mode or "").strip())
    return "\n".join(
        [
            "作者人设：",
            *[f"- {t}" for t in ctx["tags"] or ["（暂无）"]],
            *([] if not mode_info else ["", f"本次创作模式：{mode_info['label']}——{mode_info['guide']}"]),
            "",
            "红线（不要违反）：",
            *[f"- {r}" for r in ctx["redlines"] or ["（无）"]],
            "",
            *([] if not ctx.get("anchors") else ["作者金句锚点（用它的短句语气，不要整句照搬）：", *[f"- {a}" for a in ctx["anchors"]], ""]),
            "作者语言习惯（自然贴近即可，**不要硬塞口头禅/标志词**，更不要为了像而像）：",
            profile,
            *([] if not avoid else ["", "这些表达尽量别用（AI 腔/套话，用了会不像真人）：", "、".join(avoid[:20])]),
            *([] if not anchors else ["", "作者指定为风格范本的素材（重点体会其语气与节奏，学语气、不要照搬词句）：", *[f"--- 范本{i+1} ---\n{s[:400]}" for i, s in enumerate(anchors)]]),
            "",
            "风格样本（按选题检索的真实原文节选）：",
            *[f"--- 样本{i+1} ---\n{s[:400]}" for i, s in enumerate(samples)],
            *([] if not structure else ["", structure]),
            *([] if not rewrites else ["", rewrites]),
            *([] if not reverted else ["", reverted]),
            *([] if not refs else ["", "对标博主风格参考（仅借鉴语气与结构，观点务必用作者自己的）：", refs]),
        ]
    )


def generation_user_message(db: Session, topic: str, mode: str = "") -> str:
    """生成用的 user 上下文（R-129：抽出来，供「金样本回放评分」用同一份输入）。"""
    return "\n".join([f"选题：{topic}", "", author_style_context(db, topic, mode)])



def style_diagnostics(db: Session, script: str) -> dict:
    """风格诊断（R-207，纯只读、不触发重写）：口癖/高频词覆盖率 + 命中/未命中 + AI 腔词命中。

    作者口径：正向模仿型指标（口癖/高频词）只做诊断，**不作为硬门禁**——
    否则模型会为通过自检而机械塞口头禅，产出「模仿腔」。
    """
    text = script or ""
    markers = _style_markers(db)
    matched = [m for m in markers if m in text]
    missing = [m for m in markers if m not in text]
    coverage = round(len(matched) / len(markers), 4) if markers else 0.0
    cliche = [w for w in _avoid_words(db) if w and w in text]
    return {
        "style_coverage": coverage,
        "style_matched": matched,
        "style_missing": missing,
        "ai_cliche": cliche,
    }


def _self_check(db: Session, script: str) -> tuple[list[str], float]:
    """生成后自检（R-207）：**只有红线**算硬问题（触发一次收口重写）。

    AI 腔词、口癖/高频词覆盖率不再进 `issues`，改由 :func:`style_diagnostics` 记录为诊断，
    只展示、不强制重写。返回值第二项保留为口癖覆盖率（诊断值），兼容旧调用。
    """
    text = script or ""
    issues: list[str] = []
    ctx = _persona_context(db)
    for redline in ctx["redlines"]:
        if len(redline) >= 6 and redline in text:
            issues.append(f"命中红线：{redline[:20]}")
    return issues, style_diagnostics(db, text)["style_coverage"]


def _mock_payload(topic: str) -> tuple[str, str, str, dict]:
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
    return title, cover, script, shells


def generate_draft(db: Session, topic: str, settings=None, snapshot: bool = True, mode: str = "") -> Draft:
    """生成一篇脚本草稿（R-139：与工作台/每日自动生成完全相同的双模型讨论路径）。

    流程：建占位稿 → `run_debate`（生成方初稿 + 评审方 N 轮挑刺 + 生成方修订 + 自检收口）
    → 草稿上带 `quality`（含模型组合 / 是否降级 / 轮次 / 自检结果）。
    无密钥或两个模型都不可用时回落到确定性 mock 稿（开发/离线可跑，`quality.mock=True`）。
    R-157：默认生成完自动定稿留一版；`snapshot=False` 用于金样本自测 / 回炉中间稿（不留版）。
    R-183：`mode` 为创作模式（sharp/monologue/commentary/experiment），空=不指定。
    """
    from .debate import PLACEHOLDER_SCRIPT, debate_rounds, run_debate

    settings = settings or get_settings()
    cid = _creator_filter(db)
    from .persona_profile import current_persona_version

    draft = Draft(
        creator_id=cid,
        title=topic,
        cover_text="",
        script=PLACEHOLDER_SCRIPT,
        source="ai",
        prompt_version=get_prompt_version("generation", db),  # R-129 M116：按提示词版本归因
        persona_version=current_persona_version(db, cid),  # R-130：人设变化可控
    )
    db.add(draft)
    db.commit()
    db.refresh(draft)

    try:
        run_debate(db, draft, topic, settings, mode=mode)
    except LLMError as exc:
        # 无密钥 / 两个模型全挂 → 确定性 mock 稿（保留草稿，绝不静默丢稿）
        db.rollback()
        draft = db.get(Draft, draft.id) or draft
        title, cover, script, shells = _mock_payload(topic)
        draft.title = title
        draft.cover_text = cover
        draft.script = script
        draft.platform_shells = json.dumps(shells, ensure_ascii=False)
        draft.quality = json.dumps(
            {
                "mock": True,
                "reason": str(exc)[:200],
                "rounds": debate_rounds(db, settings),
                "issues": [],
                "passed": False,
                "style_coverage": 0.0,
                "diagnostics": {
                    "style_coverage": 0.0,
                    "style_matched": [],
                    "style_missing": [],
                    "ai_cliche": [],
                },
            },
            ensure_ascii=False,
        )
        db.commit()
        db.refresh(draft)

    draft.original_script = draft.script
    db.commit()
    db.refresh(draft)
    if snapshot:
        from .draft_versions import finalize_version

        finalize_version(db, draft, source="ai_generate", note="AI 生成")
    return draft
