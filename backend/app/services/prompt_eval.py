"""金样本回放评分（R-129 M115）。

候选版与当前启用版在**同一批金样本**上各跑一遍，按客观口径打分，供作者判断「准不准」：

- `format`：输出满足该功能的输出契约（JSON 可解析 + 必需字段齐全）的比例；
- `redline`：输出命中作者已确认红线的比例（越低越好）；
- `style`：输出覆盖作者高频口头禅/标志用词的比例（越像越好，仅对自然语言产出类 key 计分）。

综合分 = 100 ×（有 style：0.5·format + 0.3·(1−redline) + 0.2·style；无 style：0.6·format + 0.4·(1−redline)）。
R-129 口径：评分只做展示。R-208 起：后台自动优化链路里，候选评分 ≥ 当前版 ×(1+`AUTO_ENABLE_DELTA`) 时自动启用。
"""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable

from sqlalchemy.orm import Session

from ..config import get_settings
from ..core.log import get_logger
from ..models.prompt import AiPrompt, PromptEval
from .creator_service import current_creator_id
from .llm import _parse_json

log = get_logger("prompt_eval")

GOLDEN_TOPICS = 5
GOLDEN_VIDEOS = 8
GOLDEN_DRAFTS = 3
MAX_PROBES = 5
# R-208：自动优化链路里，候选评分相对当前启用版高出该比例才自动启用（±可调）。
AUTO_ENABLE_DELTA = 0.10
# 回放单次生成上限：推理模型（如 kimi）会把预算花在思考上，太小会导致正文为空（R-129 实测踩过）
MAX_OUTPUT_TOKENS = 6000

# 每个 key 期望的输出字段（None = 纯文本输出）
OUTPUT_FIELDS: dict[str, list[str] | None] = {
    "generation": ["title", "script"],
    "video_tags": ["main_topics", "is_ad", "tags"],
    "diff": ["suggestions"],
    "persona_init": ["tags"],
    "persona_merge": ["tags"],
    "persona_updates": ["tags"],
    "persona_compare": ["score"],
    "correct": None,
}
# 自然语言产出类：style 覆盖率参与计分
STYLE_KEYS = {"generation", "correct"}
UNSUPPORTED_REASON = "该功能暂不支持金样本回放评分（仅做候选契约自检）"


# ---------- 金样本 ----------


def _transcript(video) -> str:
    tr = getattr(video, "transcript", None)
    if tr is None:
        return ""
    return (tr.corrected_text or tr.transcript_text or "").strip()


def _style_markers(db: Session) -> list[str]:
    try:
        from ..core.style_profile import build_style_profile
        from .generation import _all_texts

        texts = [t for _v, t in _all_texts(db)]
        profile = build_style_profile(texts)
        return [str(x) for x in (profile.get("top_phrases") or [])[:8] if str(x).strip()]
    except Exception:  # noqa: BLE001
        return []


def _redlines(db: Session) -> list[str]:
    from ..models.persona import PersonaTag

    q = db.query(PersonaTag).filter(PersonaTag.status == "confirmed", PersonaTag.category == "redline")
    cid = current_creator_id(db)
    if cid:
        q = q.filter(PersonaTag.creator_id == cid)
    return [t.label for t in q.all() if len(t.label or "") >= 6]


