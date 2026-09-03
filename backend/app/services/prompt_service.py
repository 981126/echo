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
    "persona_init": ("app.services.persona", "PERSONA_INIT_SYSTEM", "人设初始化"),
    "video_tags": ("app.services.persona", "VIDEO_TAGS_SYSTEM", "视频预打标"),
    "persona_updates": ("app.services.persona", "PERSONA_UPDATES_SYSTEM", "人设增量建议"),
    "review": ("app.services.review", "REVIEW_SYSTEM", "复盘 ABCD"),
    "diff": ("app.services.diff_analysis", "DIFF_SYSTEM", "改稿差异"),
    "chat": ("app.services.chat_service", "SYSTEM_PROMPT", "AI 对话"),
    "correct": ("app.services.ingest", "CORRECT_SYSTEM", "转写校对"),
}

OPT_SYSTEM = (
    "你是提示词工程专家。基于作者当前提示词、作者素材与反馈，优化该提示词，"
    "使其更贴合作者语气、减少 AI 感、保持原有输出格式约束。"
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


def optimize(db: Session, key: str, material: str = "") -> AiPrompt | None:
    """基于当前启用版 + 素材 + 打分反馈，产出候选新版（不启用）；失败返回 None。"""
    current = get_prompt(key, db)
    if not current:
        return None
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


def auto_optimize_generation(db: Session, material: str, threshold: int = 3) -> AiPrompt | None:
    """每累计 threshold 条新素材才产出一次候选（R-022 节流，防过拟合单条）。"""
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
