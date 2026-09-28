"""人设分析管线（R-128）：逐篇提取（带缓存）→ AI 归纳合并 → 增量合并 → 增量/全量 5% 对齐。

设计要点：
- 逐篇提取结果按「提示词 + 转写稿内容」hash 缓存（app_kv），内容不变则复用，
  与实时全量重算结果完全一致，但把重复的 LLM 成本降下来（作者已确认允许缓存）。
- 比对口径：先算集合覆盖率（全量档案条目被增量档案覆盖的比例），再让 AI 做语义复核打分（0-100），
  两者都 ≥95% 才算通过；不通过则回退全量结果并通知作者。
"""

from __future__ import annotations

import hashlib
import json
from concurrent.futures import ThreadPoolExecutor, as_completed

from ..models.kv import Kv
from ..models.persona import PersonaTag
from .persona import PersonaService, empty_profile, get_prompt, label_match, merge_mechanical, _norm_label

# 达标阈值（作者要求：增量结果与从头全量分析的差异不超过 5%）
PASS_THRESHOLD = 0.95
SEMANTIC_THRESHOLD = 95.0
_PIECE_CACHE_PREFIX = "persona_piece_v1"


def _text_hash(text: str) -> str:
    return hashlib.sha1((text or "").encode("utf-8")).hexdigest()


def _piece_cache_key(prompt: str, text: str) -> str:
    """缓存键含提示词指纹：作者改写 persona_init 提示词后旧缓存自动失效。"""
    prompt_hash = hashlib.sha1((prompt or "").encode("utf-8")).hexdigest()[:10]
    return f"{_PIECE_CACHE_PREFIX}:{prompt_hash}:{_text_hash(text)}"


def _extract_one(text: str, service_factory) -> dict | None:
    """单篇调 AI（每线程独立 service 实例）；单篇失败返回 None，不影响其它篇。"""
    try:
        return service_factory().analyze_one(text)
    except Exception:  # noqa: BLE001
        return None


def extract_pieces(
    db,
    transcripts: list[str],
    service_factory=PersonaService,
    use_cache: bool = True,
    progress=None,
) -> list[dict]:
    """把每篇文案逐篇提炼成人设信号；命中缓存的不再调用 AI。"""
    texts = [t for t in transcripts if t and t.strip()]
    if not texts:
        return []
    keys: list[str] = []
    if use_cache:
        prompt = get_prompt("persona_init", db)
        keys = [_piece_cache_key(prompt, t) for t in texts]
        cached: dict[str, dict] = {}
        for row in db.query(Kv).filter(Kv.key.in_(keys)).all():
            try:
                value = json.loads(row.value)
            except (TypeError, ValueError):
                continue
            if isinstance(value, dict):
                cached[row.key] = value
        results: list[dict | None] = [cached.get(k) for k in keys]
    else:
        cached = {}
        results = [None] * len(texts)

    todo = [i for i, r in enumerate(results) if r is None]
    total = len(todo)
    if todo:
        done = 0
        with ThreadPoolExecutor(max_workers=4) as pool:
            futures = {pool.submit(_extract_one, texts[i], service_factory): i for i in todo}
            for fut in as_completed(futures):
                results[futures[fut]] = fut.result()
                done += 1
                if progress:
                    progress(done, total)
    if use_cache and todo:
        for i, key in enumerate(keys):
            if key in cached:
                continue
            value = results[i]
            if value is None:
                continue
            db.add(Kv(key=key, value=json.dumps(value, ensure_ascii=False)))
        db.commit()
    return [r if r else empty_profile() for r in results]


def merge_profile(parts: list[dict], service_factory=PersonaService) -> dict:
    """把逐篇提炼结果归纳合并成一份档案（单独一层，便于任务分阶段报进度）。"""
    if not parts:
        return empty_profile()
    return service_factory().merge_full(parts)


