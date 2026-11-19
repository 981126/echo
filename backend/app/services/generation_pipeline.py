"""普通生成的唯一编排：角度 → 蓝图 → 写作 → 独立评审 → 程序门禁（R-263）。"""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy.orm import Session

from ..core.timeutil import now as _app_now
from ..models.author_generation import GenerationRun
from ..models.draft import Draft
from ..models.persona import PersonaTag
from . import budget_settings, draft_status, llm_router
from .author_assets import assets_prompt, public_asset, retrieve_author_assets
from .evidence import gather_online_cached, mark_logs_used, public_items
from .generation_validators import (
    GenerationValidationError,
    compute_quality_passed,
    json_dict,
    json_list,
    script_hash,
    validate_angles,
    validate_blueprint,
    validate_claims,
)
from .prompt_service import get_prompt, get_prompt_version

GENERATION_PLACEHOLDER = "（正在整理创作思路…）"

AUTHOR_ANGLE_SYSTEM = """你是作者的内容策划，不是直接写稿。先识别真实目标、受众、必要前提与物理限制，再提出最多3个不同切入角度。
每个角度只能有一个核心承诺，承诺必须有现有证据或清楚的推理支撑；建议必须能由目标对象实际执行，不能用单一因素替代完整决策。
不得虚构作者经历、数字、因果或外部事实。个人经历角度必须引用 experience 资产；事实角度必须有作者资产或在线来源；纯观点标 opinion。
信息不足时不要硬凑，返回最多3个会改变结论的具体问题。
只输出 JSON：{"angles":[{"angle_id":"a1","title":"切入标题","audience":"具体受众","promise":"唯一核心承诺",
"hook":"开头问题/冲突/结果","reasoning":["推理步骤"],"required_asset_ids":[1],"external_source_ids":["online:1"],
"claim_type":"author_experience|external_fact|inference|opinion","author_fit":0,"evidence_fit":0,
"audience_value":0,"distinctiveness":0,"risk":"可能夸大或缺证据之处"}],"questions":[]}。
四项分数各0～25，低于65的角度不可选。"""

AUTHOR_BLUEPRINT_SYSTEM = """你是严谨的内容策划。把选中的角度展开成写作前的内容蓝图，不写成稿。
核心承诺必须与角度逐字一致；推理说明证据为什么支持结论，推论写出边界或简单反例；每条行动都有适用前提和可执行动作。
先检查真实目标、对象、前提和物理条件，建议不能让必要对象缺席，也不能把距离近/成本低/通常如此当成唯一依据。
事实与经历必须引用给定证据，未知就保持未知。只输出 JSON：
{"goal":"观众看完要理解/做到什么","audience":"谁适用，谁不适用","core_promise":"唯一核心承诺",
"hook":{"text":"开头","payoff":"正文哪个推理步骤或行动兑现"},
"reasoning_steps":[{"claim":"本步结论","claim_type":"author_experience|external_fact|inference|opinion",
"evidence_ids":[1],"inference":"证据为什么支持结论","limitations":"边界或反例"}],
"actions":[{"precondition":"适用前提","action":"具体行动","expected_result":"不超证据的结果"}],
"ending":"如何回扣承诺"}。证据ID只能用作者资产整数、online:N 或 input:topic。"""

AUTHOR_WRITE_SYSTEM = """你是这位作者的代笔。只能依据已验证角度、蓝图、作者资产、人设和外部证据写可直接录制的口播稿。
开头提出具体矛盾、结果或问题，正文必须兑现；全篇只服务一个核心承诺，不套三点式，不机械塞口头禅。
蓝图中的适用对象、precondition 与 limitations 必须用自然口语写进正文，不能只留在蓝图里；存在不适用人群时明确说出。
作者第一人称经历只能来自 experience/fact 资产或 input:topic；外部素材只能作外部事实，不能换成作者亲身经历。
所有数字必须来自证据或写出计算过程；相关性、个人判断和条件性结论必须保留边界，不得写成确定因果。
标题、封面字、开头与正文中的事实都要声明 claims，主张 text 必须逐字出现在正文。
只输出 JSON：{"title":"标题","cover_text":"封面字","script":"完整口播正文",
"shells":{"douyin":"","bilibili":"","xiaohongshu":""},
"claims":[{"text":"正文中的事实性表述","type":"author_experience|external_fact|inference|opinion","evidence_ids":[1]}]}。
证据ID只能用作者资产整数、online:N 或 input:topic。素材不足就降低结论强度，不能编造。"""

