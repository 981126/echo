"""R-245：视频复盘「按指标优化建议」——结合指标差距与文案原句给出可执行建议。

原则：
- 差距数字只用本地真实对比：当前值 vs 你自己近 30 条相近作品同发布天数中位数；
- 原因必须同时包含指标差距与文案引用（copy_refs 必须是转写稿子串）；
- 动作落到「前 3 秒 / 每 15~30 秒 / 结尾 CTA」等具体位置；
- 禁止「同赛道/行业平均/提升 X%」等无依据表述（无该数据源）；
- LLM 不可用或输出不合规 → 程序规则生成，仍带真实数字与文案引用。
"""

from __future__ import annotations

import json
import re

from sqlalchemy.orm import Session

from . import budget_settings, model_settings, prompt_contract
from .llm_router import primary_llm
from .prompt_service import get_prompt

ADVICE_DIMENSIONS: list[dict] = [
    {"dimension": "completion", "metric": "finish_rate", "title": "如何优化完播率", "target_metric": "completion"},
    {"dimension": "avg_view_proportion", "metric": "avg_view_proportion", "title": "如何优化平均播放占比", "target_metric": "retention"},
    {"dimension": "favorite_rate", "metric": "favorite_rate", "title": "如何优化收藏率", "target_metric": "engagement"},
    {"dimension": "follower_per_1k", "metric": "follower_per_1k", "title": "如何优化吸粉率", "target_metric": "followers"},
]

FALLBACK_NOTE = "按指标优化建议由程序依据真实指标与文案生成"

SYSTEM = (
    "你是短视频复盘顾问。你要同时结合『指标差距』和『视频文案原句』给出具体、可执行的优化建议。"
    "只能使用输入里给出的数字与文案原句，禁止编造任何数字、观众评论、行业均值或提升幅度。"
    "输入里的对比基准是『发布者自己近 30 条相近作品在同发布天数的中位数』，不是同赛道大盘，"
    "绝不能写成同赛道/行业平均/同类账号平均。关于内容原因的判断用『可能』表述；"
    "动作必须落到前 3 秒、每 15~30 秒、结尾 CTA 等具体位置。只输出 JSON。"
)


def _num(value: float | int | None) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _fmt_value(value: float | int | None, unit: str | None) -> str:
    number = _num(value)
    if number is None:
        return "暂无数据"
    if unit == "ratio":
        return f"{number * 100:.1f}%"
    if unit == "秒":
        return f"{number:.1f} 秒"
    if abs(number) < 10:
        return f"{number:.1f}"
    return f"{number:.0f}"


def _fmt_item(item: dict) -> str:
    return _fmt_value(item.get("value"), str(item.get("unit") or ""))


def _gap_text(item: dict) -> str:
    """真实差距说明（程序口径）。"""
    value = _num(item.get("value"))
    baseline = _num(item.get("baseline"))
    label = str(item.get("label") or "")
    sample = int(item.get("sample_count") or 0)
    if value is None:
        return f"{label}暂无数据"
    if baseline is None or sample <= 0:
        return f"当前{label} {_fmt_item(item)}（暂无可比较的历史作品）"
    diff = value - baseline
    lower_better = bool(item.get("lower_better"))
    direction = "低" if diff < 0 else "高"
    if lower_better:
        direction = "高" if diff > 0 else "低"
    if item.get("unit") == "ratio":
        diff_text = f"{abs(diff) * 100:.1f} 个百分点"
    else:
        diff_text = f"{abs(diff):.0f}"
    rel = f"，相对{direction} {abs(diff / baseline) * 100:.1f}%" if baseline else ""
    return (
        f"当前{label} {_fmt_item(item)}，你自己近 30 条相近作品在同发布天数的中位数是 "
        f"{_fmt_value(baseline, str(item.get('unit') or ''))}（{direction} {diff_text}{rel}；样本 {sample} 条）"
    )


def _sentences(transcript: str) -> list[str]:
    parts = re.split(r"[。！？!?\n]+", transcript or "")
    return [part.strip() for part in parts if len(part.strip()) >= 6]


def _pick_quotes(transcript: str, keywords: tuple[str, ...], limit: int = 3) -> list[str]:
    sentences = _sentences(transcript)
    if not sentences:
        return []
    picked = [sentence for sentence in sentences if any(key in sentence for key in keywords)]
    picked += [sentence for sentence in sentences if re.search(r"\d", sentence)]
    picked += [sentences[0], sentences[-1]]
    seen: list[str] = []
    for sentence in picked:
        if sentence not in seen:
            seen.append(sentence)
        if len(seen) >= limit:
            break
    return seen


def _advice_title(spec: dict, item: dict) -> str:
    value = _num(item.get("value_num")) if item.get("value_num") is not None else _num(item.get("value"))
    baseline = (
        _num(item.get("baseline_num")) if item.get("baseline_num") is not None else _num(item.get("baseline"))
    )
    weak = value is not None and baseline is not None and value < baseline
    title = str(spec["title"])
    if weak:
        return title
    return title.replace("如何优化", "如何继续提升")


