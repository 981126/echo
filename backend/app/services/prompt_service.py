"""AI 提示词版本服务（R-021）。

每个功能一份提示词，DB 中版本化：
- 默认值懒加载自各服务模块常量（首次启动 seed 入库）
- get_prompt：取当前 enabled 版本
- save：另存为新版本并启用（旧版归档）
- create_candidate：自动优化产出候选（不启用）
- enable：启用指定版本（其余归档）
"""

from __future__ import annotations

from importlib import import_module

from sqlalchemy.orm import Session

from ..models.prompt import AiPrompt
from .llm import DeepSeekClient, LLMError

# key -> (module, 常量名, 中文名)
PROMPT_META: dict[str, tuple[str, str, str]] = {
    "generation": ("app.services.generation", "GENERATION_SYSTEM", "生成脚本"),
    "persona_init": ("app.services.persona", "PERSONA_INIT_SYSTEM", "人设逐篇提取"),
    "persona_merge": ("app.services.persona", "PERSONA_MERGE_SYSTEM", "人设归纳合并"),
    "video_tags": ("app.services.persona", "VIDEO_TAGS_SYSTEM", "视频预打标"),
    "persona_updates": ("app.services.persona", "PERSONA_UPDATES_SYSTEM", "人设增量合并"),
    "persona_compare": ("app.services.persona", "PERSONA_COMPARE_SYSTEM", "人设差异复核"),
    "review": ("app.services.review", "REVIEW_SYSTEM", "复盘 ABCD"),
    "diff": ("app.services.diff_analysis", "DIFF_SYSTEM", "改稿差异"),
    "chat": ("app.services.chat_service", "SYSTEM_PROMPT", "AI 对话"),
    "correct": ("app.services.ingest", "CORRECT_SYSTEM", "转写校对"),
}

OPT_SYSTEM = (
    "你是提示词工程专家，正在帮一位自媒体作者优化他自己在用的 AI 提示词。"
    "你的目标不是把它改得更死，而是让它更像这位作者（R-128）。"
    "请这样做：\n"
    "1. 先把作者的人设档案、语言习惯画像、真实口播文案读进去，判断当前提示词哪里没抓住作者的味道。\n"
    "2. 优化时只给「方向盘」——交代角色、目标、必须遵守的红线即可；"
    "不要用过多硬性的条数/字数/句式限制去锁死 AI 的思路，让模型有深度学习与自由发挥的空间。\n"
    "3. 素材按点赞率/互动从高到低排列：越靠前越代表作者受欢迎的真实腔调，权重越高，应重点模仿。\n"
    "4. 程序需要解析的输出格式（如 JSON 字段名/返回结构）必须保持不变；除此之外的内容可以大胆重写。\n"
    "只输出优化后的提示词正文，不要解释、不要 markdown 代码块。"
)


def default_content(key: str) -> str:
    mod_name, attr, _ = PROMPT_META[key]
    return str(getattr(import_module(mod_name), attr))


def label(key: str) -> str:
    return PROMPT_META[key][2]


def get_prompt(key: str, db: Session | None = None) -> str:
    """取当前启用版本的提示词；无记录时回退代码默认值。"""
    from ..db import SessionLocal

    own = db is None
    session: Session = db or SessionLocal()
    try:
        row = (
            session.query(AiPrompt)
            .filter(AiPrompt.key == key, AiPrompt.status == "enabled")
            .order_by(AiPrompt.version.desc())
            .first()
        )
        if row:
            return row.content
    finally:
        if own:
            session.close()
    try:
        return default_content(key)
    except Exception:
        return ""


def ensure_defaults(db: Session) -> None:
    """首次启动把各功能默认提示词 seed 为 v1（enabled）。"""
    for key in PROMPT_META:
        exists = (
            db.query(AiPrompt).filter(AiPrompt.key == key).order_by(AiPrompt.version.desc()).first()
        )
        if exists is None:
            db.add(AiPrompt(key=key, version=1, content=default_content(key), status="enabled", note="系统默认"))
    db.commit()