AUTHOR_REVIEW_SYSTEM = """你是独立质量评审，不是写作方，也不能因为文字流畅就放过逻辑问题。
逐项检查：真实目标是否识别；对象、前提与物理条件是否满足；建议是否可执行；是否存在让结论失效的简单反例；
推理是否跳跃；经历、数字、因果是否有正确证据；开头承诺是否兑现；是否标题党；是否符合作者观点与表达而非通用AI稿。
逻辑与事实的任何关键问题都是硬失败。每个 hard_issue 必须引用能证明问题的正文原句，禁止说正文缺少实际存在的内容。
吸引力和作者感各1～5分，标题党或红线直接硬失败。
只输出 JSON：{"logic_passed":true,"hard_issues":[{"quote":"能证明问题的正文原句","problem":"具体问题","fix":"针对修改"}],"attraction_score":4,"author_score":4,
"issues":[{"dimension":"逻辑事实|吸引力|作者感","quote":"对应原句","problem":"具体问题","fix":"针对修改"}],
"goal_analysis":{"goal":"真实目标","constraints":"必要条件","counterexample":"已检查的反例"}}。不要代写整篇。"""

AUTHOR_REVISE_SYSTEM = """你负责只针对明确问题修订，不进行无目的的全篇互改。保持唯一核心承诺和作者真实证据，修复指出的原句与逻辑。
蓝图中的适用对象、precondition 与 limitations 必须保留在正文；修订不能删除或弱化这些边界。
修订蓝图时返回蓝图JSON；修订正文时返回 title/cover_text/script/shells/claims 完整JSON。
不得新增无证据的经历、数字或因果，不得改变证据类型。每次修订都要重新满足原输出契约。"""

_EXTERNAL_HINTS = (
    "健康", "疾病", "症状", "药", "治疗", "法律", "合同", "侵权", "金融", "理财", "股票", "基金",
    "税率", "社保", "科技", "模型", "软件", "数码", "汽车", "新闻", "热点", "政策", "研究", "数据",
)


def requires_external_facts(topic: str, input_text: str) -> bool:
    text = f"{topic} {input_text}"
    return any(hint in text for hint in _EXTERNAL_HINTS)


def _persona(db: Session, creator_id: int) -> dict[str, Any]:
    rows = (
        db.query(PersonaTag)
        .filter(PersonaTag.creator_id == creator_id, PersonaTag.status == "confirmed")
        .order_by(PersonaTag.category, PersonaTag.id)
        .all()
    )
    return {
        "tags": [
            {
                "label": row.label,
                "description": row.description,
                "category": row.category,
                "layer": row.layer,
                "evidence": row.evidence,
                "conditions": json_dict(row.conditions_json),
            }
            for row in rows
        ],
        "redlines": [row.label for row in rows if row.category == "redline"],
    }


def _attempts(run: GenerationRun) -> dict[str, Any]:
    attempts = json_dict(run.attempts_json)
    attempts.setdefault("stages", {})
    attempts.setdefault("write_count", 0)
    attempts.setdefault("review_count", 0)
    attempts.setdefault("revision_count", 0)
    return attempts