def _should_advise(item: dict) -> bool:
    if _num(item.get("value")) is None:
        return False
    if item.get("state") == "low":
        return True
    percentile = _num(item.get("percentile"))
    return percentile is not None and percentile <= 40


def _rule_advices(comparison: dict, transcript: str) -> list[dict]:
    facts = comparison.get("facts") or {}
    sentences = _sentences(transcript)
    opening = sentences[0] if sentences else ""
    last = sentences[-1] if sentences else ""
    transcript_chars = len(re.sub(r"\s+", "", transcript or ""))
    out: list[dict] = []
    for spec in ADVICE_DIMENSIONS:
        item = facts.get(spec["metric"])
        if not isinstance(item, dict) or not _should_advise(item):
            continue
        dimension = str(spec["dimension"])
        gap_text = _gap_text(item)
        if dimension == "completion":
            quotes = _pick_quotes(transcript, ("开头", "首先", "大家", "今天", "结果", "最后"))
            reasons = [gap_text]
            if opening:
                reasons.append(f"从文案看，视频开头是「{opening}」，可能是先铺垫背景、冲突信息出现偏晚。")
            actions = [
                f"把最冲突或最想要的结果前置到前 3 秒：现在是「{opening[:50]}」，可以先给结果或悬念，再补背景。",
                "按每 15~20 秒一个信息点拆节奏：每个节点给一个明确的小结论，避免连续铺垫和重复解释。",
                "中段删掉重复的总结，只保留一个核心问题；结尾提前收束，不要把结论压到最后 10 秒。",
            ]
        elif dimension == "avg_view_proportion":
            quotes = _pick_quotes(transcript, ("然后", "后来", "其实", "因为", "所以", "结果"))
            reasons = [gap_text]
            if transcript_chars:
                reasons.append(f"文案约 {transcript_chars} 字、叙述密度较高，长段落容易变成连续对镜讲，观众可能中途划走。")
            actions = [
                "减少连续对镜干讲：每隔约 30 秒插入一段实拍素材或截图（账单/后台数据/实物画面），让画面有变化。",
                "在每个信息点结尾抛一个轻问题（例如「你们有没有类似经历？」），让观众停下来思考或留言。",
                "每个小节点先给结论再解释，避免大段铺垫；讲完一个点就换画面或换场景。",
            ]
        elif dimension == "favorite_rate":
            quotes = _pick_quotes(transcript, ("经验", "建议", "方法", "技巧", "坑", "万", "块", "钱"))
            reasons = [gap_text]
            if quotes:
                reasons.append(f"文案主要是个人经历叙述（如「{quotes[0]}」），缺少可直接照做的清单或步骤。")
            actions = [
                "提炼 3 条可直接照做的清单/避坑准则：把亲身踩坑经历改写成「普通人可以照做」的步骤。",
                "视频结尾加一页可视化清单或进度表（目标/预算/步骤标清楚），给观众一个收藏回看的理由。",
                "在讲到关键经验时明确说一句「这条可以直接收藏照着做」，降低观众收藏的心理门槛。",
            ]
        else:
            quotes = _pick_quotes(transcript, ("关注", "后续", "更新", "系列", "下一条", "下次"))
            reasons = [gap_text]
            if last:
                reasons.append(f"文案结尾是「{last}」，缺少「关注后还能看到什么」的明确承诺。")
            actions = [
                "结尾加约 10 秒关注理由：明确后续会持续更新哪一类内容、帮哪类人解决什么问题。",
                "给粉丝专属权益：整理一份同主题清单/资料，关注后在评论区或私信领取。",
                "主页简介与置顶内容承接同一方向，让看完视频的人知道关注后还能看什么。",
            ]
        out.append(
            {
                "dimension": dimension,
                "title": _advice_title(spec, item),
                "target_metric": str(spec["target_metric"]),
                "gap": gap_text,
                "judgement_type": "hypothesis",
                "reasons": reasons[:3],
                "actions": actions[:4],
                "copy_refs": quotes[:3],
                "evidence": [gap_text],
            }
        )
    return out


def _brief(comparison: dict, transcript: str, comments_questions: list[dict], post_title: str) -> dict:
    facts = comparison.get("facts") or {}
    metrics: list[dict] = []
    for spec in ADVICE_DIMENSIONS:
        item = facts.get(spec["metric"])
        if not isinstance(item, dict) or _num(item.get("value")) is None:
            continue
        metrics.append(
            {
                "dimension": spec["dimension"],
                "label": item.get("label"),
                "value": _fmt_item(item),
                "value_num": _num(item.get("value")),
                "baseline": _fmt_value(item.get("baseline"), str(item.get("unit") or "")),
                "baseline_num": _num(item.get("baseline")),
                "unit": item.get("unit"),
                "gap_text": _gap_text(item),
                "percentile": item.get("percentile"),
                "sample_count": item.get("sample_count"),
                "state": item.get("state"),
            }
        )
    return {
        "video_title": post_title,
        # 允许动作里使用的时间点数字（前 3 秒/每 15~30 秒/结尾 10 秒），不视为编造数字
        "time_hints": "前 3 秒 / 每 15~30 秒 / 结尾 10 秒",
        "transcript": (transcript or "")[:3000],
        "transcript_chars": len(re.sub(r"\s+", "", transcript or "")),
        "metrics": metrics,
        "comment_questions": [
            str(item.get("group_title") or "") for item in comments_questions[:5] if item.get("group_title")
        ],
    }


