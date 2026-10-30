from __future__ import annotations

import json
import re

from sqlalchemy.orm import Session

from . import budget_settings, model_settings
from .llm_router import primary_llm
from .prompt_service import get_prompt

REVIEW_SYSTEM = (
    "你是短视频复盘助手。只能根据输入的真实证据解释原因，不得创造数字、评论、经历、搜索词或证据。"
    "数据事实和内容推测必须区分；建议必须具体、直白、可执行。只输出JSON。"
)


def enhance_findings(db: Session, findings: list[dict]) -> tuple[list[dict], str, str]:
    if not findings:
        return findings, "", ""
    slots = model_settings.resolve_slots(db)
    if not any(slot.get("api_key") for slot in slots.values()):
        return findings, "", "未配置模型，当前展示程序依据真实数据生成的分析"
    listing = json.dumps([
        {
            "rule_key": item["rule_key"],
            "title": item["title"],
            "judgement_type": item["judgement_type"],
            "conclusion": item["conclusion"],
            "suggestion": item["suggestion"],
            "metric_evidence": item["metric_evidence"],
            "content_evidence": item["content_evidence"][:2],
        }
        for item in findings
    ], ensure_ascii=False, default=str)
    try:
        llm = primary_llm(db, "video_review", target="/video-review")
        result = llm.chat_json(
            [
                {"role": "system", "content": get_prompt("video_review", db) or REVIEW_SYSTEM},
                {
                    "role": "user",
                    "content": (
                        f"请把以下分析整理成小白能懂的中文，保持每条rule_key和判断方式不变。"
                        f"输出 {{\"findings\":[{{\"rule_key\":\"...\",\"title\":\"...\",\"conclusion\":\"...\",\"suggestion\":\"...\"}}]}}。"
                        f"不得增加新的原因或数值。输入：{listing}"
                    ),
                },
            ],
            temperature=0.2,
            max_tokens=budget_settings.budget_for(db, "video_review"),
            require=("findings",),
        )
        allowed_numbers = set(re.findall(r"\d+(?:\.\d+)?", listing))
        by_rule = {item["rule_key"]: item for item in findings}
        for candidate in result.get("findings") or []:
            rule = by_rule.get(str(candidate.get("rule_key") or ""))
            text = json.dumps(candidate, ensure_ascii=False)
            if not rule or any(number not in allowed_numbers for number in re.findall(r"\d+(?:\.\d+)?", text)):
                continue
            for field in ("title", "conclusion", "suggestion"):
                value = str(candidate.get(field) or "").strip()
                if value:
                    rule[field] = value
        return findings, llm.used_model, ""
    except Exception as exc:
        return findings, "", f"AI文字整理不可用，已保留数据事实：{str(exc)[:120]}"