def golden_set(db: Session) -> dict:
    """高表现素材选题 Top5 + 高/低分草稿各 3 条 + 风格标记 + 红线。"""
    from ..models.draft import Draft
    from ..models.metrics import MetricsSnapshot
    from ..models.video import Video

    cid = current_creator_id(db)
    q = db.query(Video).filter(Video.is_ad.is_(False))
    if cid:
        q = q.filter(Video.creator_id == cid)
    snap: dict[int, MetricsSnapshot] = {}
    for row_snap in db.query(MetricsSnapshot).order_by(MetricsSnapshot.snapshot_date.desc()).all():
        snap.setdefault(row_snap.video_id, row_snap)
    scored: list[tuple[float, str, str]] = []
    for v in q.all():
        text = _transcript(v)
        if not text:
            continue
        snap_row = snap.get(v.id)
        eng = (
            float(snap_row.plays + snap_row.likes * 5 + snap_row.favorites * 3 + snap_row.comments * 10)
            if snap_row is not None
            else 0.0
        )
        scored.append((eng, v.title or "", text))
    scored.sort(key=lambda x: x[0], reverse=True)

    def _drafts(status: str, exclude_pure_manual: bool = False) -> list[dict]:
        """R-211：金样本/反面稿口径改 status 驱动（done=认可 / archived=否定，历史 rating/liked 弃用）。"""
        from .draft_versions import pure_manual_map

        dq = db.query(Draft).filter(Draft.status == status, Draft.script != "")
        if cid:
            dq = dq.filter(Draft.creator_id == cid)
        rows = dq.order_by(Draft.updated_at.desc()).limit(GOLDEN_DRAFTS * 2).all()
        if exclude_pure_manual:
            pm = pure_manual_map(db, rows)
            rows = [d for d in rows if not pm.get(d.id, False)]
        out: list[dict] = []
        for d in rows[:GOLDEN_DRAFTS]:
            if (d.script or "").strip():
                out.append(
                    {
                        "script": d.script.strip(),
                        "original": (d.original_script or "").strip(),
                        "rating": None,
                    }
                )
        return out

    return {
        "topics": [t for _e, t, _x in scored[:GOLDEN_TOPICS] if t],
        "videos": [(t, x) for _e, t, x in scored[:GOLDEN_VIDEOS]],
        "high_drafts": _drafts("done"),
        "low_drafts": _drafts("archived", exclude_pure_manual=True),  # R-210：手写稿放弃≠写得差
        "markers": _style_markers(db),
        "redlines": _redlines(db),
    }


# ---------- 每个 key 的回放输入 ----------


def _archive_json(db: Session) -> str:
    from .persona_profile import current_profile

    return json.dumps(current_profile(db, current_creator_id(db)), ensure_ascii=False)


def _probes(db: Session, key: str, golden: dict) -> list[dict]:
    """返回 [{"label": str, "user": str}]；空列表 = 没有可用金样本。"""
    videos = golden.get("videos") or []
    if key == "generation":
        from .generation import generation_user_message

        return [
            {"label": f"高表现选题：{t[:30]}", "user": generation_user_message(db, t)}
            for t in (golden.get("topics") or [])
        ]
    if key == "video_tags":
        return [{"label": f"素材：{t[:30]}", "user": x[:1200]} for t, x in videos[:3]]
    if key == "correct":
        # 校对回放必须喂**原始转写稿**（corrected 已经是修正结果），并复刻生产 user 模板
        from ..models.video import Video

        vq = db.query(Video).filter(Video.is_ad.is_(False))
        cid = current_creator_id(db)
        if cid:
            vq = vq.filter(Video.creator_id == cid)
        out: list[dict] = []
        for v in vq.order_by(Video.id.desc()).limit(30).all():
            tr = getattr(v, "transcript", None)
            if tr is None:
                continue
            raw = (tr.transcript_text or "").strip()
            if not raw:
                continue
            out.append(
                {
                    "label": f"转写稿：{(v.title or '')[:30]}",
                    "user": f"原始文案（仅供参考，可能与口播不一致）：\n无\n\n转写稿：\n{raw[:1200]}",
                }
            )
            if len(out) >= 3:
                break
        return out
    if key == "diff":
        pairs = [d for d in (golden.get("high_drafts") or []) if d.get("original")]
        if not pairs:
            from ..models.draft import Draft

            dq = db.query(Draft)
            cid = current_creator_id(db)
            if cid:
                dq = dq.filter(Draft.creator_id == cid)
            for d in dq.order_by(Draft.id.desc()).limit(20).all():
                if (d.original_script or "").strip() and (d.script or "").strip() and d.original_script.strip() != d.script.strip():
                    pairs.append({"original": d.original_script.strip(), "script": d.script.strip()})
                if len(pairs) >= 3:
                    break
        return [
            {"label": f"改稿对{i + 1}", "user": f"AI 原稿：\n{p['original'][:800]}\n\n作者改后：\n{p['script'][:800]}"}
            for i, p in enumerate(pairs[:3])
        ]
    if key in ("persona_init", "persona_merge", "persona_updates", "persona_compare"):
        from ..models.kv import Kv

        archive = _archive_json(db)
        if key == "persona_init":
            return [{"label": f"转写稿：{t[:30]}", "user": x[:1200]} for t, x in videos[:3]]
        if key == "persona_merge":
            pieces = [row.value for row in db.query(Kv).filter(Kv.key.like("persona_piece_v1:%")).limit(3).all()]
            if not pieces:
                return []
            return [{"label": "逐篇提炼结果", "user": "各篇文案提炼结果（JSON 数组）：\n[" + ",".join(pieces) + "]"}]
        if key == "persona_updates":
            if not videos:
                return []
            piece = json.dumps({"tags": [{"label": "示例标签", "description": "", "dimension": "语气"}], "redlines": []}, ensure_ascii=False)
            return [{"label": "档案 + 新篇", "user": f"当前人设档案：\n{archive}\n\n新文案提炼结果：\n{piece}"}]
        return [{"label": "增量 vs 全量", "user": f"A 增量档案：\n{archive}\n\nB 全量档案：\n{archive}"}]
    return []