def _save_attempts(db: Session, run: GenerationRun, attempts: dict[str, Any]) -> None:
    latest = _attempts(run)
    latest["stages"].update(attempts.get("stages") or {})
    for key, value in attempts.items():
        if key != "stages":
            latest[key] = value
    run.attempts_json = json.dumps(latest, ensure_ascii=False)
    attempts.clear()
    attempts.update(latest)
    db.commit()


def _complete_stage(db: Session, run: GenerationRun, stage: str, detail: dict[str, Any] | None = None) -> None:
    attempts = _attempts(run)
    attempts["stages"][stage] = {
        "status": "completed",
        "completed_at": _app_now().isoformat(),
        **(detail or {}),
    }
    _save_attempts(db, run, attempts)


def _set_stage(db: Session, run: GenerationRun, stage: str, note: str) -> None:
    run.status = "running"
    run.stage = stage
    db.commit()
    if run.draft_id:
        draft_status.set_running(db, run.draft_id, note, kind="generate", phase=stage)


def _call_json(
    db: Session,
    run: GenerationRun,
    *,
    client: Any,
    stage: str,
    prompt_key: str,
    user: str,
    budget_key: str,
    require: tuple[str, ...],
) -> dict[str, Any]:
    data = client.chat_json(
        [
            {"role": "system", "content": get_prompt(prompt_key, db)},
            {"role": "user", "content": user},
        ],
        temperature=0.35 if stage == "review" else 0.65,
        max_tokens=budget_settings.budget_for(db, budget_key),
        require=require,
    )
    trace = json_dict(run.model_trace_json)
    trace[stage] = {
        **client.routing(),
        "prompt_key": prompt_key,
        "prompt_version": get_prompt_version(prompt_key, db),
        "used_slot": str(getattr(client, "used_slot", "") or ""),
        "vendor": str(getattr(client, "used_vendor", "") or ""),
        "model": str(getattr(client, "used_model", "") or ""),
    }
    run.model_trace_json = json.dumps(trace, ensure_ascii=False)
    db.commit()
    return data


def _online_sources(evidence: dict[str, Any]) -> list[dict[str, Any]]:
    selected = evidence.get("selected") or []
    return [
        {
            "id": f"online:{index}",
            **public_items([item], 1)[0],
            "summary": str(item.get("summary") or item.get("content") or "")[:2400],
        }
        for index, item in enumerate(selected, 1)
        if public_items([item], 1)
    ]


def _context_text(topic: str, input_text: str, assets: list[dict[str, Any]], persona: dict[str, Any], online: list[dict[str, Any]]) -> str:
    return "\n\n".join(
        [
            f"选题：{topic}\n作者本次输入：{input_text or '无'}",
            "作者资产（含原文证据）：\n" + assets_prompt(assets),
            "作者人设与红线：\n" + json.dumps(persona, ensure_ascii=False),
            "外部来源：\n" + json.dumps(online, ensure_ascii=False),
        ]
    )


def _review_shape(raw: dict[str, Any], digest: str, script: str) -> dict[str, Any]:
    if not isinstance(raw.get("logic_passed"), bool):
        raise GenerationValidationError("评审缺少 logic_passed 布尔值")
    try:
        attraction = float(raw.get("attraction_score") or 0)
        author = float(raw.get("author_score") or 0)
    except (TypeError, ValueError) as exc:
        raise GenerationValidationError("评审分数必须是数字") from exc
    if not 1 <= attraction <= 5 or not 1 <= author <= 5:
        raise GenerationValidationError("评审分数必须在 1～5 之间")
    issues = raw.get("issues") if isinstance(raw.get("issues"), list) else []
    raw_hard = raw.get("hard_issues")
    hard: list[Any] = raw_hard if isinstance(raw_hard, list) else []
    for issue in hard:
        if not isinstance(issue, dict) or not str(issue.get("problem") or "").strip():
            raise GenerationValidationError("逻辑硬失败缺少问题说明")
        quote = str(issue.get("quote") or "").strip()
        if not quote or quote not in script:
            raise GenerationValidationError("逻辑硬失败引用的正文原句不存在")
    return {
        **raw,
        "executed": True,
        "script_hash": digest,
        "hard_issues": hard,
        "issues": issues,
        "attraction_score": attraction,
        "author_score": author,
    }


