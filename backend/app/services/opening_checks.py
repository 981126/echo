"""R-266：开头程序化检查（替代 LLM 吸引力自评的硬门禁）。

四条规则（顺序固定，便于页面稳定展示）：
1. 首句 ≤25 字；
2. 前 70 字至少命中一项「具体性」（数字/金额单位/结果/冲突）；
3. 不得以「大家好/我是/今天想/最近/先介绍/这一期/hello/哈喽」起手；
4. 蓝图 hook.payoff 在正文首次出现位置 ≤30%。
"""

from __future__ import annotations

import re
from difflib import SequenceMatcher

MAX_FIRST_CHARS = 25
WINDOW_CHARS = 70
MAX_PAYOFF_RATIO = 0.30

_SENTENCE_SPLIT = re.compile(r"[。！？!?…\n]")
_PUNCT = re.compile(r"[\s。！？!?；;，,、…—“”\"'（）()：:]+")
_BANNED_OPENERS = ("大家好", "我是", "今天想", "最近", "先介绍", "这一期", "hello", "哈喽")
_SIGNAL_WORDS = (
    "万", "块", "元", "岁", "天", "份", "次", "个月", "年", "小时", "分钟",
    "结果", "最后", "拿到", "赚", "过了", "成了", "面过", "涨", "降", "亏",
    "却", "反而", "居然", "偏偏", "崩", "翻车", "后悔", "被拒", "卡壳", "没人", "裁了", "凉了",
)


def clean_text(text: str) -> str:
    return _PUNCT.sub("", text or "")


def _first_sentence(text: str) -> str:
    parts = [part.strip() for part in _SENTENCE_SPLIT.split(text or "") if part.strip()]
    return parts[0] if parts else ""


def _specific_hits(window: str) -> list[str]:
    hits: list[str] = []
    if re.search(r"\d", window):
        hits.append("数字")
    for word in _SIGNAL_WORDS:
        if word in window:
            hits.append(word)
            if len(hits) >= 3:
                break
    return hits


def _payoff_ratio(script: str, payoff: str) -> float | None:
    clean_script = clean_text(script)
    clean_payoff = clean_text(payoff)
    if not clean_payoff or not clean_script:
        return None
    index = clean_script.find(clean_payoff)
    if index < 0:
        return None
    return round(index / len(clean_script), 4)


def check_opening(script: str, payoff: str = "") -> dict:
    """返回 {passed, issues[], metrics{}}；issues 顺序固定。"""
    text = (script or "").strip()
    sentence = _first_sentence(text)
    window = clean_text(text)[:WINDOW_CHARS]
    issues: list[dict] = []

    if not text:
        return {
            "passed": False,
            "issues": [{"rule": "empty_script", "detail": "正文为空", "fix": "先生成正文"}],
            "metrics": {"first_chars": 0, "window_chars": 0, "hits": [], "payoff_ratio": None},
        }

    first_chars = len(clean_text(sentence))
    if first_chars > MAX_FIRST_CHARS:
        issues.append(
            {
                "rule": "first_too_long",
                "detail": f"首句 {first_chars} 字（上限 {MAX_FIRST_CHARS}）",
                "fix": f"压到 {MAX_FIRST_CHARS} 字内，先给结论或冲突",
            }
        )

    hits = _specific_hits(window)
    if not hits:
        issues.append(
            {
                "rule": "no_specific",
                "detail": f"前 {WINDOW_CHARS} 字没有数字、结果或冲突",
                "fix": "开头补一个具体数字、结果或代价，不要只讲道理",
            }
        )

    opener = next((word for word in _BANNED_OPENERS if clean_text(text).startswith(word)), "")
    if opener:
        issues.append(
            {
                "rule": "banned_opener",
                "detail": f"以「{opener}」起手",
                "fix": "删掉自我介绍与铺垫，直接从结论或冲突开始",
            }
        )

    ratio = _payoff_ratio(text, payoff)
    payoff_state = "skipped"
    if ratio is not None:
        payoff_state = "passed" if ratio <= MAX_PAYOFF_RATIO else "late"
        if ratio > MAX_PAYOFF_RATIO:
            issues.append(
                {
                    "rule": "late_payoff",
                    "detail": f"开头承诺到全文 {ratio * 100:.0f}% 才首次兑现（上限 {int(MAX_PAYOFF_RATIO * 100)}%）",
                    "fix": "把承诺的兑现提前到前 30%",
                }
            )

    return {
        "passed": not issues,
        "issues": issues,
        "metrics": {
            "first_chars": first_chars,
            "window_chars": len(window),
            "hits": hits,
            "payoff_ratio": ratio,
            "payoff_state": payoff_state,
        },
    }


MIN_SAMPLE_OVERLAP = 8
OVERLAP_SCAN_CHARS = 150


def max_sample_overlap(script: str, samples: list[str]) -> int:
    """生成稿开头与样本的最长连续重合字数（忽略标点与空白）。"""
    head = clean_text(script)[:OVERLAP_SCAN_CHARS]
    best = 0
    for sample in samples or []:
        other = clean_text(sample)
        if not head or not other:
            continue
        match = SequenceMatcher(None, head, other, autojunk=False).find_longest_match(
            0, len(head), 0, len(other)
        )
        best = max(best, match.size)
    return best


def evaluate_opening(script: str, payoff: str = "", samples: list[str] | None = None) -> dict:
    """check_opening + 防照抄；任一不过即 passed=False。"""
    result = check_opening(script, payoff)
    overlap = max_sample_overlap(script, samples or [])
    result["metrics"]["max_overlap"] = overlap
    if overlap >= MIN_SAMPLE_OVERLAP:
        result["issues"].append(
            {
                "rule": "opening_sample_overlap",
                "detail": f"与开头样本连续重合 {overlap} 字（上限 {MIN_SAMPLE_OVERLAP}）",
                "fix": "换一种说法，只借结构与节奏，不要照抄",
            }
        )
    result["passed"] = not result["issues"]
    return result