# ---------- 打分 ----------


def _format_ok(key: str, text: str) -> bool:
    body = (text or "").strip()
    if not body:
        return False
    fields = OUTPUT_FIELDS.get(key)
    if fields is None:  # 纯文本输出：不该出现代码围栏
        return len(body) >= 5 and "```" not in body
    data = _parse_json(body)  # 自动兼容 ```json 围栏与前后缀
    if not isinstance(data, dict):
        return False
    return all(f in data for f in fields)


def _score_outputs(key: str, outputs: list[str], markers: list[str], redlines: list[str]) -> dict:
    total = max(len(outputs), 1)
    format_rate = sum(1 for o in outputs if _format_ok(key, o)) / total
    redline_hits = sum(1 for o in outputs if any(r in o for r in redlines))
    redline_rate = redline_hits / total
    style_rate: float | None = None
    if key in STYLE_KEYS and markers:
        joined = "\n".join(outputs)
        style_rate = sum(1 for m in markers if m in joined) / len(markers)
    if style_rate is None:
        score = 100.0 * (0.6 * format_rate + 0.4 * (1 - redline_rate))
    else:
        score = 100.0 * (0.5 * format_rate + 0.3 * (1 - redline_rate) + 0.2 * style_rate)
    return {
        "format_rate": round(format_rate, 4),
        "redline_rate": round(redline_rate, 4),
        "style_rate": None if style_rate is None else round(style_rate, 4),
        "score": round(score, 1),
        "probes": len(outputs),
    }


def _run_version(db: Session, llm, content: str, probes: list[dict], key: str, markers: list[str], redlines: list[str]) -> dict:
    """串行跑一个版本的 probe（并发度 ≤1 / 并发池不可用时的降级路径）。"""
    outputs: list[str] = []
    empty = 0
    errors = 0
    for probe in probes:
        try:
            out = llm.chat(
                [{"role": "system", "content": content}, {"role": "user", "content": probe["user"]}],
                temperature=0.4,
                max_tokens=MAX_OUTPUT_TOKENS,
            )
        except Exception:  # noqa: BLE001 单个样本失败按不合格计，但单独统计
            out = ""
            errors += 1
        if not (out or "").strip():
            empty += 1
        outputs.append(out)
    result = _score_outputs(key, outputs, markers, redlines)
    result["empty"] = empty
    result["errors"] = errors
    return result


# ---------- R-240 S2：候选版/当前版的独立 LLM 调用并发 ----------


def _eval_feature(key: str) -> str:
    """评测所用 LLM 的功能名（与生产路由一致）：generation 走「提示词优化与评测」组。"""
    return "prompt_optimize" if key == "generation" else "prompt_eval"


def _llm_factory(db: Session, key: str) -> Callable[[], Any]:
    """主线程取一次路由快照，返回「每个并发任务新建独立 RoutedLLM」的工厂。

    `RoutedLLM` 持有 `used_slot/degraded` 等实例状态，禁止跨线程共享；
    主用槽位口径与串行路径的 `_eval_llm` 一致（含 R-232 功能路由 / R-229 生成方跟随）。
    """
    from . import llm_router, model_settings

    feature = _eval_feature(key)
    route = llm_router.snapshot(db)
    primary = model_settings.feature_route(db, feature)
    if primary == "model1":
        return lambda: llm_router.llm_from_snapshot(route, feature)
    # llm_from_snapshot 固定 model1 主用；功能路由指定 model2 时按同语义显式构造
    return lambda: llm_router.RoutedLLM(feature, route, primary=primary, fallback="model1")


