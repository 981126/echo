"""双模型讨论生成（R-023；R-139 统一为所有脚本生成的唯一路径）。

流程：按「生成方 / 评审方」两个下拉解析出两个模型槽位 → 生成方出初稿
（失败自动换另一位）→ 交替 N 轮（评审方挑刺 → 生成方修订）→ 最终稿写回草稿。
轮次取「AI 设置」里的讨论轮次（1–10），**手动工作台 / 回炉 / 灵感池一键 / AI 对话 /
提示词自测 / 每日自动生成** 全部走这一条路径。
每轮消息写入 draft_discussions（留痕），前端 tab 可查。
"""

from __future__ import annotations

import json

from sqlalchemy.orm import Session

from ..config import get_settings
from ..models.discussion import DraftDiscussion
from ..models.draft import Draft
from ..models.kv import Kv
from . import budget_settings, llm_router
from .generation import _persona_context, _style_profile_lines, _style_samples, generation_user_message
from .llm import LLMError
from .prompt_service import get_prompt, get_prompt_version
from .creator_service import current_creator_id


def debate_rounds(db: Session, settings=None) -> int:
    """讨论轮次：`app_kv`（界面保存）> `.env` > 默认 5，夹在 1–10。"""
    settings = settings or get_settings()
    row = db.get(Kv, "debate_rounds")
    if row is not None and str(row.value).strip().isdigit():
        rounds = int(str(row.value).strip())
    else:
        rounds = int(getattr(settings, "debate_rounds", 5) or 5)
    return max(1, min(rounds, 10))


def _side_llm(route: llm_router.RouteSnapshot, slot_name: str, feature: str = "generation"):
    """把某个槽位包成「该槽位主用 + 另一个槽位兜底」的客户端（单侧故障不让整篇失败）。"""
    other = "model2" if slot_name == "model1" else "model1"
    return llm_router.RoutedLLM(feature, route, primary=slot_name, fallback=other)


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


# 各步推理预算（R-142 定标 / R-143 起可在「AI 设置 → 推理预算」里改）：
# 默认值见 `budget_settings.SLOTS`，生效值 = max(设置, 厂家下限)，下限有校准护栏测试保护。
# 实测依据：同一份评审提示词的思考量在 2418～8023+ tokens 间波动，预算落在波动区间内
# 就有一半概率被截断成「空正文」→ 误判降级。改默认值前请先重跑
# `tests/test_r142_thinking_budget.py` 头部记录的量测方法。

PLACEHOLDER_SCRIPT = "（双模型讨论生成中…）"
FAILED_SCRIPT = "（生成失败，请重试或删除本稿）"

# R-155：基于原文重新讨论时的初稿提示词（比对标洗稿多产出 tags）
SOURCE_REWRITE_SYSTEM = (
    "你是口播脚本代笔。用作者的人设口吻与表达习惯，把给定素材改写成作者能直接录的原创口播稿；"
    "不逐字抄袭、保留核心信息与结构，语言自然像本人说话。"
    '只输出 JSON：{"title": string, "cover_text": string, "script": string, "tags": string[]}；'
    "title 必须与素材原标题不同；cover_text 是 3-8 字封面字（与 title 不同）；"
    "script 是脚本正文；tags 是 3-6 个内容标签（如 求职/面试/赚钱/知识，可含具体主题词）。"
)


def merge_tags(raw: str, new_tags: list[str]) -> str:
    """R-155：把 AI 新标签并入现有 JSON 标签（去重、保留现有顺序），返回 JSON 文本。"""
    try:
        cur = json.loads(raw or "[]")
    except (TypeError, ValueError):
        cur = []
    out = [str(t) for t in cur if t] if isinstance(cur, list) else []
    for tag in new_tags or []:
        t = str(tag).strip()
        if t and t not in out:
            out.append(t)
    return json.dumps(out, ensure_ascii=False)


