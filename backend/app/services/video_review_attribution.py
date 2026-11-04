"""R-248：视频复盘「这条视频为什么好或差」AI 归因。

流程：程序先算全部真实指标事实（brief）→ 单次 LLM 结合指标/文案/评论生成 2~5 条归因 →
程序校验（维度白名单 / 数字白名单 / 文案与评论真实子串 / 条数）→ 程序按真实指标 state
判定方向 verdict、构造 metric_evidence/content_evidence → 不合规/模型不可用回退规则结论。
不新增 LLM 调用次数：替换 R-237 的 `enhance_findings` 润色调用，仍用 video_review 用途与预算。
"""

from __future__ import annotations

import json
import re

from sqlalchemy.orm import Session

from ..models.platform import PlatformPostComment
from . import budget_settings, model_settings
from .llm_router import primary_llm
from .prompt_service import get_prompt
from .video_review_advices import _allowed_numbers, _fmt_value, _gap_text, _num

# 维度白名单：维度 → 该维度下可用于归因的真实指标
FACT_DIMENSIONS: dict[str, tuple[str, ...]] = {
    "plays": ("plays", "cover_click_rate"),
    "engagement": ("likes", "comments", "favorites", "shares", "like_rate", "favorite_rate"),
    "completion": (
        "bounce_2s_rate",
        "finish_5s_rate",
        "finish_rate",
        "avg_play_seconds",
        "avg_view_proportion",
    ),
    "followers": ("profile_visits", "follower_gain", "follower_per_1k"),
}
_DIMENSION_OF = {key: dimension for dimension, keys in FACT_DIMENSIONS.items() for key in keys}
MAX_FINDINGS = 5
MAX_TRANSCRIPT = 3000
MAX_COMMENTS = 20

# 允许在建议/结论里出现的时间点数字（不视为编造数字）
TIME_HINTS = "前 3 秒 / 每 15~30 秒 / 结尾 10 秒"

SYSTEM = (
    "你是短视频复盘助手。只能根据输入的真实指标、视频文案原句和评论原文解释这条视频为什么好或差，"
    "不得创造数字、经历、评论、行业均值或提升幅度。数据事实与内容推测必须区分；"
    "样本少时不得断言整体好坏。建议必须具体、直白、可执行。只输出 JSON。"
)

FALLBACK_NOTE = "AI 归因暂不可用，已使用程序依据真实数据生成的原因"
VALIDATION_NOTE = "AI 归因未通过校验，已使用程序依据真实数据生成的原因"


def verdict_for(metric_keys: list[str], facts: dict[str, dict]) -> str:
    """由程序按真实指标状态判方向：high→strength、low→weak、样本不足/无指标→unknown、其余 neutral。"""
    valid = [
        key
        for key in metric_keys
        if isinstance(facts.get(key), dict) and _num(facts[key].get("value")) is not None
    ]
    states = [str(facts[key].get("state") or "") for key in valid]
    if not states:
        return "unknown"
    if "high" in states:
        return "strength"
    if "low" in states:
        return "weak"
    if all(
        (facts[key].get("sample_count") or 0) < 5 or facts[key].get("state") == "missing"
        for key in valid
    ):
        return "unknown"
    return "neutral"


def _has_available(dimension: str, facts: dict[str, dict]) -> bool:
    """该维度下是否至少有一项真实可用的指标（有 value）。"""
    return any(
        isinstance(facts.get(key), dict) and _num(facts[key].get("value")) is not None
        for key in FACT_DIMENSIONS[dimension]
    )


def _metric_evidence(key: str, item: dict) -> dict:
    return {
        "evidence_id": f"metric:{key}",
        "key": key,
        "label": item.get("label"),
        "value": item.get("value"),
        "baseline": item.get("baseline"),
        "unit": item.get("unit"),
        "state": item.get("state"),
        "sample_count": item.get("sample_count"),
    }


def _retention_drops(comparison: dict) -> list[dict]:
    """观看趋势里下降最大的前 3 个点；趋势不可靠时不给（避免拿噪声当证据）。"""
    retention = (comparison.get("charts") or {}).get("retention") or {}
    if not retention.get("reliable"):
        return []
    points = [
        point
        for point in retention.get("points") or []
        if isinstance(point, dict) and isinstance(point.get("current"), (int, float))
    ]
    drops: list[dict] = []
    for before, after in zip(points, points[1:]):
        drop = float(before["current"]) - float(after["current"])
        if drop > 0:
            drops.append({"time": str(after.get("time_label") or ""), "drop": round(drop, 4)})
    return sorted(drops, key=lambda item: item["drop"], reverse=True)[:3]


def _comment_texts(comments: list[PlatformPostComment]) -> list[str]:
    """按点赞取 top 评论原文（用于 brief 与引用校验）。"""
    ordered = sorted(comments, key=lambda comment: int(comment.likes or 0), reverse=True)
    texts: list[str] = []
    for comment in ordered[:MAX_COMMENTS]:
        text = (comment.text or "").strip()
        if text:
            texts.append(text)
    return texts