def _sync_draft(db: Session, draft: Draft, run: GenerationRun, data: dict[str, Any], passed: bool) -> None:
    draft.title = str(data.get("title") or draft.title or run.topic).strip()
    draft.cover_text = str(data.get("cover_text") or "").strip()
    draft.script = str(data.get("script") or "").strip()
    draft.platform_shells = json.dumps(data.get("shells") or {}, ensure_ascii=False)
    draft.prompt_version = get_prompt_version("author_write", db)
    reviews = json_list(run.reviews_json)
    latest = reviews[-1] if reviews else {}
    draft.quality = json.dumps(
        {
            "run_id": run.id,
            "passed": passed,
            "quality_passed": passed,
            "logic_passed": bool(latest.get("logic_passed")),
            "attraction_score": latest.get("attraction_score"),
            "author_score": latest.get("author_score"),
            "issues": latest.get("issues") or [],
            "hard_issues": latest.get("hard_issues") or [],
            "review_executed": bool(latest.get("executed")),
            "models": json_dict(run.model_trace_json),
        },
        ensure_ascii=False,
    )
    db.commit()


def run_generation_pipeline(
    db: Session,
    run: GenerationRun,
    draft: Draft,
    *,
    selected_angle_id: str = "",
) -> dict[str, Any]:
    if not run.creator_id:
        raise ValueError("请先选择当前主博主")
    route = llm_router.snapshot(db)
    gen_slot, review_slot = route.generation_pair()
    gen_name, review_name = gen_slot["slot"], review_slot["slot"]
    other_gen = "model2" if gen_name == "model1" else "model1"
    other_review = "model2" if review_name == "model1" else "model1"
    writer = llm_router.RoutedLLM("generation", route, primary=gen_name, fallback=other_gen)
    reviewer = llm_router.RoutedLLM("generation", route, primary=review_name, fallback=other_review)
    input_context = json_dict(run.input_context)
    input_text = str(input_context.get("query_source") or "")
    attempts = _attempts(run)
    run.status = "running"
    db.commit()

    _set_stage(db, run, "assets", "正在整理作者素材与事实依据…")
    if selected_angle_id:
        evidence = json_dict(run.evidence_json)
        assets = evidence.get("author_assets") or []
        online = evidence.get("online_sources") or []
        angles = json_list(run.angles_json)
        angle = next((item for item in angles if item.get("angle_id") == selected_angle_id), None)
        if angle is None:
            raise ValueError("所选角度不属于这次生成")
        run.selected_angle_json = json.dumps(angle, ensure_ascii=False)
        db.commit()
        _complete_stage(db, run, "assets", {"reused": True})
        _complete_stage(db, run, "angles", {"reused": True})
    else:
        assets = retrieve_author_assets(db, run.creator_id, run.topic, input_text)
        persona = _persona(db, run.creator_id)
        evidence_raw: dict[str, Any] = {}
        if requires_external_facts(run.topic, input_text):
            evidence_raw = gather_online_cached(
                db,
                run.topic,
                material=input_text,
                draft_id=draft.id,
                creator_id=run.creator_id,
                persona=json.dumps(persona["tags"], ensure_ascii=False),
                picker=writer,
            )
        online = _online_sources(evidence_raw)
        evidence = {
            "author_assets": [public_asset(item) for item in assets],
            "online_sources": online,
            "search_queries": evidence_raw.get("queries") or [],
        }
        run.evidence_json = json.dumps(evidence, ensure_ascii=False)
        _complete_stage(db, run, "assets", {"asset_count": len(assets), "online_count": len(online)})
        _set_stage(db, run, "angles", "正在分析目标并筛选最佳角度…")
        context = _context_text(run.topic, input_text, assets, persona, online)
        raw_angles = _call_json(
            db, run, client=writer, stage="angles", prompt_key="author_angle", user=context,
            budget_key="debate_initial", require=(),
        )
        asset_ids = {int(item["id"]) for item in assets}
        asset_kinds = {int(item["id"]): str(item["kind"]) for item in assets}
        online_ids = {str(item["id"]) for item in online}
        accepted, rejected, questions = validate_angles(
            raw_angles, asset_ids=asset_ids, asset_kinds=asset_kinds, online_source_ids=online_ids
        )
        run.angles_json = json.dumps(accepted + rejected, ensure_ascii=False)
        db.commit()
        _complete_stage(db, run, "angles", {"accepted": len(accepted), "rejected": len(rejected)})
        if not accepted:
            reason = "；".join(
                str(reason)
                for item in rejected
                for reason in item.get("reject_reasons") or []
            ) or "现有信息不足以形成可靠角度"
            run.status = "needs_input"
            run.stage = "done"
            run.error = reason
            run.quality_passed = False
            evidence["questions"] = questions
            run.evidence_json = json.dumps(evidence, ensure_ascii=False)
            draft.script = ""
            _sync_draft(db, draft, run, {"title": run.topic, "script": ""}, False)
            db.commit()
            return {"run_id": run.id, "draft_id": draft.id, "status": run.status, "message": reason, "questions": questions}
        angle = max(accepted, key=lambda item: float(item.get("total_score") or 0))
        run.selected_angle_json = json.dumps(angle, ensure_ascii=False)
        db.commit()
        if evidence_raw.get("log_ids"):
            mark_logs_used(db, evidence_raw["log_ids"], online)

    evidence = json_dict(run.evidence_json)
    assets = evidence.get("author_assets") or []
    online = evidence.get("online_sources") or []
    asset_ids = {int(item["id"]) for item in assets}
    asset_kinds = {int(item["id"]): str(item["kind"]) for item in assets}
    online_ids = {str(item["id"]) for item in online}
    context = _context_text(run.topic, input_text, assets, _persona(db, run.creator_id), online)
    attempts = _attempts(run)

    blueprint: dict[str, Any] | None = None
    blueprint_problem = ""
    while blueprint is None:
        _set_stage(db, run, "blueprint", "正在搭建核心承诺与推理结构…")
        prompt_key = "author_blueprint" if not blueprint_problem else "author_revise"
        user = context + "\n\n选中角度：\n" + json.dumps(angle, ensure_ascii=False)
        if blueprint_problem:
            user += f"\n\n上一版蓝图：{run.blueprint_json}\n必须修复：{blueprint_problem}"
        raw_blueprint = _call_json(
            db, run, client=writer, stage="blueprint", prompt_key=prompt_key, user=user,
            budget_key="debate_initial", require=("core_promise", "reasoning_steps"),
        )
        run.blueprint_json = json.dumps(raw_blueprint, ensure_ascii=False)
        db.commit()
        try:
            blueprint = validate_blueprint(raw_blueprint, angle=angle, asset_ids=asset_ids, online_source_ids=online_ids)
        except GenerationValidationError as exc:
            blueprint_problem = str(exc)
            if attempts["revision_count"] >= 2:
                run.status = "needs_review"
                run.stage = "done"
                run.error = blueprint_problem
                run.quality_passed = False
                db.commit()
                return {"run_id": run.id, "draft_id": draft.id, "status": run.status, "message": blueprint_problem}
            attempts["revision_count"] += 1
            _save_attempts(db, run, attempts)
    _complete_stage(db, run, "blueprint")

    final_data: dict[str, Any] | None = None
    final_review: dict[str, Any] | None = None
    problem = ""
    while True:
        _set_stage(db, run, "writing", "正在按作者观点与表达撰写正文…")
        prompt_key = "author_write" if not problem else "author_revise"
        user = context + "\n\n选中角度：\n" + json.dumps(angle, ensure_ascii=False)
        user += "\n\n已验证内容蓝图：\n" + json.dumps(blueprint, ensure_ascii=False)
        if problem:
            user += f"\n\n上一版正文：{json.dumps(final_data, ensure_ascii=False)}\n只修复这些问题：{problem}"
        data = _call_json(
            db, run, client=writer, stage="writing", prompt_key=prompt_key, user=user,
            budget_key="debate_initial" if not problem else "debate_revise", require=("script",),
        )
        attempts["write_count"] += 1
        final_data = data
        run.draft_json = json.dumps(data, ensure_ascii=False)
        run.final_script_hash = script_hash(str(data.get("script") or ""))
        _save_attempts(db, run, attempts)
        try:
            validate_claims(
                data,
                asset_kinds=asset_kinds,
                online_source_ids=online_ids,
                evidence_text="\n".join(
                    [run.topic, input_text]
                    + [str(ref.get("quote") or "") for item in assets for ref in item.get("evidence_refs") or []]
                    + [str(item.get("summary") or "") for item in online]
                ),
            )
        except GenerationValidationError as exc:
            problem = str(exc)
            if attempts["revision_count"] >= 2:
                run.status = "needs_review"
                run.stage = "done"
                run.error = problem
                run.quality_passed = False
                _sync_draft(db, draft, run, data, False)
                db.commit()
                return {"run_id": run.id, "draft_id": draft.id, "status": run.status, "message": problem}
            attempts["revision_count"] += 1
            _save_attempts(db, run, attempts)
            continue
        _complete_stage(db, run, "writing")
        _set_stage(db, run, "review", "正在检查逻辑事实、吸引力与作者感…")
        raw_review = _call_json(
            db, run, client=reviewer, stage="review", prompt_key="author_review",
            user=context + "\n\n蓝图：\n" + json.dumps(blueprint, ensure_ascii=False)
            + "\n\n最终候选正文：\n" + json.dumps(data, ensure_ascii=False),
            budget_key="debate_critique", require=("logic_passed", "attraction_score", "author_score"),
        )
        final_review = _review_shape(raw_review, run.final_script_hash, str(data.get("script") or ""))
        reviews = json_list(run.reviews_json)
        reviews.append(final_review)
        run.reviews_json = json.dumps(reviews, ensure_ascii=False)
        attempts["review_count"] += 1
        _save_attempts(db, run, attempts)
        _complete_stage(db, run, "review", {"review_count": attempts["review_count"]})
        passed_review = (
            final_review["logic_passed"]
            and not final_review["hard_issues"]
            and final_review["attraction_score"] >= 4
            and final_review["author_score"] >= 4
        )
        if passed_review:
            break
        problem = json.dumps(final_review.get("issues") or final_review["hard_issues"], ensure_ascii=False)
        if attempts["revision_count"] >= 2:
            run.status = "needs_review"
            run.stage = "done"
            run.error = "修订后仍有未解决的质量问题"
            run.quality_passed = False
            _sync_draft(db, draft, run, data, False)
            db.commit()
            return {"run_id": run.id, "draft_id": draft.id, "status": run.status, "message": run.error}
        attempts["revision_count"] += 1
        _save_attempts(db, run, attempts)

    if final_data is None or final_review is None:
        raise GenerationValidationError("写作或评审未实际执行")
    run.status = "succeeded"
    run.stage = "done"
    run.error = ""
    run.quality_passed = compute_quality_passed(run)
    if not run.quality_passed:
        raise GenerationValidationError("服务端质量门禁未通过")
    _sync_draft(db, draft, run, final_data, True)
    draft.original_script = draft.script
    db.commit()
    return {
        "run_id": run.id,
        "draft_id": draft.id,
        "status": run.status,
        "title": draft.title,
        "quality_passed": run.quality_passed,
    }