def _collect_parallel(
    db: Session,
    key: str,
    contents: dict[str, str],
    probes: list[dict],
    workers: int,
) -> tuple[dict[str, list[str]], dict[str, int]]:
    """把两版 × 各 probe 的独立 LLM 调用合并成一个任务池，按 (tag, idx) 回填。"""
    factory = _llm_factory(db, key)
    jobs = [(tag, i, probe) for tag in contents for i, probe in enumerate(probes)]
    buckets: dict[str, list[str]] = {tag: [""] * len(probes) for tag in contents}
    errors: dict[str, int] = {tag: 0 for tag in contents}

    def _run(job: tuple[str, int, dict]) -> tuple[str, int, str, int]:
        tag, idx, probe = job
        try:
            out = factory().chat(
                [
                    {"role": "system", "content": contents[tag]},
                    {"role": "user", "content": probe["user"]},
                ],
                temperature=0.4,
                max_tokens=MAX_OUTPUT_TOKENS,
            )
            return tag, idx, out or "", 0
        except Exception:  # noqa: BLE001 单个样本失败按不合格计，但单独统计
            return tag, idx, "", 1

    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="echo-prompt-eval") as ex:
        for tag, idx, out, err in ex.map(_run, jobs):
            buckets[tag][idx] = out
            errors[tag] += err
    return buckets, errors


def _run_versions(
    db: Session,
    key: str,
    contents: dict[str, str],
    probes: list[dict],
    markers: list[str],
    redlines: list[str],
) -> dict[str, dict]:
    """R-240 S2：候选版/当前版 × probe 并发跑分；并发度 ≤1 或建池失败回退串行。

    `contents` 的 key 即版本 tag（"cand"/"base"）；返回 {tag: `_score_outputs` 结果}，
    评分口径、输出顺序与 errors/empty 统计与串行完全一致。
    """
    workers = max(
        1,
        min(int(get_settings().prompt_eval_concurrency or 1), 5, len(contents) * len(probes)),
    )
    if workers > 1:
        try:
            buckets, errors = _collect_parallel(db, key, contents, probes, workers)
        except Exception:  # noqa: BLE001 并发池创建/调度异常 → 回退串行（评分口径不变）
            log.exception("金样本评测并发出错，回退串行（key=%s）", key)
        else:
            out: dict[str, dict] = {}
            for tag, outputs in buckets.items():
                result = _score_outputs(key, outputs, markers, redlines)
                result["empty"] = sum(1 for o in outputs if not (o or "").strip())
                result["errors"] = errors[tag]
                out[tag] = result
            return out
    llm, _mode = _eval_llm(db, key)
    return {tag: _run_version(db, llm, contents[tag], probes, key, markers, redlines) for tag in contents}


# ---------- 评测入口 ----------