def _brief(
    comparison: dict,
    transcript: str,
    comments: list[PlatformPostComment],
    questions: list[dict],
    rule_findings: list[dict],
    post_title: str,
) -> dict:
    facts = comparison.get("facts") or {}
    metrics: list[dict] = []
    for key, item in facts.items():
        if not isinstance(item, dict) or _num(item.get("value")) is None:
            continue
        metrics.append(
            {
                "key": key,
                "label": item.get("label"),
                "value": item.get("value"),
                "unit": item.get("unit"),
                "baseline": item.get("baseline"),
                "percentile": item.get("percentile"),
                "state": item.get("state"),
                "sample_count": item.get("sample_count"),
                "gap_text": _gap_text(item),
            }
        )
    return {
        "video_title": post_title,
        "transcript": (transcript or "")[:MAX_TRANSCRIPT],
        "transcript_chars": len(re.sub(r"\s+", "", transcript or "")),
        "metrics": metrics,
        "retention_drops": _retention_drops(comparison),
        "comment_questions": [
            str(item.get("group_title") or "") for item in questions[:5] if item.get("group_title")
        ],
        "comments": _comment_texts(comments),
        "existing_findings": [
            {"title": finding.get("title"), "conclusion": finding.get("conclusion")}
            for finding in rule_findings
        ],
        "time_hints": TIME_HINTS,
    }


def _prompt(brief: dict) -> str:
    return (
        "请为这条抖音视频生成「这条视频为什么好或差」的归因，只输出 JSON。要求：\n"
        "1) 共 2~5 条；每条 dimension 只能取 plays / engagement / completion / followers；\n"
        "2) 每条至少引用 1 个真实指标（metric_keys 取自输入 metrics 的 key）或 1 条真实原句"
        "（content_quotes 必须是输入 transcript 或 comments 里连续的原样摘录，不得改写、拼接）；\n"
        "3) title 一句话结论（不超过 300 字）；conclusion 2~4 句，必须结合真实指标差距与文案/评论内容；"
        "suggestion 写清下一条具体怎么改（可执行动作）；\n"
        "4) 只能使用输入里出现的数字，不得新增数字、经历、评论、行业均值或提升幅度；"
        "内容层面的原因用「可能」表述；样本少（state=limited 或 sample_count<5）时不得断言整体好坏；\n"
        "5) 指标 value 为 null 的视为没有数据，不要引用；没有内容依据时 content_quotes 传空数组。\n"
        '输出：{"findings":[{"dimension":"completion","title":"...","conclusion":"...",'
        '"suggestion":"...","judgement_type":"fact|hypothesis","metric_keys":["finish_rate"],'
        '"content_quotes":["...原句..."]}]}\n'
        f"输入：{json.dumps(brief, ensure_ascii=False, default=str)}"
    )


def _valid_candidates(
    candidates: list,
    brief: dict,
    facts: dict[str, dict],
    transcript: str,
    comment_texts: list[str],
) -> list[dict]:
    """校验 LLM 输出并补齐程序判定：维度/指标真实性、数字白名单、文案与评论子串、条数上限。"""
    allowed = _allowed_numbers(brief)
    out: list[dict] = []
    for candidate in candidates:
        if not isinstance(candidate, dict) or len(out) >= MAX_FINDINGS:
            continue
        dimension = str(candidate.get("dimension") or "").strip()
        if dimension not in FACT_DIMENSIONS or not _has_available(dimension, facts):
            continue
        title = str(candidate.get("title") or "").strip()[:300]
        conclusion = str(candidate.get("conclusion") or "").strip()
        suggestion = str(candidate.get("suggestion") or "").strip()
        if not title or not conclusion or not suggestion:
            continue
        metric_keys: list[str] = []
        for key in candidate.get("metric_keys") or []:
            name = str(key)
            if name in facts and _num(facts[name].get("value")) is not None and name not in metric_keys:
                metric_keys.append(name)
        quotes: list[str] = []
        for quote in candidate.get("content_quotes") or []:
            text = str(quote).strip()
            if text and (text in (transcript or "") or any(text in item for item in comment_texts)):
                quotes.append(text)
        if not metric_keys and not quotes:
            continue
        text = "\n".join((title, conclusion, suggestion))
        if any(number not in allowed for number in re.findall(r"\d+(?:\.\d+)?", text)):
            continue
        content_evidence = [
            {
                "evidence_id": f"content:quote:{index}",
                "text": quote,
                "source": "视频文案" if quote in (transcript or "") else "评论",
            }
            for index, quote in enumerate(quotes[:3], 1)
        ]
        out.append(
            {
                "dimension": dimension,
                "rule_key": f"attribution:{dimension}:{len(out) + 1}"[:60],
                "title": title,
                "judgement_type": "hypothesis" if content_evidence else "fact",
                "verdict": verdict_for(metric_keys, facts),
                "conclusion": conclusion,
                "suggestion": suggestion,
                "target_metric": dimension,
                "metric_evidence": [_metric_evidence(key, facts[key]) for key in metric_keys],
                "content_evidence": content_evidence,
                "comparison_post_ids": [],
            }
        )
    return out