def create_generation_run(db: Session, *, creator_id: int, draft_id: int | None, topic: str, query_source: str = "") -> GenerationRun:
    run = GenerationRun(
        creator_id=creator_id,
        draft_id=draft_id,
        topic=topic.strip(),
        input_context=json.dumps({"query_source": query_source}, ensure_ascii=False),
        status="queued",
    )
    db.add(run)
    db.commit()
    db.refresh(run)
    return run


def generate_author_draft(db: Session, topic: str, *, query_source: str = "") -> Draft:
    from .creator_service import current_creator_id
    from .persona_profile import current_persona_version

    creator_id = current_creator_id(db)
    if creator_id is None:
        raise ValueError("请先选择当前主博主")
    draft = Draft(
        creator_id=creator_id,
        title=topic.strip(),
        script=GENERATION_PLACEHOLDER,
        source="ai",
        persona_version=current_persona_version(db, creator_id),
    )
    db.add(draft)
    db.commit()
    db.refresh(draft)
    run = create_generation_run(db, creator_id=creator_id, draft_id=draft.id, topic=topic, query_source=query_source)
    try:
        result = run_generation_pipeline(db, run, draft)
    except Exception as exc:
        db.rollback()
        run = db.get(GenerationRun, run.id) or run
        draft = db.get(Draft, draft.id) or draft
        run.status = "failed"
        run.quality_passed = False
        run.error = str(exc)[:1000]
        if (draft.script or "") == GENERATION_PLACEHOLDER:
            draft.script = ""
        draft.quality = json.dumps(
            {"run_id": run.id, "passed": False, "review_executed": False, "error": run.error},
            ensure_ascii=False,
        )
        db.commit()
        draft_status.set_failed(db, draft.id, f"生成失败：{run.error[:150]}", kind="generate", phase=run.stage)
        raise
    if result["status"] != "succeeded":
        label = "待补信息" if result["status"] == "needs_input" else "待作者修改"
        draft_status.set_failed(
            db,
            draft.id,
            f"{label}：{result.get('message') or '本次没有形成合格正文'}",
            kind="generate",
            phase=run.stage,
        )
        raise GenerationValidationError(result.get("message") or "本次没有形成合格正文")
    from .draft_versions import finalize_version

    finalize_version(db, draft, source="ai_generate", note="AI 生成")
    draft_status.clear(db, draft.id)
    return draft


