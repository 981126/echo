"""R-265：留存曲线掉点 → 句子对齐（纯函数，便于单测）。

口径（与 `development-design/R-265-retention-timeline-diagnosis.md` 一致）：
- 相邻曲线点：`跌幅 ≥ 5 个百分点` 且 `相对跌幅 ≥ 8%` 才算掉点；
- 相邻两段都命中时合并为一段（跨度 ≤ 2 个间隔），跌幅按首尾差计算，不累加；
- 按跌幅降序取前 3，一句话只归属一次；
- 句子窗口加 ±0.5s 容差，取交集最大的一句；`precision != sentence` 时不指认句子。
"""

from __future__ import annotations

from statistics import median

ABS_DROP_MIN = 0.05  # 5 个百分点
REL_DROP_MIN = 0.08  # 相对 8%
MAX_DROPS = 3
SENTENCE_PAD_SECONDS = 0.5
LOW_PLAYS = 200
HOOK_END_SECONDS = 10
TAIL_RATIO = 0.8


def _label(seconds: float) -> str:
    total = max(0, int(round(seconds)))
    return f"{total // 60:02d}:{total % 60:02d}"


def _merge_hits(hits: list[int]) -> list[list[int]]:
    """把命中的相邻点序号分组；每组最多合并 2 段（跨度 ≤ 2 个间隔）。"""
    groups: list[list[int]] = []
    for index in hits:
        if groups and index == groups[-1][-1] + 1 and len(groups[-1]) < 2:
            groups[-1].append(index)
        else:
            groups.append([index])
    return groups


def _match_sentence(
    start: float, end: float, sentences: list[dict]
) -> dict | None:
    best: dict | None = None
    best_overlap = 0.0
    for sentence in sentences:
        start_ms = sentence.get("start_ms")
        end_ms = sentence.get("end_ms")
        if not isinstance(start_ms, (int, float)) or not isinstance(end_ms, (int, float)):
            continue
        begin = float(start_ms) / 1000 - SENTENCE_PAD_SECONDS
        finish = float(end_ms) / 1000 + SENTENCE_PAD_SECONDS
        text = str(sentence.get("text") or "").strip()
        if not text:
            continue
        overlap = min(end, finish) - max(start, begin)
        if overlap > best_overlap:
            best_overlap = overlap
            best = {"text": text, "start_ms": int(sentence["start_ms"]), "end_ms": int(sentence["end_ms"])}
    return best


def _category(start: float, end: float, duration_seconds: int | None) -> str:
    if end <= HOOK_END_SECONDS:
        return "hook"
    if duration_seconds and start >= duration_seconds * TAIL_RATIO:
        return "tail"
    return "body"


def align_drops(
    points: list[dict],
    sentences: list[dict] | None,
    precision: str,
    plays: int | None,
    reliable: bool,
    duration_seconds: int | None = None,
) -> tuple[list[dict], str]:
    """返回 (drops, reason)；reason=ok 表示正常，其它值说明为何没有结果。"""
    valid = [
        point
        for point in points or []
        if isinstance(point, dict)
        and isinstance(point.get("current"), (int, float))
        and isinstance(point.get("time_seconds"), (int, float))
    ]
    if not reliable:
        return [], "unreliable"
    if len(valid) < 5:
        return [], "few_points"
    if plays is None or int(plays) < LOW_PLAYS:
        return [], "low_plays"

    # 第 0 秒恒为 1（曲线归一化起点），它的跌幅就是「2 秒内跳出」，已有 2 秒跳出率指标覆盖，
    # 不参与句级掉点判定，避免一条毫无信息量的 00:00–00:02 淹没真正的中段流失。
    start_index = 1 if valid[0]["time_seconds"] == 0 and abs(float(valid[0]["current"]) - 1.0) < 1e-6 else 0

    hits: list[int] = []
    for index in range(start_index, len(valid) - 1):
        before = float(valid[index]["current"])
        after = float(valid[index + 1]["current"])
        drop = before - after
        if drop >= ABS_DROP_MIN and drop / max(before, 1e-6) >= REL_DROP_MIN:
            hits.append(index)

    candidates: list[dict] = []
    for group in _merge_hits(hits):
        first = valid[group[0]]
        last = valid[group[-1] + 1]
        start = float(first["time_seconds"])
        end = float(last["time_seconds"])
        drop = float(first["current"]) - float(last["current"])
        candidates.append(
            {
                "start_seconds": int(round(start)),
                "end_seconds": int(round(end)),
                "time_label": f"{_label(start)}–{_label(end)}",
                "drop": round(drop, 4),
                "drop_ratio": round(drop / max(float(first["current"]), 1e-6), 4),
                "category": _category(start, end, duration_seconds),
            }
        )

    candidates.sort(key=lambda item: item["drop"], reverse=True)
    usable = sentences if precision == "sentence" and sentences else []
    used: set[str] = set()
    out: list[dict] = []
    for candidate in candidates:
        if len(out) >= MAX_DROPS:
            break
        sentence = None
        if usable:
            matched = _match_sentence(candidate["start_seconds"], candidate["end_seconds"], usable)
            if matched is not None and matched["text"] not in used:
                sentence = matched
                used.add(matched["text"])
        confidence = "sentence" if sentence else ("window" if precision in ("sentence", "chunk") else "none")
        out.append({**candidate, "sentence": sentence, "confidence": confidence})
    return out, "ok"


def summarize_drops(drops: list[dict]) -> str:
    """给 LLM 的一句话摘要（数字来自程序，避免模型自造）。"""
    if not drops:
        return ""
    top = drops[0]
    return f"流失最大的一段在 {top['time_label']}，下降 {top['drop'] * 100:.1f} 个百分点"


def median_drop(points: list[dict]) -> float:
    """曲线相邻点跌幅中位数（用于判断“明显掉点”，保留给调用方参考）。"""
    values = [
        float(a["current"]) - float(b["current"])
        for a, b in zip(points, points[1:])
        if isinstance(a.get("current"), (int, float)) and isinstance(b.get("current"), (int, float))
    ]
    return float(median(values)) if values else 0.0
