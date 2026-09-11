"""提示词优化契约（R-129）：按 key 的语料、输出契约、上下文模板、候选自检、长度预算。

设计目标（对应 R-129 P0/P1）：
- **按 key 定制语料**：每个功能只喂它真正相关的真实样本；确实取不到样本时明确报「样本不足」，不拿人设语料硬编。
- **输出契约固定（分层）**：契约段由程序在候选末尾拼接（`contract_for`），优化器改不到；风格段继续由运行时动态注入，
  系统提示词里不允许写死作者传记/红线。
- **候选自检**：`validate_candidate` 校验必需字段、长度预算、以及「是否把事实写死」（红线原文 / 你是 XX 本人 / 作者姓名）。
"""

from __future__ import annotations

import re

from sqlalchemy.orm import Session

from .creator_service import current_creator_id

# ---------- 输出契约（程序固定，候选末尾自动拼接，优化器不得改写） ----------
CONTRACTS: dict[str, str] = {
    "generation": (
        "输出契约（系统固定，不得改动字段名与结构）：\n"
        "只输出 JSON："
        '{"title":"视频标题","cover_text":"封面字","script":"完整口播脚本",'
        '"shells":{"douyin":"抖音发布文案","bilibili":"B站简介","xiaohongshu":"小红书笔记正文"}}'
    ),
    "video_tags": (
        "输出契约（系统固定）：\n"
        "只输出 JSON："
        '{"main_topics":["求职|面试|赚钱|知识|其他"],"is_ad":false,"tags":["标签1","标签2"]}'
        "；main_topics 至少一个；is_ad 表示口播中是否明显推广产品/品牌。"
    ),
    "correct": (
        "输出契约（系统固定）：\n"
        "只输出修正后的转写文本本身，不要 JSON、不要解释、不要增删内容、不要改写成书面语。"
    ),
    "review": (
        "输出契约（系统固定）：\n"
        "只输出 JSON："
        '{"B_attribution":[{"video":"文件名","why":"为什么好/差"}],'
        '"C_next_action":"下一条应该做什么","D_topic_direction":"赛道方向建议"}'
    ),
    "diff": (
        "输出契约（系统固定）：\n"
        "只输出 JSON："
        '{"suggestions":[{"label":"简短标签","description":"具体偏好描述","reason":"依据哪处改写"}]}'
        "；看不出明显偏好时返回空数组。"
    ),
    "persona_init": (
        "输出契约（系统固定）：\n"
        "只输出 JSON："
        '{"tags":[{"label":"简短标签","description":"一句话描述","dimension":"语气/价值观/口头禅/选题/受众/结构/专业/其他",'
        '"evidence":"原文短句"}],"redlines":["作者明确不做的表达或内容"]}'
    ),
    "persona_merge": (
        "输出契约（系统固定）：\n"
        "只输出 JSON："
        '{"tags":[{"label":"...","description":"...","dimension":"...","evidence":"..."}],"redlines":["..."]}'
    ),
    "persona_updates": (
        "输出契约（系统固定）：\n"
        "只输出 JSON："
        '{"tags":[{"label":"...","description":"...","dimension":"...","evidence":"..."}],"redlines":["..."]}'
    ),
    "persona_compare": (
        "输出契约（系统固定）：\n只输出 JSON：{\"score\":0-100,\"reason\":\"一句话说明差距\"}"
    ),
    "chat": (
        "输出契约（系统固定）：\n"
        "用简体中文回答，简洁、口语化、直接；涉及生成/修改/删除的写操作必须先取得作者明确同意才可调用工具执行。"
    ),
}

# 契约/任务语义锚点：候选里必须出现，否则说明格式或任务本身被改坏了
REQUIRED_MARKERS: dict[str, list[str]] = {
    "generation": ["title", "cover_text", "script", "shells", "JSON"],
    "video_tags": ["main_topics", "is_ad", "tags", "JSON"],
    "correct": ["校对", "只输出"],
    "review": ["B_attribution", "C_next_action", "D_topic_direction", "JSON"],
    "diff": ["suggestions", "label", "description", "reason", "JSON"],
    "persona_init": ["tags", "label", "description", "dimension", "evidence", "redlines", "JSON"],
    "persona_merge": ["tags", "label", "description", "dimension", "evidence", "redlines", "JSON"],
    "persona_updates": ["tags", "label", "description", "dimension", "evidence", "redlines", "JSON"],
    "persona_compare": ["score", "reason", "JSON"],
    "chat": ["助手", "同意"],
}