def _store(db: Session, key: str, cand_version: int, base_version: int, supported: bool, reason: str, detail: dict, cand: float = 0.0, base: float = 0.0) -> PromptEval:
    row = PromptEval(
        key=key,
        candidate_version=cand_version,
        base_version=base_version,
        candidate_score=cand,
        base_score=base,
        supported=supported,
        reason=reason,
        detail=json.dumps(detail, ensure_ascii=False),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def _eval_llm(db: Session, key: str):
    """评测用模型与该 key 在生产里的模型保持一致（R-129/R-139）。

    - generation 走「生成方/评审方」里的生成方模型；
    - 其余功能生产里都走模型1（失败才降级模型2），评测同样走模型1。
    """
    from . import llm_router

    if key == "generation":
        from .prompt_service import _optimize_llm

        llm, mode = _optimize_llm(db)
        return llm, mode
    client = llm_router.primary_llm(db, "prompt_eval")
    return client, client.used_model


def evaluate(db: Session, key: str, candidate_version: int, update=None) -> PromptEval | None:
    """对候选版做金样本回放评分，与当前启用版对比；结果落 prompt_evals。"""
    candidate = (
        db.query(AiPrompt).filter(AiPrompt.key == key, AiPrompt.version == candidate_version).first()
    )
    if candidate is None:
        return None
    base = (
        db.query(AiPrompt)
        .filter(AiPrompt.key == key, AiPrompt.status == "enabled")
        .order_by(AiPrompt.version.desc())
        .first()
    )
    base_version = base.version if base is not None else 0
    if key not in OUTPUT_FIELDS:
        return _store(db, key, candidate_version, base_version, False, UNSUPPORTED_REASON, {})
    golden = golden_set(db)
    probes = _probes(db, key, golden)[:MAX_PROBES]
    if not probes:
        return _store(db, key, candidate_version, base_version, False, "样本不足，无法回放评分", {})
    markers = golden.get("markers") or []
    redlines = golden.get("redlines") or []
    if update:
        update(20, f"金样本回放评分（{len(probes)} 个样本 × 2 版）…")
    contents = {"cand": candidate.content}
    if base is not None:
        contents["base"] = base.content
    if update:
        update(30, "并发回放评分中…")
    results = _run_versions(db, key, contents, probes, markers, redlines)
    if update:
        update(85, "评分完成，正在汇总…")
    cand_result = results["cand"]
    base_result = results.get("base", {})
    detail = {
        "probes": [p["label"] for p in probes],
        "candidate": cand_result,
        "base": base_result,
        "markers": markers[:8],
        "redlines": redlines[:10],
    }
    # 两版都产不出内容 → 评分无意义，标记为不可用而不是给个误导性的低分
    if cand_result.get("empty") == len(probes) and base_result.get("empty") == len(probes):
        return _store(
            db,
            key,
            candidate_version,
            base_version,
            False,
            "AI 回放返回为空（模型未产出内容，可能是配额或上下文问题），本次评分无效",
            detail,
        )
    if update:
        update(95, "写入评测结果…")
    return _store(
        db,
        key,
        candidate_version,
        base_version,
        True,
        "",
        detail,
        cand=float(cand_result.get("score") or 0.0),
        base=float(base_result.get("score") or 0.0),
    )


def latest_eval(db: Session, key: str) -> PromptEval | None:
    return db.query(PromptEval).filter(PromptEval.key == key).order_by(PromptEval.id.desc()).first()


def start_prompt_eval(db: Session, key: str, version: int) -> int | None:
    """候选产出后排队评测（后台任务）。"""
    from ..tasks import start_task

    return start_task("prompt_eval", {"key": key, "version": version}, prompt_eval_task)


def prompt_eval_task(db: Session, payload: dict, update=None) -> dict:
    """后台任务：跑金样本回放评分 + R-208 自动启用/静默丢弃 + 写通知。"""
    from ..tasks import push_notification

    key = str(payload.get("key") or "")
    version = int(payload.get("version") or 0)
    if not key or not version:
        return {"message": "评测参数缺失，跳过"}
    row = evaluate(db, key, version, update=update)
    if row is None:
        return {"message": "候选不存在，跳过评测"}
    enabled = False
    if not row.supported:
        message = f"评测跳过：{row.reason}"
    elif row.base_score <= 0:
        # 当前版没有可比评分（内容为空/无效）：不作判断，保留候选待作者查看
        message = f"候选 v{version} 得分 {row.candidate_score:.0f}；当前版无可比评分，候选保留待人工查看"
    elif row.candidate_score >= row.base_score * (1 + AUTO_ENABLE_DELTA):
        from .prompt_service import enable_version

        enable_version(db, key, version)
        enabled = True
        gain = (row.candidate_score - row.base_score) / row.base_score * 100
        cand_row = db.query(AiPrompt).filter(AiPrompt.key == key, AiPrompt.version == version).first()
        note = (cand_row.note or "").strip() if cand_row is not None else ""
        change = f"；变更说明：{note[:120]}" if note else ""
        message = (
            f"已自动启用候选 v{version}（评分 {row.candidate_score:.0f} vs v{row.base_version} {row.base_score:.0f}，"
            f"+{gain:.0f}%）{change}；如不认可可回滚到 v{row.base_version}"
        )
    else:
        # R-208：不更好静默丢弃（留痕 rejected，不发通知、不打扰作者）
        from .prompt_service import reject_candidate

        reject_candidate(db, key, version)
        if update:
            update(100, f"候选 v{version} 未明显更好，已静默丢弃")
        return {"message": f"候选 v{version}（{row.candidate_score:.0f} vs {row.base_score:.0f}）未明显更好，已丢弃"}
    try:
        push_notification(
            db,
            kind="prompt_auto_enable" if enabled else "prompt_eval",
            status="done",
            title=f"{key} 候选自动启用" if enabled else f"{key} 候选评测完成",
            message=message,
            target=f"/prompts?key={key}",
        )
    except Exception:  # noqa: BLE001
        db.rollback()
    if update:
        update(100, message)
    return {"message": message}


__all__ = [
    "golden_set",
    "evaluate",
    "latest_eval",
    "start_prompt_eval",
    "prompt_eval_task",
    "OUTPUT_FIELDS",
]
