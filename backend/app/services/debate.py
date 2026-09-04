"""双模型讨论生成（R-023）。

流程：选择 生成方 + 评审方 → 生成方出初稿 → 交替 5 轮
（评审方按人设/素材挑刺 → 生成方修订）→ 最终稿写回草稿。
每轮消息写入 draft_discussions（留痕），前端 tab 可查。
任一方失败自动降级：单模型也可完成；两者都失败抛 LLMError。
"""

from __future__ import annotations

import random

from sqlalchemy.orm import Session

from ..config import get_settings
from ..models.discussion import DraftDiscussion
from ..models.draft import Draft
from ..models.kv import Kv
from .generation import _persona_context, _style_profile_lines, _style_samples
from .llm import LLMError, get_llm
from .prompt_service import get_prompt

MODELS = ["deepseek", "kimi"]


def choose_models(db: Session) -> tuple[str, str]:
    settings = get_settings()
    row = db.get(Kv, "generation_model")
    mode = (row.value if row else "") or settings.generation_model
    if mode == "kimi":
        return "kimi", "deepseek"
    if mode == "random":
        gen = random.choice(MODELS)
        return gen, "kimi" if gen == "deepseek" else "deepseek"
    if mode == "alternate":
        c = db.get(Kv, "alt_count")
        n = int(c.value) if c else 0
        if c:
            c.value = str(n + 1)
        else:
            db.add(Kv(key="alt_count", value="1"))
        gen = MODELS[n % 2]
        return gen, "kimi" if gen == "deepseek" else "deepseek"
    return "deepseek", "kimi"


def _context(db: Session, topic: str) -> dict:
    persona = _persona_context(db)
    return {
        "topic": topic,
        "tags": persona["tags"],
        "redlines": persona["redlines"],
        "profile": _style_profile_lines(db),
        "samples": _style_samples(db, topic, k=3),
    }


def _add(db: Session, draft_id: int, round_no: int, actor: str, kind: str, content: str) -> None:
    db.add(DraftDiscussion(draft_id=draft_id, round=round_no, actor=actor, kind=kind, content=content))
    db.commit()


def run_debate_draft(db: Session, payload: dict) -> dict:
    """后台任务体：payload {draft_id, topic}。"""
    draft = db.get(Draft, int(payload.get("draft_id") or 0))
    if draft is None:
        raise LLMError("草稿不存在")
    topic = str(payload.get("topic", "")).strip() or draft.title or "今日话题"
    ctx = _context(db, topic)

    persona_text = "\n".join(f"- {t}" for t in ctx["tags"] or ["（暂无）"]) or "（暂无）"
    red_text = "\n".join(f"- {r}" for r in ctx["redlines"] or ["（无）"]) or "（无）"
    samples_text = "\n\n".join(f"--- 样本{i+1} ---\n{s[:300]}" for i, s in enumerate(ctx["samples"]))
    style_note = f"{ctx['profile']}\n\n风格样本：\n{samples_text or '（暂无样本）'}"

    settings = get_settings()
    gen, critic = choose_models(db)
    gen_llm = get_llm(gen, settings)
    critic_llm = get_llm(critic, settings)

    # 1) 初稿：优先生成方，失败换评审方（降级）
    initial = None
    for name, llm in ((gen, gen_llm), (critic, critic_llm)):
        try:
            data = llm.chat_json(
                [
                    {"role": "system", "content": get_prompt("generation", db)},
                    {
                        "role": "user",
                        "content": (
                            f"选题：{topic}\n\n作者人设：\n{persona_text}\n\n"
                            f"红线（不要违反）：\n{red_text}\n\n作者语言习惯（必须模仿）：\n{style_note}"
                        ),
                    },
                ],
                temperature=0.8,
                max_tokens=2500,
            )
            initial = {
                "model": name,
                "title": str(data.get("title", "")).strip() or topic,
                "cover_text": str(data.get("cover_text", "")).strip(),
                "script": str(data.get("script", "")).strip(),
            }
            break
        except Exception:
            continue
    if not initial:
        raise LLMError("DeepSeek 与 Kimi 初稿生成均失败")

    draft.title = initial["title"]
    draft.cover_text = initial["cover_text"]
    draft.script = initial["script"] or topic
    db.commit()
    _add(db, draft.id, 0, initial["model"], "draft", draft.script)

    # 2) 5 轮讨论：评审方挑刺 → 生成方修订
    critic_system = (
        "你是脚本评审专家。请对照作者人设与语言习惯，指出当前脚本哪些地方不像作者、"
        "哪些有 AI 感，并给出具体可执行的修改建议（每轮简短、直给）。\n"
        f"作者人设：\n{persona_text}\n红线（不得违反）：\n{red_text}\n作者语言习惯：\n{ctx['profile']}"
    )
    revise_system = (
        "你是撰稿模型。根据评审意见，用作者的口吻重写整篇口播脚本，"
        "只输出脚本正文，不要解释、不要加标题。保持 1-2 分钟口播长度。\n"
        f"作者语言习惯（必须模仿）：\n{style_note}"
    )

    rounds = max(int(getattr(settings, "debate_rounds", 5) or 0), 1)
    latest = draft.script
    for r in range(1, rounds + 1):
        try:
            critique = critic_llm.chat(
                [
                    {"role": "system", "content": critic_system},
                    {"role": "user", "content": f"当前脚本：\n{latest}"},
                ],
                temperature=0.4,
                max_tokens=1200,
            )
        except Exception:
            break  # 评审方不可用：以当前稿定稿
        if not critique.strip():
            break
        _add(db, draft.id, r, critic, "critique", critique.strip())
        try:
            revised = gen_llm.chat(
                [
                    {"role": "system", "content": revise_system},
                    {
                        "role": "user",
                        "content": f"评审意见：\n{critique}\n\n当前脚本：\n{latest}",
                    },
                ],
                temperature=0.7,
                max_tokens=3000,
            )
        except Exception:
            break
        if not revised.strip():
            break
        latest = revised.strip()
        draft.script = latest
        db.commit()
        _add(db, draft.id, r, gen, "revise", latest)

    return {"draft_id": draft.id, "title": draft.title}