# 上下文模板：告诉优化器运行时 user 消息里已经有什么，避免它重复写进系统提示词
CONTEXT_NOTES: dict[str, str] = {
    "generation": (
        "运行时 user 消息会动态注入：选题、作者人设档案（含维度）、红线清单、金句锚点、语言习惯画像、"
        "AI 腔禁词、风格样本节选、对标风格参考、最佳实践。因此系统提示词里**不要**重复写这些内容，"
        "更不要把作者姓名、学历、收入、经历等具体事实写死。"
    ),
    "video_tags": "运行时 user 消息是**一条**视频的转写稿（无其它上下文）。",
    "correct": "运行时 user 消息是：原始文案（仅供参考，可能不准）+ 待校对转写稿。",
    "review": "运行时 user 消息是当期视频数据摘要（指标/赛道/雷达）。",
    "diff": "运行时 user 消息是 AI 原稿 + 作者改后稿。",
    "persona_init": "运行时 user 消息是作者**一篇**转写稿。",
    "persona_merge": "运行时 user 消息是多篇文案各自提炼结果组成的 JSON 数组。",
    "persona_updates": "运行时 user 消息是「当前人设档案 + 新一篇提炼结果」。",
    "persona_compare": "运行时 user 消息是「A 增量档案 + B 全量档案」。",
    "chat": "运行时由程序提供工具定义与历史消息，系统提示词只负责角色与权限规则。",
}

# 长度预算（可优化段 + 契约段总字数上限）
BUDGETS: dict[str, int] = {
    "generation": 2000,
    "video_tags": 1200,
    "correct": 1000,
    "review": 1500,
    "diff": 1200,
    "persona_init": 1600,
    "persona_merge": 1600,
    "persona_updates": 1600,
    "persona_compare": 1200,
    "chat": 1500,
}
DEFAULT_BUDGET = 1500

_IDENTITY_PATTERNS = (
    re.compile(r"你是\s*[^\s，。；]{0,12}本人"),
    re.compile(r"你是\s*R-?\d+", re.IGNORECASE),
)
_MIN_CONTENT = 20


def contract_for(key: str) -> str:
    return CONTRACTS.get(key, "")


def budget_for(key: str) -> int:
    return BUDGETS.get(key, DEFAULT_BUDGET)


def context_note_for(key: str) -> str:
    return CONTEXT_NOTES.get(key, "")


def _clip(text: str, n: int = 300) -> str:
    return (text or "").strip()[:n]


def _transcript_text(video) -> str:
    tr = getattr(video, "transcript", None)
    if tr is None:
        return ""
    return (tr.corrected_text or tr.transcript_text or "").strip()


def _recent_videos(db: Session, limit: int = 40) -> list:
    from ..models.video import Video

    q = db.query(Video).filter(Video.is_ad.is_(False))
    cid = current_creator_id(db)
    if cid:
        q = q.filter(Video.creator_id == cid)
    return q.order_by(Video.id.desc()).limit(limit).all()


def _archive_text(db: Session) -> str:
    from .persona_profile import current_profile

    prof = current_profile(db, current_creator_id(db))
    lines: list[str] = []
    for t in prof["tags"]:
        dim = f"[{t.get('dimension')}] " if t.get("dimension") else ""
        lines.append(f"- {dim}{t['label']}: {t.get('description', '')}")
    for r in prof["redlines"]:
        lines.append(f"- [红线] {r}")
    return "\n".join(lines)


# ---------- 按 key 的语料 ----------


def _material_generation(db: Session) -> tuple[str, list[str]]:
    from .prompt_service import feedback_context, learning_material

    parts = [learning_material(db), feedback_context(db)]
    text = "\n\n".join(p for p in parts if p and p.strip())
    return text, (["人设+风格画像+加权转写稿", "打分反馈"] if text else [])


