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
from .creator_service import current_creator_id

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


def _note(db: Session, draft_id: int, round_no: int, text: str) -> None:
    _add(db, draft_id, round_no, "system", "note", text)


def _status(db: Session, draft_id: int, text: str) -> None:
    """把"当前正在做什么"写入 Kv，供前端讨论页显示思考中状态。"""
    key = f"debate:{draft_id}"
    row = db.get(Kv, key)
    if row is None:
        db.add(Kv(key=key, value=text))
    else:
        row.value = text
    db.commit()


def _clear_status(db: Session, draft_id: int) -> None:
    row = db.get(Kv, f"debate:{draft_id}")
    if row is not None:
        db.delete(row)
        db.commit()


def _chat_once(llm, system: str, user: str, temperature: float, max_tokens: int) -> str:
    """单次调用 + 一次瞬时失败重试；仍失败抛 LLMError。"""
    from .llm import LLMError

    last: Exception | None = None
    for _ in range(2):
        try:
            out = llm.chat(
                [{"role": "system", "content": system}, {"role": "user", "content": user}],
                temperature=temperature,
                max_tokens=max_tokens,
            )
            if out and out.strip():
                return out.strip()
        except LLMError as e:
            last = e
        except Exception as e:  # noqa: BLE001
            last = e
    raise LLMError(str(last) or "调用失败/返回为空")


def run_debate_draft(db: Session, payload: dict) -> dict:
    """后台任务体：payload {draft_id, topic}。"""
    draft = db.get(Draft, int(payload.get("draft_id") or 0))
    if draft is None:
        raise LLMError("草稿不存在")
    if draft.creator_id is None:
        draft.creator_id = current_creator_id(db)  # 兜底：老占位稿无归属时补当前主博主
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

    # 1) 初稿：优先生成方，失败换评审方（降级，且失败留痕）
    initial = None
    initial_system = get_prompt("generation", db)
    initial_user = (
        f"选题：{topic}\n\n作者人设：\n{persona_text}\n\n"
        f"红线（不要违反）：\n{red_text}\n\n作者语言习惯（必须模仿）：\n{style_note}"
    )
    for name, llm in ((gen, gen_llm), (critic, critic_llm)):
        _status(db, draft.id, f"{name.upper()} 正在起草初稿…（生成方 {gen.upper()}）")
        try:
            data = llm.chat_json(
                [
                    {"role": "system", "content": initial_system},
                    {"role": "user", "content": initial_user},
                ],
                temperature=0.8,
                max_tokens=3200,
            )
            initial = {
                "model": name,
                "title": str(data.get("title", "")).strip() or topic,
                "cover_text": str(data.get("cover_text", "")).strip(),
                "script": str(data.get("script", "")).strip(),
            }
            break
        except Exception as exc:  # noqa: BLE001
            _note(db, draft.id, 0, f"{name} 初稿失败：{str(exc)[:200]}；切换下一位")
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

    kv_rounds = db.get(Kv, "debate_rounds")
    rounds = int(kv_rounds.value) if kv_rounds and str(kv_rounds.value).isdigit() else int(
        getattr(settings, "debate_rounds", 5) or 5
    )
    rounds = max(1, min(int(rounds), 10))
    latest = draft.script
    for r in range(1, rounds + 1):
        _status(db, draft.id, f"{critic.upper()} 正在评审第 {r}/{rounds} 轮…")
        try:
            critique = _chat_once(critic_llm, critic_system, f"当前脚本：\n{latest}", 0.4, 3000)
        except Exception as exc:  # noqa: BLE001
            _note(db, draft.id, r, f"评审方({critic})失败：{str(exc)[:200]}，以当前稿定稿")
            break
        _add(db, draft.id, r, critic, "critique", critique)
        _status(db, draft.id, f"{gen.upper()} 正在按评审修订第 {r}/{rounds} 轮…")
        try:
            revised = _chat_once(
                gen_llm,
                revise_system,
                f"评审意见：\n{critique}\n\n当前脚本：\n{latest}",
                0.7,
                4200,
            )
        except Exception as exc:  # noqa: BLE001
            _note(db, draft.id, r, f"修订方({gen})失败：{str(exc)[:200]}，保留上一稿")
            break
        latest = revised
        draft.script = latest
        db.commit()
        _add(db, draft.id, r, gen, "revise", latest)

    _clear_status(db, draft.id)
    return {"draft_id": draft.id, "title": draft.title}
