"""双模型讨论生成（R-023；R-139 统一为所有脚本生成的唯一路径）。

流程：按「生成方 / 评审方」两个下拉解析出两个模型槽位 → 生成方出初稿
（失败自动换另一位）→ 交替 N 轮（评审方挑刺 → 生成方修订）→ 最终稿写回草稿。
轮次取「AI 设置」里的讨论轮次（1–10），**手动工作台 / 回炉 / 灵感池一键 / AI 对话 /
提示词自测 / 每日自动生成** 全部走这一条路径。
每轮消息写入 draft_discussions（留痕），前端 tab 可查。
"""

from __future__ import annotations

import json
import re
from concurrent.futures import ThreadPoolExecutor

from sqlalchemy.orm import Session

from ..config import get_settings
from ..core.log import get_logger
from ..models.discussion import DraftDiscussion
from ..models.draft import Draft
from ..models.kv import Kv
from . import budget_settings, draft_status, llm_router
from .generation import _persona_context, _style_profile_lines, _style_samples, author_style_context, generation_user_message
from .llm import LLMError
from .prompt_service import get_prompt, get_prompt_version
from .creator_service import current_creator_id

log = get_logger("debate")


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


def _persona_brief(ctx: dict, profile: str = "") -> str:
    """R-233：给「生成方选文」的紧凑人设（标签 + 红线 + 语言风格），不塞全文上下文。"""
    tags = "\n".join(f"- {t}" for t in (ctx.get("tags") or [])[:16]) or "（暂无）"
    redlines = "\n".join(f"- {r}" for r in (ctx.get("redlines") or [])[:8]) or "（无）"
    style = (profile or ctx.get("profile") or "")[:800]
    return f"标签：\n{tags}\n红线：\n{redlines}\n语言风格：{style or '（暂无）'}"


def _retrieve_station_side(topic: str, creator_id: int | None) -> tuple[dict, dict]:
    """R-241：站内素材检索（只读，独立 Session，供与联网检索并发）。

    返回 `(station, station_meta)`；失败降级为空证据（站内素材是增强项，不阻断生成）。
    """
    from ..db import SessionLocal
    from .station_evidence import meta as station_meta
    from .station_evidence import retrieve_station

    s = SessionLocal()
    try:
        station = retrieve_station(s, topic, creator_id=creator_id)
        return station, station_meta(station)
    except Exception as exc:  # noqa: BLE001 站内素材检索失败不阻断生成
        log.warning("站内素材检索失败（降级为空证据）：%s", str(exc)[:160])
        empty = {"author": [], "benchmark": [], "block": ""}
        return empty, station_meta(empty)
    finally:
        s.close()


def _evidence_and_station(
    db: Session,
    *,
    topic: str,
    material: str,
    draft_id: int,
    creator_id: int | None,
    persona: str,
    picker,
) -> tuple[dict, dict, dict]:
    """R-241：联网证据与站内证据**并发**获取。

    - 站内检索在独立只读 Session 线程里跑（`_retrieve_station_side`）；
    - 联网检索走当前 Session（内部写 web_search_logs + 证据缓存），在主线程执行；
    - 两者都完成后再由调用方按「联网 block → 站内 block」原顺序拼接。
    """
    from .evidence import gather_online_cached

    station_exec = ThreadPoolExecutor(max_workers=1, thread_name_prefix="echo-station")
    station_future = station_exec.submit(_retrieve_station_side, topic, creator_id)
    try:
        ev = gather_online_cached(
            db,
            topic,
            material=material,
            draft_id=draft_id,
            creator_id=creator_id,
            persona=persona,
            picker=picker,
        )
        station, station_meta = station_future.result()
    finally:
        station_exec.shutdown(wait=False, cancel_futures=True)
    return ev, station, station_meta


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