def clear_debate_state(db: Session, draft_id: int) -> None:
    """讨论失败/中断后的清理（R-134）：清进度状态；占位稿改成可读的失败提示，避免永久「生成中…」。"""
    if not draft_id:
        return
    _clear_status(db, draft_id)
    draft = db.get(Draft, draft_id)
    if draft is not None and (draft.script or "").strip() == PLACEHOLDER_SCRIPT:
        draft.script = FAILED_SCRIPT
        db.commit()


def _chat_once(llm, system: str, user: str, temperature: float, max_tokens: int) -> str:
    """单次调用；空正文/异常都抛 LLMError（由上层决定是否换人）。"""
    try:
        out = llm.chat(
            [{"role": "system", "content": system}, {"role": "user", "content": user}],
            temperature=temperature,
            max_tokens=max_tokens,
        )
    except LLMError:
        raise
    except Exception as exc:  # noqa: BLE001 超时/网络/HTTP 统一成 LLMError，便于上层处理
        raise LLMError(f"{type(exc).__name__}: {exc}") from exc
    text = (out or "").strip()
    if not text:
        raise LLMError("返回空正文")
    return text


def run_debate(
    db: Session,
    draft: Draft,
    topic: str,
    settings=None,
    source_text: str = "",
    source_title: str = "",
) -> dict:
    """在已有草稿上跑一次完整双模型讨论（所有脚本生成的唯一路径，R-139）。

    R-155：传入 `source_text` 时走「基于原文」讨论——初稿按原文改写成作者口吻，产出
    标题/封面字/正文/标签；写回 `original_script` 供【原文对照】，标签与现有合并去重。
    不传 `source_text` 时行为与原来完全一致（按选题生成）。

    返回 {draft_id, title, models, fallback, rounds, degraded}，其中 origin 信息用于
    写入 `Draft.quality`，让作者一眼看出这篇稿子由哪两个模型产出、是否降级。
    """
    from .generation import _self_check

    settings = settings or get_settings()
    route = llm_router.snapshot(db)
    gen_slot, critic_slot = route.generation_pair()
    gen = gen_slot["slot"]
    critic = critic_slot["slot"]
    gen_llm = _side_llm(route, gen)
    critic_llm = _side_llm(route, critic)
    rounds_total = debate_rounds(db, settings)

    ctx = _context(db, topic)
    persona_text = "\n".join(f"- {t}" for t in ctx["tags"] or ["（暂无）"]) or "（暂无）"
    red_text = "\n".join(f"- {r}" for r in ctx["redlines"] or ["（无）"]) or "（无）"
    samples_text = "\n\n".join(f"--- 样本{i+1} ---\n{s[:300]}" for i, s in enumerate(ctx["samples"]))
    style_note = f"{ctx['profile']}\n\n风格样本：\n{samples_text or '（暂无样本）'}"

    # 1) 初稿：优先生成方，失败自动换评审方（降级留痕）
    initial = None
    if source_text:
        # R-155：基于原文讨论——原文可能是洗稿素材 ASR 文案（original_script）或自建稿正文
        if db.query(DraftDiscussion).filter(DraftDiscussion.draft_id == draft.id).count() > 0:
            _note(db, draft.id, 0, "—— 重新讨论（基于原文）——")
        initial_system = SOURCE_REWRITE_SYSTEM
        initial_user = (
            f"作者人设：\n{persona_text}\n\n参考素材标题：{source_title or topic}\n"
            f"参考素材原文：\n{source_text[:4000]}"
        )
        initial_budget = budget_settings.budget_for(db, "rewrite")
    else:
        initial_system = get_prompt("generation", db)
        initial_user = generation_user_message(db, topic)  # R-129：与金样本回放评分同一份输入
        initial_budget = budget_settings.budget_for(db, "debate_initial")
    for name, llm in ((gen, gen_llm), (critic, critic_llm)):
        _status(db, draft.id, f"{name} 正在起草初稿…（生成方 {gen}）")
        try:
            data = llm.chat_json(
                [
                    {"role": "system", "content": initial_system},
                    {"role": "user", "content": initial_user},
                ],
                temperature=0.8 if not source_text else 0.7,
                max_tokens=initial_budget,
                require=("script",),
            )
            initial = {
                # R-142：留痕要记**实际出结果**的槽位（内部降级后 name 会与事实不符）
                "model": getattr(llm, "used_slot", None) or name,
                "title": str(data.get("title", "")).strip() or topic,
                "cover_text": str(data.get("cover_text", "")).strip(),
                "script": str(data.get("script", "")).strip(),
                "shells": data.get("shells") if isinstance(data.get("shells"), dict) else {},
                "tags": [str(t).strip() for t in (data.get("tags") or []) if str(t).strip()] if source_text else [],
            }
            break
        except Exception as exc:  # noqa: BLE001
            _note(db, draft.id, 0, f"{name} 初稿失败：{str(exc)[:200]}；切换下一位")
    if not initial:
        raise LLMError("生成方与评审方初稿生成均失败")

    draft.title = initial["title"]
    draft.cover_text = initial["cover_text"]
    draft.script = initial["script"] or topic
    if initial["shells"]:
        draft.platform_shells = json.dumps(initial["shells"], ensure_ascii=False)
    if source_text:
        draft.original_script = source_text  # R-155：原文对照展示「原文 vs 讨论后」
        draft.tags = merge_tags(draft.tags, initial["tags"])  # R-155：标签合并去重
    db.commit()
    _add(db, draft.id, 0, initial["model"], "draft", draft.script)

    # 2) N 轮讨论：评审方挑刺 → 生成方修订
    critic_system = (
        "你是脚本评审专家。请对照作者人设与语言习惯，指出当前脚本哪些地方不像作者、"
        "哪些有 AI 感，并给出具体可执行的修改建议（每轮简短、直给）。\n"
        f"作者人设：\n{persona_text}\n红线（不得违反）：\n{red_text}\n作者语言习惯：\n{ctx['profile']}"
    )
    if source_text:
        critic_system += f"\n参考原文（检查是否照搬/重复）：\n{source_text[:1500]}"
    revise_system = (
        "你是撰稿模型。根据评审意见，用作者的口吻重写整篇口播脚本，"
        "只输出脚本正文，不要解释、不要加标题。保持 1-2 分钟口播长度。\n"
        f"作者语言习惯（必须模仿）：\n{style_note}"
    )

    latest = draft.script
    rounds_done = 0
    for r in range(1, rounds_total + 1):
        _status(db, draft.id, f"{critic} 正在评审第 {r}/{rounds_total} 轮…")
        try:
            critique = _chat_once(
                critic_llm,
                critic_system,
                f"当前脚本：\n{latest}",
                0.4,
                budget_settings.budget_for(db, "debate_critique"),
            )
        except Exception as exc:  # noqa: BLE001
            _note(db, draft.id, r, f"评审方({critic})失败：{str(exc)[:200]}，以当前稿定稿")
            break
        _add(db, draft.id, r, critic, "critique", critique)
        _status(db, draft.id, f"{gen} 正在按评审修订第 {r}/{rounds_total} 轮…")
        try:
            revised = _chat_once(
                gen_llm,
                revise_system,
                f"评审意见：\n{critique}\n\n当前脚本：\n{latest}",
                0.7,
                budget_settings.budget_for(db, "debate_revise"),
            )
        except Exception as exc:  # noqa: BLE001
            _note(db, draft.id, r, f"修订方({gen})失败：{str(exc)[:200]}，保留上一稿")
            break
        latest = revised
        draft.script = latest
        db.commit()
        _add(db, draft.id, r, gen, "revise", latest)
        rounds_done = r

    # 3) 生成后自检（R-131）：有问题就带着问题让生成方再改一次（只 1 次，避免成本失控）
    issues, coverage = _self_check(db, draft.script)
    if issues:
        _status(db, draft.id, "正在按自检问题做最后一次收口修订…")
        fix_user = (
            f"这是你自己刚写的脚本：\n{latest}\n\n"
            "以下几处不符合作者风格或踩了红线，请整篇重写并避免：\n"
            + "\n".join(f"- {i}" for i in issues)
            + f"\n\n作者语言习惯（必须模仿）：\n{style_note}"
        )
        try:
            fixed = _chat_once(
                gen_llm, revise_system, fix_user, 0.6, budget_settings.budget_for(db, "debate_revise")
            )
            latest = fixed
            draft.script = latest
            db.commit()
            _add(db, draft.id, rounds_total + 1, gen, "revise", latest)
            issues, coverage = _self_check(db, draft.script)
        except Exception as exc:  # noqa: BLE001 收口失败保留原稿
            _note(db, draft.id, rounds_total + 1, f"自检收口修订失败：{str(exc)[:200]}，保留当前稿")

    degraded = bool(gen_llm.degraded or critic_llm.degraded or initial["model"] != gen)
    draft.quality = json.dumps(
        {
            "models": {"gen": f"{gen}({gen_slot['vendor']}/{gen_slot['model']})", "critic": f"{critic}({critic_slot['vendor']}/{critic_slot['model']})"},
            "used": {"gen": gen_llm.routing()["used"], "critic": critic_llm.routing()["used"]},
            "fallback": degraded,
            "rounds": rounds_total,
            "rounds_done": rounds_done,
            "issues": issues,
            "passed": not issues,
            "style_coverage": coverage,
            "sole_model": gen == critic,
        },
        ensure_ascii=False,
    )
    draft.script = latest
    db.commit()
    _clear_status(db, draft.id)
    return {
        "draft_id": draft.id,
        "title": draft.title,
        "models": {"gen": gen, "critic": critic},
        "fallback": degraded,
        "rounds": rounds_total,
        "tags": json.loads(draft.tags or "[]") if source_text else [],
    }