def annotate_profile_stats(profile: dict, parts: list[dict], materials: list[tuple]) -> dict:
    """R-182：给合并后的 tag 补 frequency（命中素材篇数）与 last_seen_at（最后出现时间）。

    `parts` 与 `materials` 一一对应（都被 `extract_pieces`/`_owner_materials` 按同一顺序过滤）。
    """
    from .persona import label_match

    vids = [m[0] for m in materials]
    for tag in (profile or {}).get("tags") or []:
        label = str(tag.get("label", "")).strip()
        if not label:
            continue
        hits: list[int] = []
        for i, part in enumerate(parts):
            labels = [str(t.get("label", "")).strip() for t in (part or {}).get("tags") or [] if isinstance(t, dict)]
            if any(lbl and label_match(label, lbl) for lbl in labels):
                hits.append(i)
        tag["frequency"] = len(hits)
        dates = []
        for i in hits:
            if i < len(vids):
                v = vids[i]
                d = getattr(v, "published_at", None) or getattr(v, "created_at", None)
                if d:
                    dates.append(d)
        tag["last_seen_at"] = max(dates) if dates else None
    return profile


def full_profile(
    db,
    transcripts: list[str],
    service_factory=PersonaService,
    use_cache: bool = True,
    progress=None,
) -> dict:
    """从头全量分析：逐篇提取 → AI 归纳合并（总结去重）成一份完整档案。"""
    parts = extract_pieces(db, transcripts, service_factory=service_factory, use_cache=use_cache, progress=progress)
    return merge_profile(parts, service_factory=service_factory)


def incremental_profile(
    current: dict,
    new_part: dict,
    service_factory=PersonaService,
) -> dict:
    """增量操作：当前档案 + 新文案提炼结果 → 更新后的完整档案。"""
    return service_factory().merge_incremental(current or empty_profile(), new_part or empty_profile())


def profile_coverage(candidate: dict, reference: dict) -> tuple[float, list[dict]]:
    """reference(全量) 被 candidate(增量) 覆盖的比例，以及未覆盖的条目。"""
    ref_items: list[tuple[str, str]] = [
        (str(t.get("label", "")).strip(), "tag") for t in (reference or {}).get("tags") or [] if str(t.get("label", "")).strip()
    ]
    ref_items += [(str(r).strip(), "redline") for r in (reference or {}).get("redlines") or [] if str(r).strip()]
    if not ref_items:
        return 1.0, []
    cand_labels = [str(t.get("label", "")).strip() for t in (candidate or {}).get("tags") or []]
    cand_labels += [str(r).strip() for r in (candidate or {}).get("redlines") or []]
    cand_labels = [c for c in cand_labels if c]
    missing: list[dict] = []
    hit = 0
    for label, kind in ref_items:
        if any(label_match(label, c) for c in cand_labels):
            hit += 1
        else:
            missing.append({"label": label, "kind": kind})
    return hit / len(ref_items), missing


def compare_profiles(
    incremental: dict,
    full: dict,
    service_factory=PersonaService,
    threshold: float = PASS_THRESHOLD,
) -> dict:
    """增量 vs 全量：集合覆盖率 + AI 语义复核；不达标则选用全量结果。"""
    coverage, missing = profile_coverage(incremental, full)
    verdict = service_factory().compare_profiles(incremental, full)
    semantic = verdict.get("score")
    passed = coverage >= threshold and (semantic is None or semantic >= SEMANTIC_THRESHOLD)
    return {
        "coverage": round(coverage, 4),
        "semantic": semantic,
        "semantic_reason": str(verdict.get("reason", "")),
        "passed": passed,
        "fallback": not passed,
        "missing": missing,
        "chosen": incremental if passed else full,
    }


# ---------- 档案读写 ----------

_DIMENSION_CATEGORY = {"红线": "redline", "禁忌": "redline", "边界": "redline", "选题": "topic", "赛道": "topic"}


def _tag_category(dimension: str) -> str:
    return _DIMENSION_CATEGORY.get((dimension or "").strip(), "style")


