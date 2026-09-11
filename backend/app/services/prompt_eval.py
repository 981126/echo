"""金样本回放评分（R-129 M115）。

候选版与当前启用版在**同一批金样本**上各跑一遍，按客观口径打分，供作者判断「准不准」：

- `format`：输出满足该功能的输出契约（JSON 可解析 + 必需字段齐全）的比例；
- `redline`：输出命中作者已确认红线的比例（越低越好）；
- `style`：输出覆盖作者高频口头禅/标志用词的比例（越像越好，仅对自然语言产出类 key 计分）。

综合分 = 100 ×（有 style：0.5·format + 0.3·(1−redline) + 0.2·style；无 style：0.6·format + 0.4·(1−redline)）。
评分只做展示，不设启用门槛（R-129 确认口径）。
"""

from __future__ import annotations

import json

from sqlalchemy.orm import Session

from ..models.prompt import AiPrompt, PromptEval
from .creator_service import current_creator_id
from .llm import _parse_json

GOLDEN_TOPICS = 5
GOLDEN_VIDEOS = 8
GOLDEN_DRAFTS = 3
MAX_PROBES = 5
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
    from ..models.feedback import Feedback
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

    def _drafts(min_rating: int | None, max_rating: int | None, liked: bool = False) -> list[dict]:
        dq = db.query(Feedback, Draft).join(Draft, Feedback.draft_id == Draft.id)
        if cid:
            dq = dq.filter(Draft.creator_id == cid)
        if liked:
            dq = dq.filter(Feedback.liked.is_(True))
        if min_rating is not None:
            dq = dq.filter(Feedback.rating >= min_rating)
        if max_rating is not None:
            dq = dq.filter(Feedback.rating <= max_rating)
        out: list[dict] = []
        for fb, d in dq.order_by(Feedback.id.desc()).limit(GOLDEN_DRAFTS).all():
            if d and (d.script or "").strip():
                out.append(
                    {
                        "script": d.script.strip(),
                        "original": (d.original_script or "").strip(),
                        "rating": fb.rating,
                    }
                )
        return out

    return {
        "topics": [t for _e, t, _x in scored[:GOLDEN_TOPICS] if t],
        "videos": [(t, x) for _e, t, x in scored[:GOLDEN_VIDEOS]],
        "high_drafts": _drafts(4, None) or _drafts(None, None, liked=True),
        "low_drafts": _drafts(None, 2),
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
    """评测用模型与该 key 在生产里的模型保持一致（R-129）：

    只有 generation 跟随「生成模型策略」，其余功能生产里都走 DeepSeek；
    用错模型会得到与线上不同的结果（实测：kimi 推理模型跑长文本校对会返回空正文）。
    """
    from .llm import DeepSeekClient

    if key == "generation":
        from .prompt_service import _optimize_llm

        llm, mode = _optimize_llm(db)
        return llm, mode
    return DeepSeekClient(), "deepseek"


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
    llm, _mode = _eval_llm(db, key)
    cand_result = _run_version(db, llm, candidate.content, probes, key, markers, redlines)
    if update:
        update(60, "候选版评分完成，正在跑当前版…")
    base_result = (
        _run_version(db, llm, base.content, probes, key, markers, redlines) if base is not None else {}
    )
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
    """后台任务：跑金样本回放评分 + 写通知（R-129 M115）。"""
    from ..tasks import push_notification

    key = str(payload.get("key") or "")
    version = int(payload.get("version") or 0)
    if not key or not version:
        return {"message": "评测参数缺失，跳过"}
    row = evaluate(db, key, version, update=update)
    if row is None:
        return {"message": "候选不存在，跳过评测"}
    if not row.supported:
        message = f"评测跳过：{row.reason}"
    else:
        message = f"候选 v{version} 得分 {row.candidate_score:.0f} / 当前 v{row.base_version} 得分 {row.base_score:.0f}"
    try:
        push_notification(
            db,
            kind="prompt_eval",
            status="done",
            title=f"{key} 候选评测完成",
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
