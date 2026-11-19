"""普通生成的程序契约与质量门禁（R-263）。"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any


class GenerationValidationError(ValueError):
    """模型候选不满足程序契约，可带原因进入针对修订。"""


def json_dict(raw: str | None) -> dict[str, Any]:
    try:
        value = json.loads(raw or "{}")
    except (TypeError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def json_list(raw: str | None) -> list[Any]:
    try:
        value = json.loads(raw or "[]")
    except (TypeError, ValueError):
        return []
    return value if isinstance(value, list) else []


def script_hash(script: str) -> str:
    return hashlib.sha256((script or "").encode("utf-8")).hexdigest()


def _text(value: Any) -> str:
    return str(value or "").strip()


def _score(value: Any) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise GenerationValidationError("角度评分必须是数字") from exc
    if not 0 <= number <= 25:
        raise GenerationValidationError("角度单项评分必须在 0～25 之间")
    return number


def validate_angles(
    raw: Any,
    *,
    asset_ids: set[int],
    asset_kinds: dict[int, str],
    online_source_ids: set[str],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[str]]:
    if not isinstance(raw, dict) or not isinstance(raw.get("angles"), list):
        raise GenerationValidationError("角度结果缺少 angles 数组")
    accepted: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    promises: set[str] = set()
    for index, item in enumerate(raw["angles"][:3], 1):
        if not isinstance(item, dict):
            continue
        angle = dict(item)
        angle["angle_id"] = _text(angle.get("angle_id")) or f"a{index}"
        reasons: list[str] = []
        for field in ("title", "audience", "promise", "hook"):
            if not _text(angle.get(field)):
                reasons.append(f"缺少 {field}")
        if not isinstance(angle.get("reasoning"), list) or not angle["reasoning"]:
            reasons.append("缺少推理步骤")
        promise_key = re.sub(r"\s+", "", _text(angle.get("promise")))
        if promise_key and promise_key in promises:
            reasons.append("与其他角度核心承诺重复")
        try:
            scores = {
                key: _score(angle.get(key))
                for key in ("author_fit", "evidence_fit", "audience_value", "distinctiveness")
            }
        except GenerationValidationError as exc:
            reasons.append(str(exc))
            scores = {}
        total = sum(scores.values())
        if scores and total < 65:
            reasons.append(f"总分 {total:g} 低于 65")
        required = angle.get("required_asset_ids")
        if not isinstance(required, list):
            reasons.append("required_asset_ids 必须是数组")
            required = []
        try:
            required_ids = {int(value) for value in required}
        except (TypeError, ValueError):
            required_ids = set()
            reasons.append("资产 ID 不是整数")
        if not required_ids.issubset(asset_ids):
            reasons.append("引用了未选中或不属于当前作者的资产")
        external_ids = {_text(value) for value in angle.get("external_source_ids") or []}
        if not external_ids.issubset(online_source_ids):
            reasons.append("引用了不存在的外部来源")
        claim_type = _text(angle.get("claim_type")) or "inference"
        if claim_type not in {"author_experience", "external_fact", "inference", "opinion"}:
            reasons.append("未知角度主张类型")
        if claim_type == "author_experience" and not any(
            asset_kinds.get(asset_id) == "experience" for asset_id in required_ids
        ):
            reasons.append("个人经历角度没有作者经历资产")
        if claim_type in {"author_experience", "external_fact"} and not required_ids and not external_ids:
            reasons.append("事实角度没有证据")
        angle["claim_type"] = claim_type
        angle["required_asset_ids"] = sorted(required_ids)
        angle["external_source_ids"] = sorted(external_ids)
        angle["total_score"] = total
        if reasons:
            rejected.append({**angle, "reject_reasons": reasons})
            continue
        promises.add(promise_key)
        accepted.append(angle)
    questions = [_text(value) for value in raw.get("questions") or [] if _text(value)][:3]
    return accepted, rejected, questions


def validate_blueprint(
    raw: Any,
    *,
    angle: dict[str, Any],
    asset_ids: set[int],
    online_source_ids: set[str],
) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise GenerationValidationError("蓝图不是 JSON 对象")
    problems: list[str] = []
    for field in ("goal", "audience", "core_promise", "ending"):
        if not _text(raw.get(field)):
            problems.append(f"缺少 {field}")
    if angle.get("promise") and _text(raw.get("core_promise")) != _text(angle.get("promise")):
        problems.append("核心承诺与选中角度不一致")
    hook = raw.get("hook")
    if not isinstance(hook, dict) or not _text(hook.get("text")) or not _text(hook.get("payoff")):
        problems.append("开头及兑现位置不能为空")
    steps = raw.get("reasoning_steps")
    if not isinstance(steps, list) or not steps:
        problems.append("推理步骤不能为空")
        steps = []
    valid_types = {"author_experience", "external_fact", "inference", "opinion"}
    for step in steps:
        if not isinstance(step, dict):
            problems.append("推理步骤格式错误")
            continue
        if not _text(step.get("claim")) or not _text(step.get("inference")):
            problems.append("推理步骤缺少结论或证据关系")
        claim_type = _claim_type(step.get("claim_type"))
        step["claim_type"] = claim_type
        if claim_type not in valid_types:
            problems.append("推理步骤主张类型错误")
        ids = step.get("evidence_ids")
        if (ids is None or (isinstance(ids, list) and not ids)) and claim_type in {"inference", "opinion"}:
            ids = ["input:topic"] if claim_type == "inference" else []
        elif not isinstance(ids, list):
            problems.append("推理步骤 evidence_ids 必须是数组")
            ids = []
        step["evidence_ids"] = ids
        numeric_ids = {value for value in ids if isinstance(value, int)}
        external_ids = {_text(value) for value in ids if isinstance(value, str)}
        if not numeric_ids.issubset(asset_ids) or not external_ids.issubset(online_source_ids | {"input:topic"}):
            problems.append("推理步骤引用未知证据")
        if claim_type in {"author_experience", "external_fact"} and not ids:
            problems.append("事实或经历步骤没有证据")
        if claim_type == "inference" and not _text(step.get("limitations")):
            problems.append("推论步骤缺少边界或反例")
    actions = raw.get("actions")
    if not isinstance(actions, list):
        problems.append("actions 必须是数组")
        actions = []
    for action in actions:
        if not isinstance(action, dict) or any(
            not _text(action.get(field)) for field in ("precondition", "action", "expected_result")
        ):
            problems.append("每条建议必须包含前提、行动和不超证据的预期结果")
    if problems:
        raise GenerationValidationError("；".join(dict.fromkeys(problems)))
    return raw


_ARABIC_NUMBER = re.compile(r"(?<![A-Za-z0-9])\d+(?:,\d{3})*(?:\.\d+)?\s*(?:%|％|元|块|米|公里|岁|年|月|日|天|次|个|条|篇|倍|小时|分钟|秒|人|台|步|分)?")
_CHINESE_NUMBER = re.compile(
    r"[零一二三四五六七八九十百千万亿两]{2,}\s*(?:%|％|元|块|米|公里|岁|年|月|日|天|次|个|条|篇|倍|小时|分钟|秒|人|台|步|分)?"
)


_VAGUE_QUANTITIES = {"一个", "两个", "几个", "一两个", "两三个"}


def extract_numbers(text: str) -> list[str]:
    values = _ARABIC_NUMBER.findall(text or "") + _CHINESE_NUMBER.findall(text or "")
    normalized = [re.sub(r"\s+", "", value) for value in values]
    return list(dict.fromkeys(value for value in normalized if value not in _VAGUE_QUANTITIES))


def _calculation_numbers(text: str) -> set[str]:
    allowed: set[str] = set()
    for left, operator, right in re.findall(r"(\d+(?:\.\d+)?)\s*([+\-*/×÷])\s*(\d+(?:\.\d+)?)", text or ""):
        a, b = float(left), float(right)
        if operator == "+":
            result = a + b
        elif operator == "-":
            result = a - b
        elif operator in {"*", "×"}:
            result = a * b
        elif b:
            result = a / b
        else:
            continue
        allowed.update({left, right})
        allowed.add(str(int(result) if result.is_integer() else round(result, 6)))
    return allowed


def _number_key(value: str) -> str:
    return re.sub(r"(?:人民币|块钱|块|元)$", "", value.replace(",", "").replace(" ", ""))


_CLAIM_TYPE_ALIASES = {
    "experience": "author_experience",
    "personal_experience": "author_experience",
    "author_experiences": "author_experience",
    "fact": "external_fact",
    "factual": "external_fact",
    "external_facts": "external_fact",
    "analysis": "inference",
    "reasoning": "inference",
    "deduction": "inference",
    "personal_opinion": "opinion",
    "author_opinion": "opinion",
    "viewpoint": "opinion",
}


def _claim_type(value: Any) -> str:
    raw = _text(value)
    return _CLAIM_TYPE_ALIASES.get(raw, raw)


def _claim_text_matches(script: str, claim: str) -> bool:
    normalized_script = re.sub(r"\s+", "", script)
    normalized_claim = re.sub(r"\s+", "", claim).rstrip("。！？!?；;，,")
    return bool(normalized_claim and normalized_claim in normalized_script)


def validate_claims(
    draft: dict[str, Any],
    *,
    asset_kinds: dict[int, str],
    online_source_ids: set[str],
    evidence_text: str,
) -> None:
    script = _text(draft.get("script"))
    if not script:
        raise GenerationValidationError("正文为空")
    claims = draft.get("claims")
    if not isinstance(claims, list):
        raise GenerationValidationError("正文缺少 claims 数组")
    problems: list[str] = []
    for claim in claims:
        if not isinstance(claim, dict):
            problems.append("主张格式错误")
            continue
        text = _text(claim.get("text"))
        claim_type = _claim_type(claim.get("type"))
        claim["type"] = claim_type
        ids = claim.get("evidence_ids")
        if not text or not _claim_text_matches(script, text):
            problems.append("主张必须逐字出现在正文中")
        if (ids is None or (isinstance(ids, list) and not ids)) and claim_type in {"inference", "opinion"}:
            ids = ["input:topic"] if claim_type == "inference" else []
        elif not isinstance(ids, list):
            problems.append("主张 evidence_ids 必须是数组")
            ids = []
        claim["evidence_ids"] = ids
        numeric_ids = {value for value in ids if isinstance(value, int)}
        external_ids = {_text(value) for value in ids if isinstance(value, str)}
        if claim_type == "author_experience":
            if not numeric_ids and "input:topic" not in external_ids:
                problems.append("作者经历没有作者证据")
            if any(asset_kinds.get(value) not in {"experience", "fact"} for value in numeric_ids):
                problems.append("作者经历引用了非作者事实/经历资产")
        elif claim_type == "external_fact":
            if not external_ids or not external_ids.issubset(online_source_ids):
                problems.append("外部事实没有有效外部来源")
        elif claim_type == "inference":
            if not ids:
                problems.append("推论没有蓝图证据")
        elif claim_type != "opinion":
            problems.append("未知主张类型")
        if set(numeric_ids) - set(asset_kinds):
            problems.append("主张引用未知作者资产")
        if external_ids - online_source_ids - {"input:topic"}:
            problems.append("主张引用未知外部来源")
    if re.search(r"我曾经|我之前|我当年|我亲测|我试过|我花了|我赚了|我遇到过|我的经历|我做过", script):
        declared = any(isinstance(item, dict) and item.get("type") == "author_experience" for item in claims)
        if not declared:
            problems.append("正文含第一人称经历但未声明作者证据")
    allowed = {_number_key(value) for value in extract_numbers(evidence_text)}
    allowed |= {_number_key(value) for value in _calculation_numbers(evidence_text + "\n" + script)}
    actual = extract_numbers(_text(draft.get("title")) + "\n" + _text(draft.get("cover_text")) + "\n" + script)
    for number in actual:
        normalized = _number_key(number)
        if normalized not in allowed and not any(
            normalized in candidate or candidate in normalized
            for candidate in allowed
        ):
            problems.append(f"数字无证据或计算过程：{number}")
    if problems:
        raise GenerationValidationError("；".join(dict.fromkeys(problems)))


def compute_quality_passed(run: Any) -> bool:
    attempts = json_dict(getattr(run, "attempts_json", "{}"))
    stages = attempts.get("stages") if isinstance(attempts, dict) else {}
    required_stages = {"assets", "angles", "blueprint", "writing", "review"}
    completed = isinstance(stages, dict) and all(
        isinstance(stages.get(name), dict) and stages[name].get("status") == "completed"
        for name in required_stages
    )
    reviews = json_list(getattr(run, "reviews_json", "[]"))
    final_review = reviews[-1] if reviews and isinstance(reviews[-1], dict) else {}
    final_hash = getattr(run, "final_script_hash", "")
    opening = stages.get("opening_check") if isinstance(stages, dict) else None
    return bool(
        getattr(run, "status", "") == "succeeded"
        and completed
        and int(attempts.get("write_count") or 0) >= 1
        and int(attempts.get("review_count") or 0) >= 1
        and 0 <= int(attempts.get("revision_count") or 0) <= 2
        and final_review.get("executed") is True
        and final_review.get("script_hash") == final_hash
        and final_hash
        and final_review.get("logic_passed") is True
        and not final_review.get("hard_issues")
        # R-266：吸引力分改为诊断项，不再参与硬门禁；开头检查成为必要条件
        and float(final_review.get("author_score") or 0) >= 4
        and isinstance(opening, dict)
        and opening.get("status") == "completed"
        and opening.get("passed") is True
    )