def _material_video_tags(db: Session) -> tuple[str, list[str]]:
    from ..models.video import Video

    q = db.query(Video).filter(Video.tags_confirmed.is_(True))
    cid = current_creator_id(db)
    if cid:
        q = q.filter(Video.creator_id == cid)
    lines: list[str] = []
    for v in q.order_by(Video.id.desc()).limit(20).all():
        text = _transcript_text(v)
        if not text:
            continue
        lines.append(
            "【样本】转写稿节选：\n"
            + _clip(text, 260)
            + f"\n真实标注：main_topics={v.main_topics or '[]'}；is_ad={bool(v.is_ad)}；tags={v.tags or '[]'}"
        )
        if len(lines) >= 8:
            break
    return "\n\n".join(lines), ([f"已确认标签素材×{len(lines)}"] if lines else [])


def _material_correct(db: Session) -> tuple[str, list[str]]:
    lines: list[str] = []
    for v in _recent_videos(db, limit=60):
        tr = getattr(v, "transcript", None)
        if tr is None:
            continue
        raw = (tr.transcript_text or "").strip()
        fixed = (tr.corrected_text or "").strip()
        if not raw or not fixed or raw == fixed:
            continue
        lines.append("【原始转写】\n" + _clip(raw, 220) + "\n【校对后】\n" + _clip(fixed, 220))
        if len(lines) >= 6:
            break
    return "\n\n".join(lines), ([f"转写原始/校对对×{len(lines)}"] if lines else [])


def _material_review(db: Session) -> tuple[str, list[str]]:
    from ..models.metrics import ReviewReport

    rows = db.query(ReviewReport).order_by(ReviewReport.id.desc()).limit(2).all()
    lines = [
        f"【历史复盘产出（run_date={r.run_date}）】\n{_clip(r.content, 900)}" for r in rows if r.content
    ]
    return "\n\n".join(lines), ([f"历史复盘报告×{len(lines)}"] if lines else [])


def _material_diff(db: Session) -> tuple[str, list[str]]:
    from ..models.draft import Draft

    q = db.query(Draft)
    cid = current_creator_id(db)
    if cid:
        q = q.filter(Draft.creator_id == cid)
    lines: list[str] = []
    for d in q.order_by(Draft.id.desc()).limit(40).all():
        original = (d.original_script or "").strip()
        edited = (d.script or "").strip()
        if not original or not edited or original == edited:
            continue
        lines.append("【AI 原稿】\n" + _clip(original, 240) + "\n【作者改后】\n" + _clip(edited, 240))
        if len(lines) >= 5:
            break
    return "\n\n".join(lines), ([f"AI 原稿/作者改后对×{len(lines)}"] if lines else [])


def _material_persona(db: Session, *, mode: str) -> tuple[str, list[str]]:
    """persona_init / persona_merge / persona_updates / persona_compare 的语料。"""
    from ..models.kv import Kv
    from ..models.persona import PersonaCheck

    archive = _archive_text(db)
    transcripts = [(v, _transcript_text(v)) for v in _recent_videos(db, limit=20)]
    transcripts = [(v, t) for v, t in transcripts if t][:5]
    blocks: list[str] = []
    sources: list[str] = []
    if archive:
        blocks.append("【当前已确认人设档案】\n" + _clip(archive, 1200))
        sources.append("当前人设档案")
    if mode in ("persona_init", "persona_merge"):
        if transcripts:
            sample = "\n\n".join(f"【代表性转写稿{i + 1}】\n{_clip(t, 240)}" for i, (_v, t) in enumerate(transcripts))
            blocks.append("【作者代表性转写稿（逐篇提取的输入）】\n" + sample)
            sources.append(f"代表性转写稿×{len(transcripts)}")
        if mode == "persona_merge":
            pieces = [
                row.value
                for row in db.query(Kv).filter(Kv.key.like("persona_piece_v1:%")).limit(3).all()
            ]
            if pieces:
                blocks.append("【逐篇提炼结果样例（归纳合并的输入）】\n" + _clip("\n".join(pieces), 1200))
                sources.append("逐篇提炼结果样例")
    elif mode == "persona_updates":
        if transcripts:
            blocks.append("【新一篇转写稿】\n" + _clip(transcripts[0][1], 300))
            sources.append("新一篇转写稿")
    elif mode == "persona_compare":
        check = db.query(PersonaCheck).order_by(PersonaCheck.id.desc()).first()
        if check is not None:
            blocks.append("【最近一次增量 vs 全量校验记录】\n" + _clip(check.detail, 900))
            sources.append("最近一次对齐校验记录")
    if not blocks:
        return "", []
    return "\n\n".join(blocks), sources


