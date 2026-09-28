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
from . import budget_settings, draft_status, llm_router
from .generation import _persona_context, _style_profile_lines, _style_samples, author_style_context, generation_user_message
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


def model_label(vendor: str, model_id: str) -> str:
    """「厂家标签 · 模型 ID」——全站展示实际模型的唯一口径（R-178）。

    厂家标签复用 `model_settings.VENDORS`（设置页「模型设置」的同一事实源），
    例如 `DeepSeek · deepseek-flash`；厂家未知时退化成只显示模型 ID。
    """
    from .model_settings import VENDORS

    label = (VENDORS.get(vendor or "") or {}).get("label") or ""
    mid = model_id or ""
    if label and mid:
        return f"{label} · {mid}"
    return label or mid or ""


def _llm_model_fields(llm) -> dict:
    """取某个模型客户端**实际出结果**的三元组（R-142/R-178）。"""
    if llm is None:
        return {"used_slot": "", "vendor": "", "model_id": ""}
    return {
        "used_slot": str(getattr(llm, "used_slot", "") or ""),
        "vendor": str(getattr(llm, "used_vendor", "") or ""),
        "model_id": str(getattr(llm, "used_model", "") or ""),
    }


def _add(
    db: Session,
    draft_id: int,
    round_no: int,
    actor: str,
    kind: str,
    content: str,
    *,
    llm=None,
) -> None:
    """写一条留痕。传 `llm` 时同时落库**实际出结果**的模型（R-178）。"""
    db.add(
        DraftDiscussion(
            draft_id=draft_id,
            round=round_no,
            actor=actor,
            kind=kind,
            content=content,
            **_llm_model_fields(llm),
        )
    )
    db.commit()


def _note(db: Session, draft_id: int, round_no: int, text: str) -> None:
    _add(db, draft_id, round_no, "system", "note", text)


