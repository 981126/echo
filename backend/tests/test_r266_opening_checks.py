"""R-266：开头检查器的四条规则与降级。"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.opening_checks import check_opening


def _rules(result: dict) -> list[str]:
    return [item["rule"] for item in result["issues"]]


def test_passes_with_short_specific_opening():
    result = check_opening("投简历一直被拒？问题不在简历。先确定目标。")
    assert result["passed"] is True
    assert result["issues"] == []


def test_first_sentence_too_long():
    result = check_opening("我身边很多朋友都问过我这样一个问题那就是到底应该怎么准备面试才不会被刷下来。先看目标。")
    assert "first_too_long" in _rules(result)
    assert result["metrics"]["first_chars"] > 25


def test_no_specific_signal():
    result = check_opening("很多人都会遇到这个问题。我们需要认真思考。")
    assert "no_specific" in _rules(result)


def test_banned_opener():
    result = check_opening("大家好，今天聊聊面试。被拒三次后我才明白。")
    assert "banned_opener" in _rules(result)


def test_late_payoff():
    body = "先给结论。" + "背景铺垫。" * 20 + "第一步是把目标写下来。"
    result = check_opening(body, payoff="第一步是把目标写下来")
    assert "late_payoff" in _rules(result)
    assert result["metrics"]["payoff_ratio"] > 0.30


def test_payoff_skipped_when_missing():
    result = check_opening("被拒三次后我才明白。先确定目标。", payoff="")
    assert result["metrics"]["payoff_state"] == "skipped"
    assert result["passed"] is True


def test_empty_script_fails_everything():
    result = check_opening("")
    assert result["passed"] is False
    assert _rules(result) == ["empty_script"]


def test_issue_order_is_stable():
    result = check_opening("大家好，我是一个特别喜欢研究各种面试技巧并且愿意分享的人。")
    assert _rules(result) == ["first_too_long", "no_specific", "banned_opener"]