def generation_run_payload(run: GenerationRun) -> dict[str, Any]:
    reviews = json_list(run.reviews_json)
    evidence = json_dict(run.evidence_json)
    return {
        "run_id": run.id,
        "draft_id": run.draft_id,
        "status": run.status,
        "stage": run.stage,
        "topic": run.topic,
        "selected_angle": json_dict(run.selected_angle_json),
        "angles": json_list(run.angles_json),
        "blueprint": json_dict(run.blueprint_json),
        "evidence": {
            "author_assets": evidence.get("author_assets") or [],
            "online_sources": evidence.get("online_sources") or [],
            "questions": evidence.get("questions") or [],
        },
        "review": reviews[-1] if reviews else {"executed": False, "logic_passed": False, "issues": []},
        "quality_passed": bool(run.quality_passed) and run.status != "legacy",
        "legacy_unverified": run.status == "legacy",
        "models": json_dict(run.model_trace_json),
        "attempts": json_dict(run.attempts_json),
        "error": run.error,
        "updated_at": run.updated_at.isoformat() if run.updated_at else None,
    }


__all__ = [
    "AUTHOR_ANGLE_SYSTEM",
    "AUTHOR_BLUEPRINT_SYSTEM",
    "AUTHOR_REVIEW_SYSTEM",
    "AUTHOR_REVISE_SYSTEM",
    "AUTHOR_WRITE_SYSTEM",
    "GENERATION_PLACEHOLDER",
    "create_generation_run",
    "generate_author_draft",
    "generation_run_payload",
    "requires_external_facts",
    "run_generation_pipeline",
]