def _fallback_finding(comparison: dict) -> dict:
    """规则也没有结论时，至少给 1 条「暂时还不能判断整体好坏」的说明（含真实样本数与差异最大指标）。"""
    facts = comparison.get("facts") or {}
    sample = int((facts.get("plays") or {}).get("sample_count") or 0)
    comparable: list[tuple[str, dict]] = [
        (key, item)
        for key, item in facts.items()
        if isinstance(item, dict)
        and _num(item.get("value")) is not None
        and _num(item.get("baseline")) is not None
    ]

    def gap_ratio(pair: tuple[str, dict]) -> float:
        item = pair[1]
        value, baseline = float(item["value"]), float(item["baseline"])
        return abs(value - baseline) / max(abs(baseline), 1e-9)

    comparable.sort(key=gap_ratio, reverse=True)
    top = comparable[:2]
    if top:
        parts = []
        for key, item in top:
            unit = str(item.get("unit") or "")
            sample_count = int(item.get("sample_count") or 0)
            parts.append(
                f"{item.get('label')} {_fmt_value(item.get('value'), unit)}"
                f"（你自己平时 {_fmt_value(item.get('baseline'), unit)}，样本 {sample_count} 条）"
            )
        if sample < 5:
            head = f"可比较的历史作品只有 {sample} 条，样本少于 5 条，暂时还不能判断整体好坏。"
        else:
            head = f"可比较的历史作品 {sample} 条，各项指标与平时差异不大，暂时还不能判断整体好坏。"
        conclusion = f"{head}目前能看到的差异是：{'；'.join(parts)}。"
        dimension = _DIMENSION_OF.get(top[0][0], "plays")
        metric_evidence = [_metric_evidence(key, item) for key, item in top]
    else:
        conclusion = "暂无可比较的历史作品和足够指标，暂时还不能判断整体好坏。"
        dimension = "plays"
        metric_evidence = []
    return {
        "dimension": dimension,
        "rule_key": "attribution:fallback",
        "title": "暂时还不能判断整体好坏",
        "judgement_type": "fact",
        "verdict": "unknown",
        "conclusion": conclusion,
        "suggestion": "继续发布并同步数据，样本 ≥5 条后重新分析，原因会更可靠。",
        "target_metric": dimension,
        "metric_evidence": metric_evidence,
        "content_evidence": [],
        "comparison_post_ids": [],
    }


def _rule_findings(rule_findings: list[dict], facts: dict[str, dict]) -> list[dict]:
    """规则 findings 兜底：程序按其真实指标状态补 verdict，逻辑与阈值不变。"""
    out: list[dict] = []
    for finding in rule_findings:
        item = dict(finding)
        keys = [
            str(evidence.get("key"))
            for evidence in item.get("metric_evidence") or []
            if isinstance(evidence, dict) and evidence.get("key")
        ]
        item["verdict"] = verdict_for(keys, facts)
        out.append(item)
    return out


def build_attribution(
    db: Session,
    comparison: dict,
    transcript: str,
    comments: list[PlatformPostComment],
    questions: list[dict],
    rule_findings: list[dict],
    post_title: str = "",
) -> tuple[list[dict], str, str]:
    """生成「为什么好/差」归因；返回 (findings, model_name, warning)。"""
    facts = comparison.get("facts") or {}
    fallback = _rule_findings(rule_findings, facts)
    slots = model_settings.resolve_slots(db)
    if not any(slot.get("api_key") for slot in slots.values()):
        return (fallback or [_fallback_finding(comparison)]), "", FALLBACK_NOTE
    brief = _brief(comparison, transcript, comments, questions, rule_findings, post_title)
    try:
        llm = primary_llm(db, "video_review", target="/video-review")
        result = llm.chat_json(
            [
                {"role": "system", "content": get_prompt("video_review", db) or SYSTEM},
                {"role": "user", "content": _prompt(brief)},
            ],
            temperature=0.3,
            max_tokens=budget_settings.budget_for(db, "video_review"),
            require=("findings",),
        )
    except Exception as exc:  # noqa: BLE001 模型不可用时回退规则结论
        return (fallback or [_fallback_finding(comparison)]), "", f"{FALLBACK_NOTE}（{str(exc)[:120]}）"
    valid = _valid_candidates(
        list(result.get("findings") or []),
        brief,
        facts,
        transcript,
        _comment_texts(comments),
    )
    if len(valid) >= 2:
        return valid[:MAX_FINDINGS], llm.used_model, ""
    if valid:
        merged = (valid + fallback)[:MAX_FINDINGS]
        if len(merged) < 2:
            merged.append(_fallback_finding(comparison))
        return merged[:MAX_FINDINGS], llm.used_model, ""
    return (fallback or [_fallback_finding(comparison)]), llm.used_model, VALIDATION_NOTE