def _next_version(db: Session, key: str) -> int:
    row = db.query(AiPrompt).filter(AiPrompt.key == key).order_by(AiPrompt.version.desc()).first()
    return (row.version + 1) if row else 1


def save_new_version(db: Session, key: str, content: str, note: str = "") -> AiPrompt:
    """手动编辑保存 = 另存为新版本并启用（旧 enabled 转 archived）。"""
    content = (content or "").strip()
    db.query(AiPrompt).filter(AiPrompt.key == key, AiPrompt.status == "enabled").update(
        {"status": "archived"}, synchronize_session=False
    )
    row = AiPrompt(key=key, version=_next_version(db, key), content=content, status="enabled", note=note or "手动编辑")
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def create_candidate(db: Session, key: str, content: str, note: str = "") -> AiPrompt:
    row = AiPrompt(
        key=key, version=_next_version(db, key), content=content, status="candidate", note=note or "AI 自动优化候选"
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def enable_version(db: Session, key: str, version: int) -> AiPrompt | None:
    row = (
        db.query(AiPrompt)
        .filter(AiPrompt.key == key, AiPrompt.version == version)
        .first()
    )
    if row is None:
        return None
    db.query(AiPrompt).filter(AiPrompt.key == key, AiPrompt.status == "enabled").update(
        {"status": "archived"}, synchronize_session=False
    )
    row.status = "enabled"
    db.commit()
    db.refresh(row)
    return row


def feedback_context(db: Session) -> str:
    """把作者的高分/低分反馈摘要带进优化输入（R-022 回流 C）。"""
    from ..models.draft import Draft
    from ..models.feedback import Feedback

    lines = []
    lows = (
        db.query(Feedback, Draft)
        .join(Draft, Feedback.draft_id == Draft.id)
        .filter(Feedback.rating <= 2)
        .order_by(Feedback.id.desc())
        .limit(3)
        .all()
    )
    highs = (
        db.query(Feedback, Draft)
        .join(Draft, Feedback.draft_id == Draft.id)
        .filter((Feedback.rating >= 4) | (Feedback.liked.is_(True)))
        .order_by(Feedback.id.desc())
        .limit(3)
        .all()
    )
    if highs:
        lines.append("作者认可（4-5 分/采用）的稿子节选——保持这种腔调：")
        for _fb, d in highs:
            if d and d.script:
                lines.append(f"- {d.script[:200]}")
    if lows:
        lines.append("作者不满意（1-2 分）的稿子节选——避免这种腔调：")
        for _fb, d in lows:
            if d and d.script:
                lines.append(f"- {d.script[:200]}")
    return "\n".join(lines)


def learning_material(db: Session, max_items: int = 16) -> str:
    """组装「提示词优化语料」：人设 + 语言画像 + 全部 ASR 转写文案（按点赞率/互动加权）。

    不再只看最新单条视频：当前所有真实口播文案（优先 ASR 转写）参与，
    点赞率/互动高的权重更高、排更前；人设与红线一并作为优化输入。
    """
    import math
    from datetime import date as _date

    from ..models.metrics import MetricsSnapshot
    from ..models.video import Video
    from .generation import _creator_filter, _persona_context, _style_profile_lines
    from .metrics import _platform_breakdown

    parts: list[str] = []
    cid = _creator_filter(db)

    ctx = _persona_context(db)
    if ctx.get("tags"):
        parts.append("作者人设档案（逐篇提取 + AI 归纳合并，方括号为维度）：\n" + "\n".join(f"- {t}" for t in ctx["tags"]))
    if ctx.get("redlines"):
        parts.append("红线（不要违反）：\n" + "\n".join(f"- {r}" for r in ctx["redlines"]))
    if ctx.get("anchors"):
        parts.append("作者金句锚点：\n" + "\n".join(f"- {a}" for a in ctx["anchors"]))
    try:
        profile = _style_profile_lines(db)
        if profile:
            parts.append("作者语言习惯画像（从全部素材统计）：\n" + profile)
    except Exception:  # noqa: BLE001 画像失败不阻断
        pass

    q = db.query(Video).filter(Video.is_ad.is_(False))
    if cid:
        q = q.filter(Video.creator_id == cid)
    snap: dict[int, MetricsSnapshot] = {}
    for _s in db.query(MetricsSnapshot).order_by(MetricsSnapshot.snapshot_date.desc()).all():
        snap.setdefault(_s.video_id, _s)

    scored: list[tuple[float, str, str]] = []
    for v in q.all():
        tr = v.transcript
        if tr is None:
            continue
        text = (tr.corrected_text or tr.transcript_text or "").strip()
        if not text:
            continue
        plays = likes = fav = comments = 0
        for row in _platform_breakdown(db, v):  # 绑定平台最新真实数据
            plays += int(row.get("plays") or 0)
            likes += int(row.get("likes") or 0)
            fav += int(row.get("favorites") or 0)
            comments += int(row.get("comments") or 0)
        if plays <= 0 and likes <= 0:  # 无平台数据退回指标快照
            s = snap.get(v.id)
            if s is not None:
                plays = int(s.plays or 0)
                likes = int(s.likes or 0)
                fav = int(s.favorites or 0)
                comments = int(s.comments or 0)
        rate = min((likes / plays), 1.0) if plays > 0 else 0.0
        engage = plays + likes * 5 + fav * 3 + comments * 10
        base = v.published_at.date() if v.published_at else v.created_at.date()
        age = max((_date.today() - base).days, 0)
        w = (1.0 + math.log1p(engage)) * (1.0 + rate * 3.0) * math.exp(-age / 400.0)
        scored.append((w, text, f"播放{plays} 赞{likes} 藏{fav} 评{comments}"))
    scored.sort(key=lambda x: x[0], reverse=True)

    if scored:
        lines = []
        for i, (_w, text, stat) in enumerate(scored[:max_items], 1):
            lines.append(f"[素材{i}] {stat}：\n{text[:300]}")
        parts.append(
            "作者真实口播文案（全部 ASR 转写，按点赞率/互动加权从高到低，越靠前越该学）：\n"
            + "\n\n".join(lines)
        )
        if len(scored) > max_items:
            parts.append(f"（另有 {len(scored) - max_items} 条，只取权重最高的前 {max_items} 条）")
    return "\n\n".join(parts)


def optimize(db: Session, key: str, material: str = "") -> AiPrompt | None:
    """基于当前启用版 + 人设/全量素材(按点赞率加权) + 打分反馈，产出候选新版（不启用）。"""
    current = get_prompt(key, db)
    if not current:
        return None
    try:
        if not (material or "").strip():
            material = learning_material(db)
    except Exception:  # noqa: BLE001 组装语料失败仍可用反馈兜底
        material = ""
    ctx = feedback_context(db)
    parts = [material or "", ctx]
    user_material = "\n".join(x for x in parts if x.strip()) or "（无）"
    llm = DeepSeekClient()
    user = f"当前提示词：\n{current}\n\n作者新增素材/反馈（用于校准语气）：\n{user_material}"
    try:
        content = llm.chat(
            [{"role": "system", "content": OPT_SYSTEM}, {"role": "user", "content": user}],
            temperature=0.3,
            max_tokens=2000,
        )
    except (LLMError, Exception):  # noqa: BLE001 外部失败不破坏当前版
        return None
    if not content or len(content) < 20:
        return None
    return create_candidate(db, key, content, note="AI 自动优化（待启用）")


def auto_optimize_generation(db: Session, material: str = "", threshold: int = 3) -> AiPrompt | None:
    """每累计 threshold 条新素材才产出一次候选（R-022 节流）。

    触发时基于当前所有素材/人设组装语料（material 留空走 learning_material），
    不再只拿最新一条视频做优化。
    """
    from ..models.kv import Kv

    row = db.get(Kv, "generation_import_count")
    if row is None:
        row = Kv(key="generation_import_count", value="0")
        db.add(row)
    cur = int(row.value or "0") + 1
    if cur < threshold:
        row.value = str(cur)
        db.commit()
        return None
    cand = optimize(db, "generation", material)
    if cand is not None:
        row.value = "0"
    else:
        row.value = str(threshold - 1)  # 失败则下一次导入再试
    db.commit()
    return cand