def mark_latest_run_reverted(db: Session, draft_id: int) -> bool:
    """R-209：作者回退跨过了 AI 讨论结果——把最近一次讨论运行头回填 ``reverted: true``。

    「讨论后被作者改回旧版」是双模型讨论最强的负反馈，留在运行头上，
    以后做生成方×评审方组合效果统计时可直接取用。
    """
    row = (
        db.query(DraftDiscussion)
        .filter(DraftDiscussion.draft_id == draft_id, DraftDiscussion.kind == "run")
        .order_by(DraftDiscussion.id.desc())
        .first()
    )
    if row is None:
        return False
    try:
        payload = json.loads(row.content or "{}")
    except json.JSONDecodeError:
        payload = {}
    if payload.get("reverted"):
        return False
    payload["reverted"] = True
    row.content = json.dumps(payload, ensure_ascii=False)
    db.commit()
    return True


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

# R-228：评审/修订共用的事实硬规则——评审与修订每轮都要看到证据块，且都不得替作者编造经历。
# 根因（draft 128 留痕）：评审在"修改建议"里发明第一人称素材（公司倒闭欠薪、投递转化数字），
# 生成方照填，终稿全是作者没说过的话；作者 insight 反复毙此方向但机制未堵。
NO_FABRICATION_RULE = (
    "\n\n事实硬规则（评审与修订都必须遵守）：文中一切具体事实（数字/公司/人名/作者亲身经历）"
    "只能来自注入的【联网事实素材】/【站内真实素材】或作者上下文（人设/ASR 转写/范本/金句锚点）"
    "里已有的内容；**严禁替作者发明第一人称经历、具体数字、公司/人名**。"
    "论据缺素材时，建议写「这里需要作者补充真实经历」，不要编一个填上。"
)

def _with_evidence(system: str, evidence_block: str) -> str:
    """证据块拼进 system prompt——每轮 critique/revise 调用都随消息可见（R-228）。"""
    if not evidence_block:
        return system
    return system + f"\n\n可引用的事实素材（评审与修订都只能用这里的事实）：\n{evidence_block}"