def _material_chat(db: Session) -> tuple[str, list[str]]:
    try:
        from .chat_service import TOOLS

        names: list[str] = []
        for tool in TOOLS:
            if not isinstance(tool, dict):
                continue
            fn = tool.get("function")
            if not isinstance(fn, dict):
                continue
            name = str(fn.get("name") or "").strip()
            if name:
                names.append(name)
        text = (
            "作者当前可用的工具：" + "、".join(names) + "\n"
            "权限规则：只读查询可直接执行；生成/修改/删除等写操作必须先取得作者明确同意才可执行。"
        )
        return text, ["工具清单与权限规则"]
    except Exception:  # noqa: BLE001
        return "", []


_BUILDERS = {
    "generation": _material_generation,
    "video_tags": _material_video_tags,
    "correct": _material_correct,
    "review": _material_review,
    "diff": _material_diff,
    "chat": _material_chat,
}


def material_for(key: str, db: Session) -> tuple[str, list[str]]:
    """返回 (语料文本, 来源说明)。语料为空表示该 key 目前没有可用样本。"""
    if key in _BUILDERS:
        return _BUILDERS[key](db)
    if key in ("persona_init", "persona_merge", "persona_updates", "persona_compare"):
        return _material_persona(db, mode=key)
    return "", []


# ---------- 候选自检 ----------


def _forbidden_facts(db: Session | None) -> tuple[list[str], str]:
    if db is None:
        return [], ""
    from ..models.persona import PersonaTag
    from ..models.platform import Creator

    q = db.query(PersonaTag).filter(PersonaTag.status == "confirmed", PersonaTag.category == "redline")
    cid = current_creator_id(db)
    if cid:
        q = q.filter(PersonaTag.creator_id == cid)
    redlines = [t.label for t in q.all() if len(t.label or "") >= 6]
    creator = db.query(Creator).filter(Creator.is_current.is_(True)).first()
    name = (creator.name if creator else "") or ""
    return redlines, name


def validate_candidate(key: str, content: str, db: Session | None = None) -> tuple[bool, str]:
    """候选自检：长度 → 预算 → 契约字段 → 是否写死事实。返回 (是否通过, 失败原因)。"""
    text = (content or "").strip()
    if len(text) < _MIN_CONTENT:
        return False, "候选内容过短"
    budget = budget_for(key)
    if len(text) > budget:
        return False, f"超出长度预算（{len(text)}/{budget} 字）"
    missing = [m for m in REQUIRED_MARKERS.get(key, []) if m not in text]
    if missing:
        return False, "缺少输出契约字段：" + "、".join(missing)
    redlines, name = _forbidden_facts(db)
    for redline in redlines:
        if redline in text:
            return False, f"把红线原文写进了提示词正文（{redline[:15]}…）"
    for pattern in _IDENTITY_PATTERNS:
        if pattern.search(text):
            return False, "出现「你是 XX 本人」式身份写死"
    if name and len(name) >= 2 and f"你是{name}" in text:
        return False, "把作者姓名写死进了提示词"
    return True, ""


def assemble_candidate(key: str, optimizable: str) -> str:
    """把模型产出的「可优化段」与程序固定的契约段拼成完整候选（分层）。"""
    body = (optimizable or "").strip()
    contract = contract_for(key)
    if not contract:
        return body
    return f"{body}\n\n{contract}" if body else contract


def material_summary(sources: list[str]) -> str:
    return "、".join(sources) if sources else "样本不足"


__all__ = [
    "CONTRACTS",
    "REQUIRED_MARKERS",
    "CONTEXT_NOTES",
    "BUDGETS",
    "contract_for",
    "budget_for",
    "context_note_for",
    "material_for",
    "material_summary",
    "validate_candidate",
    "assemble_candidate",
]