def current_profile(db, cid: int | None) -> dict:
    """当前已确认人设档案（结构化，R-182 含 layer）；金句锚点不属于人设维度，不并入。"""
    q = db.query(PersonaTag).filter(PersonaTag.status == "confirmed")
    if cid:
        q = q.filter(PersonaTag.creator_id == cid)
    tags: list[dict] = []
    redlines: list[str] = []
    for t in q.order_by(PersonaTag.id).all():
        if t.category == "redline":
            redlines.append(t.label)
        elif t.category == "phrase":
            continue
        else:
            tags.append(
                {
                    "label": t.label,
                    "description": t.description or "",
                    "dimension": getattr(t, "dimension", "") or "",
                    "evidence": getattr(t, "evidence", "") or "",
                    "layer": getattr(t, "layer", "") or "stance",
                }
            )
    return {"tags": tags, "redlines": redlines}


def _existing_keys(db, cid: int | None) -> set[tuple[str, str]]:
    q = db.query(PersonaTag)
    if cid:
        q = q.filter(PersonaTag.creator_id == cid)
    keys: set[tuple[str, str]] = set()
    for t in q.all():
        if t.status in ("confirmed", "suggested"):
            keys.add((t.category, _norm_label(t.label)))
    return keys


def current_persona_version(db, cid: int | None) -> int:
    """当前人设档案版本（max PersonaTag.version）；供草稿记录生成时的人设版本（R-130）。"""
    from sqlalchemy import func

    q = db.query(func.max(PersonaTag.version))
    if cid:
        q = q.filter(PersonaTag.creator_id == cid)
    return int(q.scalar() or 0)


def _next_version(db, cid: int | None) -> int:
    return current_persona_version(db, cid) + 1


def persist_suggestions(
    db, cid: int | None, profile: dict, skip_existing: bool = True, max_items: int = 150
) -> dict:
    """把档案落库为「待确认建议」（R-182：四层 layer + evidence + 频次/最近出现）。

    已确认/待确认的同名条目跳过（被拒的可再次建议）；
    max_items 是防御性上限：AI 归纳失败退化成机械合并时可能产出几百条原始标签。
    """
    from .persona import FORBIDDEN, LAYERS, _default_layer

    existing = _existing_keys(db, cid) if skip_existing else set()
    version = _next_version(db, cid)
    added = 0
    truncated = False

    def _add(label: str, description: str, dimension: str, layer: str, evidence: str, item: dict) -> None:
        nonlocal added, truncated
        if added >= max_items:
            truncated = True
            return
        if layer not in LAYERS:
            layer = _default_layer(dimension)
        category = "redline" if layer == FORBIDDEN else _tag_category(dimension)
        key = (category, _norm_label(label))
        if skip_existing and key in existing:
            return
        existing.add(key)
        try:
            frequency = int(item.get("frequency") or 0)
        except (TypeError, ValueError):
            frequency = 0
        last_seen = item.get("last_seen_at")
        db.add(
            PersonaTag(
                creator_id=cid,
                label=label[:100],
                description=description,
                dimension=(dimension or ("红线" if layer == FORBIDDEN else ""))[:30],
                category=category,
                layer=layer,
                evidence=evidence[:200],
                frequency=max(0, frequency),
                last_seen_at=last_seen,
                confirm_strength=2,
                source="ai",
                status="suggested",
                version=version,
            )
        )
        added += 1

    for item in (profile or {}).get("tags") or []:
        if not isinstance(item, dict):
            label = str(item).strip()
            if label:
                _add(label, "", "", "stance", "", {})
            continue
        label = str(item.get("label", "")).strip()
        if not label:
            continue
        _add(
            label,
            str(item.get("description", "")).strip(),
            str(item.get("dimension", "")).strip(),
            str(item.get("layer", "")).strip(),
            str(item.get("evidence", "")).strip(),
            item,
        )
    for redline in (profile or {}).get("redlines") or []:
        label = str(redline).strip()
        if label:
            _add(label, "", "红线", FORBIDDEN, "", {})
    db.commit()
    return {"version": version, "added": added, "truncated": truncated}


__all__ = [
    "PASS_THRESHOLD",
    "SEMANTIC_THRESHOLD",
    "extract_pieces",
    "full_profile",
    "merge_profile",
    "annotate_profile_stats",
    "incremental_profile",
    "profile_coverage",
    "compare_profiles",
    "current_profile",
    "current_persona_version",
    "persist_suggestions",
    "merge_mechanical",
]