def run_debate_draft(db: Session, payload: dict) -> dict:
    """后台任务体：payload {draft_id, topic}（工作台双模型讨论生成）。"""
    draft = db.get(Draft, int(payload.get("draft_id") or 0))
    if draft is None:
        raise LLMError("草稿不存在")
    if draft.creator_id is None:
        draft.creator_id = current_creator_id(db)  # 兜底：老占位稿无归属时补当前主博主
    if not draft.prompt_version:
        draft.prompt_version = get_prompt_version("generation", db)  # R-129：按提示词版本归因
    topic = str(payload.get("topic", "")).strip() or draft.title or "今日话题"
    return run_debate(db, draft, topic)


def run_rewrite_debate(db: Session, payload: dict) -> dict:
    """对标洗稿双模型多轮讨论（R-118）。

    payload: {owner_id, key, title, text, benchmark_name, post_id, work_id}
    初稿先由生成方按原文改写，随后评审方/生成方交替多轮打磨；
    每轮写 draft_discussions 留痕，最终稿落 drafts（含 original_script / source_ref）。
    """
    from ..models.platform import Creator
    from .benchmark import persona_lines

    owner = db.get(Creator, int(payload.get("owner_id") or 0))
    if owner is None:
        raise LLMError("主博主不存在")
    source_title = str(payload.get("title") or "").strip() or "对标洗稿"
    source_text = str(payload.get("text") or "")
    if not source_text.strip():
        raise LLMError("该素材还没有可用文案（先转写补齐）")

    source_tags = [str(t) for t in (payload.get("tags") or []) if t]
    source_ref = {
        "kind": "benchmark",
        "key": payload.get("key") or "",
        "source_title": source_title,
        "benchmark_name": payload.get("benchmark_name") or "",
        "post_id": payload.get("post_id"),
        "work_id": payload.get("work_id"),
        "tags": source_tags,
    }

    persona = "\n".join(persona_lines(db, owner)) or "（尚未建人设档案）"
    settings = get_settings()
    route = llm_router.snapshot(db)
    gen_slot, critic_slot = route.generation_pair()
    gen, critic = gen_slot["slot"], critic_slot["slot"]
    gen_llm = _side_llm(route, gen)
    critic_llm = _side_llm(route, critic)

    from .persona_profile import current_persona_version

    draft = Draft(
        creator_id=owner.id,
        title="",
        cover_text="",
        script="",
        original_script=source_text,
        source="ai",
        status="draft",
        source_ref=json.dumps(source_ref, ensure_ascii=False),
        tags=json.dumps(source_tags, ensure_ascii=False),
        persona_version=current_persona_version(db, owner.id),  # R-130：人设变化可控
    )
    db.add(draft)
    db.commit()
    db.refresh(draft)

    rewrite_system = (
        "你是口播脚本代笔。用作者的人设口吻与表达习惯，把给定素材改写成作者能直接录的原创口播稿；"
        "不逐字抄袭、保留核心信息与结构，语言自然像本人说话。"
        "只输出 JSON：{\"title\": string, \"cover_text\": string, \"script\": string}；"
        "title 必须是与素材原标题不同的新标题；cover_text 是 3-8 字封面字（与 title 不同）；script 是脚本正文。"
    )
    rewrite_user = f"作者人设：\n{persona}\n\n参考素材标题：{source_title}\n参考素材原文：\n{source_text[:4000]}"

    latest = None
    for name, llm in ((gen, gen_llm), (critic, critic_llm)):
        _status(db, draft.id, f"{name.upper()} 正在初稿洗稿…")
        try:
            data = llm.chat_json(
                [{"role": "system", "content": rewrite_system}, {"role": "user", "content": rewrite_user}],
                temperature=0.7,
                max_tokens=budget_settings.budget_for(db, "rewrite"),  # 洗稿走自己的预算项
                require=("script",),
            )
            latest = str(data.get("script", "")).strip()
            draft.title = str(data.get("title", "")).strip() or ""
            draft.cover_text = str(data.get("cover_text", "")).strip()
            break
        except Exception as exc:  # noqa: BLE001
            _note(db, draft.id, 0, f"{name} 初稿失败：{str(exc)[:200]}；切换下一位")
    if not latest:
        _clear_status(db, draft.id)
        raise LLMError("生成方与评审方洗稿初稿均失败")

    # 标题不得与素材原标题一致（模型偶发偷懒时兜底）
    if not draft.title or draft.title.strip() == source_title.strip():
        draft.title = (source_title[:30] + "·口播稿") if source_title else "对标洗稿"
    draft.script = latest
    db.commit()
    _add(db, draft.id, 0, gen, "draft", latest)

    critic_system = (
        "你是脚本评审专家。对照作者人设与语言习惯，指出当前脚本哪些地方不像作者、哪些有 AI 感、"
        "哪些与原文重复或照搬；给出具体可执行的修改建议（简短直给）。\n"
        f"作者人设：\n{persona}"
    )
    revise_system = (
        "你是撰稿模型。根据评审意见，用作者口吻重写整篇口播脚本，只输出脚本正文，"
        "不要解释、不要加标题，保持 1-2 分钟口播长度。"
    )

    rounds = debate_rounds(db, settings)

    for r in range(1, rounds + 1):
        _status(db, draft.id, f"{critic.upper()} 正在评审第 {r}/{rounds} 轮…")
        try:
            critique = _chat_once(
                critic_llm,
                critic_system,
                f"参考原文：\n{source_text[:2000]}\n\n当前脚本：\n{latest}",
                0.4,
                budget_settings.budget_for(db, "debate_critique"),
            )
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
                budget_settings.budget_for(db, "debate_revise"),
            )
        except Exception as exc:  # noqa: BLE001
            _note(db, draft.id, r, f"修订方({gen})失败：{str(exc)[:200]}，保留上一稿")
            break
        latest = revised
        draft.script = latest
        db.commit()
        _add(db, draft.id, r, gen, "revise", latest)

    _clear_status(db, draft.id)
    return {
        "draft_id": draft.id,
        "title": draft.title,
        "cover_text": draft.cover_text,
        "script": latest,
        "original_script": source_text,
        "source_ref": source_ref,
        "benchmark_name": payload.get("benchmark_name") or "",
        "tags": source_tags,
    }