def _run_header(db: Session, draft_id: int, gen_slot: dict, critic_slot: dict, rounds: int) -> int:
    """一次讨论的运行头（R-178）：记录**当时配置**的生成方/评审方，返回该行 id 供结束时回填。

    作者切模型后仍能从历史里看出「那一次用的是谁」；结束时会补 `rounds_done/degraded`。
    """
    payload = {
        "gen": _slot_meta(gen_slot),
        "critic": _slot_meta(critic_slot),
        "rounds": rounds,
        "rounds_done": None,
        "degraded": None,
    }
    row = DraftDiscussion(
        draft_id=draft_id,
        round=0,
        actor="system",
        kind="run",
        content=json.dumps(payload, ensure_ascii=False),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row.id


def _finish_run_header(db: Session, header_id: int, *, rounds_done: int, degraded: bool) -> None:
    """讨论结束回填运行头（跑满/中断都留事实）。"""
    row = db.get(DraftDiscussion, header_id)
    if row is None:
        return
    try:
        payload = json.loads(row.content or "{}")
    except json.JSONDecodeError:
        payload = {}
    payload["rounds_done"] = rounds_done
    payload["degraded"] = bool(degraded)
    row.content = json.dumps(payload, ensure_ascii=False)
    db.commit()


def _slot_meta(slot: dict) -> dict:
    """槽位配置（含可展示文案）——运行头用。"""
    vendor = str(slot.get("vendor") or "")
    model_id = str(slot.get("model") or "")
    return {
        "slot": str(slot.get("slot") or ""),
        "vendor": vendor,
        "model": model_id,
        "label": model_label(vendor, model_id),
    }


def _status(
    db: Session,
    draft_id: int,
    text: str,
    *,
    kind: str = "debate",
    actor: str = "",
    phase: str = "",
    round_no: int | None = None,
    rounds: int | None = None,
) -> None:
    """把"当前正在做什么（谁、哪一步、第几轮）"写进草稿 AI 状态（R-173）。

    卡片与讨论 tab 都读它；`actor/phase/round/rounds` 让前端不必解析文案就能画状态条。
    """
    draft_status.set_running(
        db,
        draft_id,
        text,
        kind=kind,
        actor=actor,
        phase=phase,
        round_no=round_no,
        rounds=rounds,
    )


def _clear_status(db: Session, draft_id: int) -> None:
    draft_status.clear(db, draft_id)


# 各步推理预算（R-142 定标 / R-143 起可在「AI 设置 → 推理预算」里改）：
# 默认值见 `budget_settings.SLOTS`，生效值 = max(设置, 厂家下限)，下限有校准护栏测试保护。
# 实测依据：同一份评审提示词的思考量在 2418～8023+ tokens 间波动，预算落在波动区间内
# 就有一半概率被截断成「空正文」→ 误判降级。改默认值前请先重跑
# `tests/test_r142_thinking_budget.py` 头部记录的量测方法。

PLACEHOLDER_SCRIPT = "（双模型讨论生成中…）"
FAILED_SCRIPT = "（生成失败，请重试或删除本稿）"

# R-155：基于原文重新讨论时的初稿提示词（比对标洗稿多产出 tags）
# R-181：改为「参考改写」契约——只借选题与信息线索，不借结构/比喻/句群，必须补作者自己的经历与判断。
SOURCE_REWRITE_SYSTEM = (
    "你是口播脚本代笔。只把给定素材当作**选题与信息线索**，"
    "用作者的人设口吻与表达习惯，写成作者能直接录的原创口播稿。"
    "硬性要求：1) 不逐字抄袭，不复用原文的结构、核心比喻和句群；"
    "2) 必须补入作者自己的经历、判断或案例，观点必须用作者自己的；"
    "3) 语言自然口语，像作者本人对着镜头说话。"
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


def clear_debate_state(db: Session, draft_id: int, reason: str = "") -> None:
    """讨论失败/中断后的收尾（R-134；R-173 起保留「中断」标记）。

    - R-134：占位稿改成可读的失败提示，避免永久「生成中…」；
    - R-173：不再静默删状态，而是记成 `failed`——卡片显示「上次讨论中断（可重新讨论）」，
      但不转圈（前端只对 `running` 画动画）。
    """
    if not draft_id:
        return
    draft_status.set_failed(db, draft_id, reason or "讨论中断", kind="debate")
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
    # R-178：先落「本次讨论的运行头」——记录当时配置的生成方/评审方（切模型后仍可回溯），结束时回填结果
    run_header_id = _run_header(db, draft.id, gen_slot, critic_slot, rounds_total)
    gen_label = _slot_meta(gen_slot)["label"]
    critic_label = _slot_meta(critic_slot)["label"]

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
            f"{author_style_context(db)}\n\n"
            f"【参考素材·只借选题与信息线索，不借结构与措辞】\n"
            f"素材标题：{source_title or topic}\n素材原文：\n{source_text[:4000]}"
        )
        initial_budget = budget_settings.budget_for(db, "rewrite")
    else:
        initial_system = get_prompt("generation", db)
        initial_user = generation_user_message(db, topic)  # R-129：与金样本回放评分同一份输入
        initial_budget = budget_settings.budget_for(db, "debate_initial")
    for name, llm in ((gen, gen_llm), (critic, critic_llm)):
        _status(
            db,
            draft.id,
            f"{gen_label or name} 正在起草初稿…（生成方）",
            actor=name,
            phase="draft",
            rounds=rounds_total,
        )
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
                "llm": llm,
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
    _add(db, draft.id, 0, initial["model"], "draft", draft.script, llm=initial.get("llm"))

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
    break_reason = ""
    for r in range(1, rounds_total + 1):
        _status(
            db,
            draft.id,
            f"{critic_label or critic} 正在评审第 {r}/{rounds_total} 轮…",
            actor=critic,
            phase="critique",
            round_no=r,
            rounds=rounds_total,
        )
        try:
            critique = _chat_once(
                critic_llm,
                critic_system,
                f"当前脚本：\n{latest}",
                0.4,
                budget_settings.budget_for(db, "debate_critique"),
            )
        except Exception as exc:  # noqa: BLE001
            break_reason = f"第 {r}/{rounds_total} 轮评审失败（{str(exc)[:120]}），已按当前稿定稿，可重新讨论"
            _note(db, draft.id, r, f"评审方({critic})失败：{str(exc)[:200]}，以当前稿定稿")
            break
        _add(db, draft.id, r, critic, "critique", critique, llm=critic_llm)
        _status(
            db,
            draft.id,
            f"{gen_label or gen} 正在按评审修订第 {r}/{rounds_total} 轮…",
            actor=gen,
            phase="revise",
            round_no=r,
            rounds=rounds_total,
        )
        try:
            revised = _chat_once(
                gen_llm,
                revise_system,
                f"评审意见：\n{critique}\n\n当前脚本：\n{latest}",
                0.7,
                budget_settings.budget_for(db, "debate_revise"),
            )
        except Exception as exc:  # noqa: BLE001
            break_reason = f"第 {r}/{rounds_total} 轮修订失败（{str(exc)[:120]}），保留上一稿，可重新讨论"
            _note(db, draft.id, r, f"修订方({gen})失败：{str(exc)[:200]}，保留上一稿")
            break
        latest = revised
        draft.script = latest
        db.commit()
        _add(db, draft.id, r, gen, "revise", latest, llm=gen_llm)
        rounds_done = r

    # 3) 生成后自检（R-131）：有问题就带着问题让生成方再改一次（只 1 次，避免成本失控）
    issues, coverage = _self_check(db, draft.script)
    if issues:
        _status(
            db,
            draft.id,
            f"{gen_label or gen} 正在做最后一次收口修订…",
            actor=gen,
            phase="selfcheck",
            rounds=rounds_total,
        )
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
            _add(db, draft.id, rounds_total + 1, gen, "revise", latest, llm=gen_llm)
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
    # R-173：跑满才清状态；中途某轮失败（R-118 允许以当前稿定稿）留下「中断」标记，
    # 让作者看到「讨论 x/y 轮后中断」而不是以为讨论正常结束。
    if break_reason:
        draft_status.set_failed(db, draft.id, break_reason, kind="debate")
    else:
        _clear_status(db, draft.id)
    # R-178：回填运行头（实际跑完几轮 / 是否降级）
    _finish_run_header(db, run_header_id, rounds_done=rounds_done, degraded=degraded)
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
    # R-173：把草稿 id 回写进 payload，供调用方（rewrite_worker）在**异常时**也能标记中断状态
    payload["draft_id"] = draft.id
    # R-178：洗稿同样留运行头 + 每次调用记实际模型
    rewrite_rounds = debate_rounds(db, settings)
    run_header_id = _run_header(db, draft.id, gen_slot, critic_slot, rewrite_rounds)
    gen_label = _slot_meta(gen_slot)["label"]
    critic_label = _slot_meta(critic_slot)["label"]

    # R-157：洗稿前先把素材 ASR 文案记为第一版（洗稿后正文是第二版）
    from .draft_versions import finalize_version

    finalize_version(
        db,
        draft,
        source="ai_rewrite",
        note="洗稿前（素材 ASR）",
        content={
            "title": source_title,
            "script": source_text,
            "tags": json.dumps(source_tags, ensure_ascii=False),
        },
    )

    rewrite_system = (
        "你是口播脚本代笔。用作者的人设口吻与表达习惯，把给定素材改写成作者能直接录的原创口播稿；"
        "不逐字抄袭、保留核心信息与结构，语言自然像本人说话。"
        "只输出 JSON：{\"title\": string, \"cover_text\": string, \"script\": string}；"
        "title 必须是与素材原标题不同的新标题；cover_text 是 3-8 字封面字（与 title 不同）；script 是脚本正文。"
    )
    rewrite_user = f"作者人设：\n{persona}\n\n参考素材标题：{source_title}\n参考素材原文：\n{source_text[:4000]}"

    latest = None
    draft_llm = None
    for name, llm in ((gen, gen_llm), (critic, critic_llm)):
        _status(
            db,
            draft.id,
            f"{gen_label or name.upper()} 正在初稿洗稿…",
            kind="rewrite",
            actor=name,
            phase="draft",
        )
        try:
            data = llm.chat_json(
                [{"role": "system", "content": rewrite_system}, {"role": "user", "content": rewrite_user}],
                temperature=0.7,
                max_tokens=budget_settings.budget_for(db, "rewrite"),  # 洗稿走自己的预算项
                require=("script",),
            )
            latest = str(data.get("script", "")).strip()
            draft_llm = llm
            draft.title = str(data.get("title", "")).strip() or ""
            draft.cover_text = str(data.get("cover_text", "")).strip()
            break
        except Exception as exc:  # noqa: BLE001
            _note(db, draft.id, 0, f"{name} 初稿失败：{str(exc)[:200]}；切换下一位")
    if not latest:
        draft_status.set_failed(db, draft.id, "洗稿初稿生成失败（生成方与评审方都失败）", kind="rewrite")
        raise LLMError("生成方与评审方洗稿初稿均失败")

    # 标题不得与素材原标题一致（模型偶发偷懒时兜底）
    if not draft.title or draft.title.strip() == source_title.strip():
        draft.title = (source_title[:30] + "·口播稿") if source_title else "对标洗稿"
    draft.script = latest
    db.commit()
    _add(db, draft.id, 0, gen, "draft", latest, llm=draft_llm)

    critic_system = (
        "你是脚本评审专家。对照作者人设与语言习惯，指出当前脚本哪些地方不像作者、哪些有 AI 感、"
        "哪些与原文重复或照搬；给出具体可执行的修改建议（简短直给）。\n"
        f"作者人设：\n{persona}"
    )
    revise_system = (
        "你是撰稿模型。根据评审意见，用作者口吻重写整篇口播脚本，只输出脚本正文，"
        "不要解释、不要加标题，保持 1-2 分钟口播长度。"
    )

    rounds = rewrite_rounds
    break_reason = ""

    for r in range(1, rounds + 1):
        _status(
            db,
            draft.id,
            f"{critic_label or critic.upper()} 正在评审第 {r}/{rounds} 轮…",
            kind="rewrite",
            actor=critic,
            phase="critique",
            round_no=r,
            rounds=rounds,
        )
        try:
            critique = _chat_once(
                critic_llm,
                critic_system,
                f"参考原文：\n{source_text[:2000]}\n\n当前脚本：\n{latest}",
                0.4,
                budget_settings.budget_for(db, "debate_critique"),
            )
        except Exception as exc:  # noqa: BLE001
            break_reason = f"第 {r}/{rounds} 轮评审失败（{str(exc)[:120]}），已按当前稿定稿，可重新讨论"
            _note(db, draft.id, r, f"评审方({critic})失败：{str(exc)[:200]}，以当前稿定稿")
            break
        _add(db, draft.id, r, critic, "critique", critique, llm=critic_llm)
        _status(
            db,
            draft.id,
            f"{gen_label or gen.upper()} 正在按评审修订第 {r}/{rounds} 轮…",
            kind="rewrite",
            actor=gen,
            phase="revise",
            round_no=r,
            rounds=rounds,
        )
        try:
            revised = _chat_once(
                gen_llm,
                revise_system,
                f"评审意见：\n{critique}\n\n当前脚本：\n{latest}",
                0.7,
                budget_settings.budget_for(db, "debate_revise"),
            )
        except Exception as exc:  # noqa: BLE001
            break_reason = f"第 {r}/{rounds} 轮修订失败（{str(exc)[:120]}），保留上一稿，可重新讨论"
            _note(db, draft.id, r, f"修订方({gen})失败：{str(exc)[:200]}，保留上一稿")
            break
        latest = revised
        draft.script = latest
        db.commit()
        _add(db, draft.id, r, gen, "revise", latest, llm=gen_llm)

    # R-173：真正跑满才清状态；中途失败（R-118 允许以当前稿定稿）留下「中断」标记，
    # 免得作者以为「只讨论了一轮」是正常结果。
    if break_reason:
        draft_status.set_failed(db, draft.id, break_reason, kind="rewrite")
    else:
        _clear_status(db, draft.id)
    # R-178：回填运行头（实际跑完几轮）
    _finish_run_header(
        db,
        run_header_id,
        rounds_done=rounds if not break_reason else 0,
        degraded=bool(gen_llm.degraded or critic_llm.degraded),
    )
    # R-157：洗稿完成后记第二版
    finalize_version(db, draft, source="ai_rewrite", note="洗稿后")
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