# R-155：基于原文重新讨论时的初稿提示词（比对标洗稿多产出 tags）
# R-181：改为「参考改写」契约——只借选题与信息线索，不借结构/比喻/句群，必须补作者自己的经历与判断。
SOURCE_REWRITE_SYSTEM = (
    "你是口播脚本代笔。只把给定素材当作**选题与信息线索**，"
    "用作者的人设口吻与表达习惯，写成作者能直接录的原创口播稿。"
    "硬性要求：1) 不逐字抄袭，不复用原文的结构、核心比喻和句群；"
    "2) 必须补入作者自己的经历、判断或案例，观点必须用作者自己的"
    "（只能用作者上下文与注入证据里已有的内容，严禁编造；缺素材就标【需作者补充】）；"
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
    mode: str = "",
    query_source: str = "",
) -> dict:
    """在已有草稿上跑一次完整双模型讨论（所有脚本生成的唯一路径，R-139）。

    R-155：传入 `source_text` 时走「基于原文」讨论——初稿按原文改写成作者口吻，产出
    标题/封面字/正文/标签；写回 `original_script` 供【原文对照】，标签与现有合并去重。
    不传 `source_text` 时行为与原来完全一致（按选题生成）。

    返回 {draft_id, title, models, fallback, rounds, degraded}，其中 origin 信息用于
    写入 `Draft.quality`，让作者一眼看出这篇稿子由哪两个模型产出、是否降级。
    """
    from .generation import _self_check, style_diagnostics

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

    # R-227：联网事实证据（query = 选题 + 该入口能拿到的最具体文本；无 key/失败静默）
    # R-233：豆包 + DeepSeek 双源检索/正文补齐/去营销，并由生成方按当前主博主人设选文
    # R-241：证据结果走 TTL 缓存（命中跳过选文 LLM）；站内检索与联网检索并发（见 _evidence_and_station）
    from .evidence import mark_logs_used, public_items, resolve_used

    ctx = _context(db, topic)  # R-233：选文要先拿到人设（原在证据之后）
    persona_text = "\n".join(f"- {t}" for t in ctx["tags"] or ["（暂无）"]) or "（暂无）"
    red_text = "\n".join(f"- {r}" for r in ctx["redlines"] or ["（无）"]) or "（无）"
    samples_text = "\n\n".join(f"--- 样本{i+1} ---\n{s[:300]}" for i, s in enumerate(ctx["samples"]))
    style_note = f"{ctx['profile']}\n\n风格样本：\n{samples_text or '（暂无样本）'}"

    # R-233：双源检索 + 抓正文 + 选文可能耗时 10~30s，先把状态亮出来（前端轮询可见）
    _status(
        db,
        draft.id,
        "正在联网检索参考（豆包 + DeepSeek），随后由生成方按人设选文…",
        actor=gen,
        phase="evidence",
        rounds=rounds_total,
    )
    ev, station, station_meta = _evidence_and_station(
        db,
        topic=topic,
        material=source_text or query_source,
        draft_id=draft.id,
        creator_id=draft.creator_id,
        persona=_persona_brief(ctx),
        picker=gen_llm,
    )
    evidence_block = "\n\n".join(x for x in (ev.get("block") or "", station.get("block") or "") if x)
    # R-227：证据先落库——讨论进行中前端「论点/引用来源」即时可见（不必等跑完）
    _merge_quality(
        db,
        draft,
        {
            "search_queries": ev.get("queries") or [],
            "online_sources": public_items(ev.get("sources") or []),
            "references": public_items(ev.get("selected") or [], 5),
            "station": station_meta,
        },
    )

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
            + (f"\n\n{evidence_block}" if evidence_block else "")
        )
        initial_budget = budget_settings.budget_for(db, "rewrite")
    else:
        initial_system = get_prompt("generation", db)
        # R-129：与金样本回放评分同一份输入；R-183 创作模式；R-227 注入联网证据
        initial_user = generation_user_message(db, topic, mode, evidence_block)
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
                "outlines": _parse_outlines(data),
                "sources_raw": data.get("sources") if isinstance(data.get("sources"), list) else [],
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
    # R-227：初稿一出来就把论点/引用来源落库（讨论中即可核对）
    _merge_quality(
        db,
        draft,
        {
            "outline": initial["outlines"][0]["claim"] if initial.get("outlines") else "",
            "outlines": initial.get("outlines") or [],
            "sources": public_items(resolve_used(ev.get("selected") or [], initial.get("sources_raw") or [])),
        },
    )
    _add(db, draft.id, 0, initial["model"], "draft", draft.script, llm=initial.get("llm"))

    # 2) N 轮讨论：评审方挑刺 → 生成方修订
    # R-228：评审/修订 system 都带事实硬规则；证据块（联网+站内）拼进 system，每轮调用都可见
    #（此前证据只在初稿注入，修订轮看不到事实，评审想"补具体细节"只能凭想象编）。
    critic_system = _with_evidence(
        (
            "你是脚本评审专家。请对照作者人设与语言习惯，指出当前脚本哪些地方不像作者、"
            "哪些有 AI 感，并给出具体可执行的修改建议（每轮简短、直给）。"
            "**并重点检查内容质量**：有没有 2-4 条明确论点、每条是否都有具体事例/数据支撑、"
            "有没有正确但没用的空话、有没有编造数字/人名/机构。"
            + NO_FABRICATION_RULE
            + f"\n作者人设：\n{persona_text}\n红线（不得违反）：\n{red_text}\n作者语言习惯：\n{ctx['profile']}"
        ),
        evidence_block,
    )
    if source_text:
        critic_system += f"\n参考原文（检查是否照搬/重复）：\n{source_text[:1500]}"
    revise_system = _with_evidence(
        (
            "你是撰稿模型。根据评审意见，用作者的口吻重写整篇口播脚本，"
            "只输出脚本正文，不要解释、不要加标题。保持 1-2 分钟口播长度。"
            "**优先满足内容质量**：确保有 2-4 条明确论点，且每条都有具体事例/数据支撑；"
            "有可引用的联网事实就口语化引用；严禁编造数字/人名/机构。"
            + NO_FABRICATION_RULE
            + f"\n作者语言习惯（自然贴近即可，不要硬塞口头禅/标志词）：\n{style_note}"
        ),
        evidence_block,
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

    # 3) 生成后自检（R-207）：**只有红线**才触发一次收口重写；
    #    口癖/高频词覆盖率、AI 腔词只做诊断（不强制重写，避免机械塞口头禅→模仿腔）。
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
            "以下几处踩了作者的**红线**，请整篇重写并避开；保持原有语气，不要为改而改、也不要硬塞口头禅：\n"
            + "\n".join(f"- {i}" for i in issues)
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

    diagnostics = style_diagnostics(db, draft.script)
    degraded = bool(gen_llm.degraded or critic_llm.degraded or initial["model"] != gen)
    # R-227：论点 / 引用来源 / 联网留痕 落库（引用编号越界=疑似编造来源，剔除）
    outlines = initial.get("outlines") or []
    used_sources = resolve_used(ev.get("selected") or [], initial.get("sources_raw") or [])
    draft.quality = json.dumps(
        {
            "models": {"gen": f"{gen}({gen_slot['vendor']}/{gen_slot['model']})", "critic": f"{critic}({critic_slot['vendor']}/{critic_slot['model']})"},
            "used": {"gen": gen_llm.routing()["used"], "critic": critic_llm.routing()["used"]},
            "fallback": degraded,
            "rounds": rounds_total,
            "rounds_done": rounds_done,
            "issues": issues,
            "passed": not issues,
            "style_coverage": diagnostics["style_coverage"],
            "diagnostics": diagnostics,
            "sole_model": gen == critic,
            "outline": outlines[0]["claim"] if outlines else "",
            "outlines": outlines,
            "sources": public_items(used_sources, 10),
            "online_sources": public_items(ev.get("sources") or []),
            "references": public_items(ev.get("selected") or [], 5),
            "search_queries": ev.get("queries") or [],
            "station": station_meta,
            # R-230：outlines/sources 是初稿口径；讨论后正文若已偏离论点，标记供前端提示
            "outline_drift": detect_outline_drift(outlines, draft.script),
        },
        ensure_ascii=False,
    )
    draft.script = latest
    db.commit()
    mark_logs_used(db, ev.get("log_ids") or [], public_items(used_sources, 10))
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
        "references": public_items(ev.get("selected") or [], 5),
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
    mode = str(payload.get("mode") or "").strip()
    query_source = str(payload.get("query_source") or "").strip()
    return run_debate(db, draft, topic, mode=mode, query_source=query_source)


def _merge_quality(db: Session, draft: Draft, patch: dict) -> None:
    """R-227：把证据/论点**增量**写进 `Draft.quality` 并提交，让讨论进行中前端就能看到。"""
    try:
        cur = json.loads(draft.quality or "{}")
        if not isinstance(cur, dict):
            cur = {}
    except (TypeError, ValueError):
        cur = {}
    cur.update(patch)
    draft.quality = json.dumps(cur, ensure_ascii=False)
    db.commit()


def _parse_outlines(data: dict) -> list[dict]:
    """R-227：解析模型输出的多条论点 `outlines`（兼容旧的单条 `outline`）。"""
    out: list[dict] = []
    raw = data.get("outlines")
    if isinstance(raw, list):
        for it in raw:
            if isinstance(it, dict):
                claim = str(it.get("claim") or "").strip()
                support = str(it.get("support") or "").strip()
                if claim:
                    out.append({"claim": claim, "support": support})
            elif isinstance(it, str) and it.strip():
                out.append({"claim": it.strip(), "support": ""})
    if not out:
        legacy = str(data.get("outline") or "").strip()
        if legacy:
            out.append({"claim": legacy, "support": ""})
    return out


# R-230：claim 关键词的纯文本提取——连续中英数串整串，长串再滑 4 字窗；
# 用于检测「初稿论点是否仍出现在终稿正文」，不额外调 LLM（省调用也省编造风险）。
_CLAIM_TOKEN = re.compile(r"[0-9A-Za-z一-鿿]+")


def _claim_grams(claim: str) -> list[str]:
    grams: list[str] = []
    for tok in _CLAIM_TOKEN.findall(claim or ""):
        if len(tok) <= 4:
            grams.append(tok)
        else:
            grams.extend(tok[i : i + 4] for i in range(len(tok) - 3))
    return [g for g in grams if len(g) >= 2]


def detect_outline_drift(outlines: list[dict], script: str) -> bool:
    """初稿论点 vs 终稿正文的漂移检测：任一 claim 的关键词在终稿中完全消失即 drift。

    quality 里落库的 outlines/sources 取的是**初稿**的，N 轮讨论后正文可能整体改写
    （draft 128：初稿谈自由职业、终稿谈求职）——标记漂移，前端提示「以正文为准」。
    """
    claims = [
        str((o or {}).get("claim") or "").strip()
        for o in (outlines or [])
        if isinstance(o, dict) and str((o or {}).get("claim") or "").strip()
    ]
    text = (script or "").strip()
    if not claims or not text:
        return False
    for claim in claims:
        if not any(g in text for g in _claim_grams(claim)):
            return True
    return False


def run_rewrite_debate(db: Session, payload: dict) -> dict:
    """对标洗稿双模型多轮讨论（R-118）。

    payload: {owner_id, key, title, text, benchmark_name, post_id, work_id}
    初稿先由生成方按原文改写，随后评审方/生成方交替多轮打磨；
    每轮写 draft_discussions 留痕，最终稿落 drafts（含 original_script / source_ref）。
    """
    from ..models.platform import Creator

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

    # R-194：对标洗稿主链路必须与普通生成/草稿讨论同源——注入完整作者上下文
    # （人设四层 + 风格范本 + 改稿对照 + 禁用词 + 结构偏好 + 相关风格样本），
    # 不能只喂简化人设，否则洗稿仍不像作者。
    from .benchmark import REWRITE_SYSTEM, _rewrite_user

    author_ctx = author_style_context(db, source_title)
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
    # R-227：联网事实证据（无 key/失败静默返回空），并写留痕
    # R-233：双源检索/正文补齐/去营销 + 生成方按当前主博主人设选文
    # R-241：证据缓存 + 站内检索与联网检索并发（同 run_debate）
    from .evidence import mark_logs_used, public_items, resolve_used

    rewrite_rounds = debate_rounds(db, settings)
    _status(
        db,
        draft.id,
        "正在联网检索参考（豆包 + DeepSeek），随后由生成方按人设选文…",
        kind="rewrite",
        actor=gen,
        phase="evidence",
        rounds=rewrite_rounds,
    )
    ev, station, station_meta = _evidence_and_station(
        db,
        topic=source_title,
        material=source_text,
        draft_id=draft.id,
        creator_id=owner.id,
        persona=_persona_brief(_persona_context(db), profile=author_ctx),
        picker=gen_llm,
    )
    evidence_block = "\n\n".join(x for x in (ev.get("block") or "", station.get("block") or "") if x)
    # R-227：证据先落库——讨论进行中前端「论点/引用来源」即时可见
    _merge_quality(
        db,
        draft,
        {
            "search_queries": ev.get("queries") or [],
            "online_sources": public_items(ev.get("sources") or []),
            "references": public_items(ev.get("selected") or [], 5),
            "station": station_meta,
        },
    )
    # R-178：洗稿同样留运行头 + 每次调用记实际模型
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

    # R-194：初稿走统一「参考改写」契约 + 完整作者上下文（只借选题与信息线索）；R-227 注入联网证据
    rewrite_system = REWRITE_SYSTEM
    rewrite_user = _rewrite_user(db, source_title, source_text, evidence_block)

    latest = None
    draft_llm = None
    initial_outlines: list[dict] = []
    initial_sources_raw: list = []
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
            initial_outlines = _parse_outlines(data)
            raw_sources = data.get("sources")
            initial_sources_raw = raw_sources if isinstance(raw_sources, list) else []
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
    # R-227：初稿的论点/引用来源先落库（讨论中即可核对）
    _merge_quality(
        db,
        draft,
        {
            "outline": initial_outlines[0]["claim"] if initial_outlines else "",
            "outlines": initial_outlines,
            "sources": public_items(resolve_used(ev.get("selected") or [], initial_sources_raw)),
        },
    )
    _add(db, draft.id, 0, gen, "draft", latest, llm=draft_llm)

    critic_system = (
        "你是脚本评审专家。对照**作者完整上下文**（人设/风格范本/语言习惯/禁用词/结构偏好）指出当前脚本"
        "哪些地方不像作者、哪些有 AI 腔、哪些与原文结构或句子雷同照搬"
        "（参考改写要求：只借选题与信息线索，不借结构/比喻/句群，必须补作者自己的经历与判断）；"
        "**并重点检查内容质量**：有没有 2-4 条明确论点、每条是否都有具体事例/数据支撑、"
        "引用的联网事实是否与提供的素材一致（有没有编造数字/人名/机构/经历）、"
        "有没有「要努力/要相信自己」这类正确但没用的空话；给出具体可执行的修改建议（简短直给）。"
        + NO_FABRICATION_RULE
        + f"\n作者上下文：\n{author_ctx}"
        + (f"\n\n可引用的联网事实素材：\n{evidence_block}" if evidence_block else "")
    )
    revise_system = (
        "你是撰稿模型。根据评审意见，用作者口吻重写整篇口播脚本，只输出脚本正文，"
        "不要解释、不要加标题，保持 1-2 分钟口播长度。"
        "**优先满足内容质量**：确保有 2-4 条明确论点，且每条都有具体事例/数据支撑；"
        "有可引用的联网事实就口语化引用；严禁编造数字/人名/机构/经历；删掉空话。"
        + NO_FABRICATION_RULE
        + f"\n作者上下文（必须贴合）：\n{author_ctx}"
        + (f"\n\n可引用的联网事实素材：\n{evidence_block}" if evidence_block else "")
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
    # R-227：论点 + 引用来源落库（引用编号越界=疑似编造来源，剔除）；并回写留痕的 used
    used_sources = resolve_used(ev.get("selected") or [], initial_sources_raw)
    draft.quality = json.dumps(
        {
            "outline": initial_outlines[0]["claim"] if initial_outlines else "",
            "outlines": initial_outlines,
            "sources": public_items(used_sources, 10),
            "online_sources": public_items(ev.get("sources") or []),
            "references": public_items(ev.get("selected") or [], 5),
            "search_queries": ev.get("queries") or [],
            "station": station_meta,
            # R-230：outlines/sources 是洗稿初稿口径；讨论后正文若已偏离论点，标记供前端提示
            "outline_drift": detect_outline_drift(initial_outlines, latest),
        },
        ensure_ascii=False,
    )
    db.commit()
    mark_logs_used(db, ev.get("log_ids") or [], public_items(used_sources, 10))
    return {
        "draft_id": draft.id,
        "title": draft.title,
        "cover_text": draft.cover_text,
        "script": latest,
        "original_script": source_text,
        "source_ref": source_ref,
        "benchmark_name": payload.get("benchmark_name") or "",
        "tags": source_tags,
        "outline": initial_outlines[0]["claim"] if initial_outlines else "",
        "outlines": initial_outlines,
        "sources": public_items(used_sources, 10),
        "online_sources": public_items(ev.get("sources") or []),
        "references": public_items(ev.get("selected") or [], 5),
        "search_queries": ev.get("queries") or [],
        "station": station_meta,
    }