def _allowed_numbers(brief: dict) -> set[str]:
    return set(re.findall(r"\d+(?:\.\d+)?", json.dumps(brief, ensure_ascii=False, default=str)))


def _valid_candidates(candidates: list, brief: dict) -> list[dict]:
    """校验 LLM 输出：维度白名单、动作/原因条数、数字白名单、文案引用必须是子串。"""
    transcript = str(brief.get("transcript") or "")
    allowed = _allowed_numbers(brief)
    by_dimension = {str(spec["dimension"]): spec for spec in ADVICE_DIMENSIONS}
    metrics = {str(item["dimension"]): item for item in brief.get("metrics") or []}
    out: list[dict] = []
    seen: set[str] = set()
    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        dimension = str(candidate.get("dimension") or "")
        spec = by_dimension.get(dimension)
        if spec is None or dimension in seen or dimension not in metrics:
            continue
        actions = [str(value).strip() for value in (candidate.get("actions") or []) if str(value).strip()]
        reasons = [str(value).strip() for value in (candidate.get("reasons") or []) if str(value).strip()]
        refs = [str(value).strip() for value in (candidate.get("copy_refs") or []) if str(value).strip()]
        if len(actions) < 2 or not reasons:
            continue
        text = json.dumps(candidate, ensure_ascii=False)
        if any(number not in allowed for number in re.findall(r"\d+(?:\.\d+)?", text)):
            continue
        valid_refs = [ref for ref in refs if ref in transcript]
        if not valid_refs:
            continue
        gap = str(metrics[dimension].get("gap_text") or "")
        out.append(
            {
                "dimension": dimension,
                "title": _advice_title(spec, metrics[dimension]),
                "target_metric": str(spec["target_metric"]),
                "gap": gap,
                "judgement_type": "hypothesis",
                "reasons": reasons[:4],
                "actions": actions[:5],
                "copy_refs": valid_refs[:3],
                "evidence": [gap],
            }
        )
        seen.add(dimension)
    return out


def build_metric_advices(
    db: Session,
    comparison: dict,
    transcript: str,
    comments_questions: list[dict],
    post_title: str = "",
) -> tuple[list[dict], str, str]:
    """生成按指标优化建议；返回 (advices, model_name, warning)。"""
    fallback = _rule_advices(comparison, transcript)
    slots = model_settings.resolve_slots(db)
    if not any(slot.get("api_key") for slot in slots.values()):
        return fallback, "", FALLBACK_NOTE
    brief = _brief(comparison, transcript, comments_questions, post_title)
    if not brief["metrics"]:
        return fallback, "", FALLBACK_NOTE
    try:
        llm = primary_llm(db, "video_review", target="/video-review")
        result = llm.chat_json(
            [
                {"role": "system", "content": get_prompt("video_review_advice", db)},
                {
                    "role": "user",
                    "content": (
                        "请生成「按指标优化建议」并只输出 JSON。要求：\n"
                        "1) 最多 4 条，dimension 只能取 completion / avg_view_proportion / favorite_rate / follower_per_1k；\n"
                        "2) 每条同时结合指标差距和文案原句：reasons 引用指标差距，copy_refs 必须是 transcript 原句（原样摘录，不得改写）；\n"
                        "3) actions 写 3~4 条具体动作，落到前 3 秒 / 每 15~30 秒 / 结尾 CTA 等位置，不要空话；\n"
                        "4) 只能使用输入里的数字，不得写同赛道/行业平均，不得承诺提升百分比；内容原因用「可能」表述；\n"
                        "5) 没有可比数据的 dimension 不生成。\n"
                        f"{prompt_contract.contract_for('video_review_advice')}\n"
                        f"输入：{json.dumps(brief, ensure_ascii=False)}"
                    ),
                },
            ],
            temperature=0.3,
            max_tokens=budget_settings.budget_for(db, "video_review"),
            require=("advices",),
        )
        valid = _valid_candidates(list(result.get("advices") or []), brief)
        if valid:
            return valid, llm.used_model, ""
        return fallback, llm.used_model, "AI 建议未通过校验，已改用程序依据真实数据生成的建议"
    except Exception as exc:  # noqa: BLE001
        return fallback, "", f"AI 建议暂不可用，已使用程序建议：{str(exc)[:120]}"
