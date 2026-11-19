"""R-265：复盘结论接线（掉点引用原句 + 分诊降级）。"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.video_review_rules import apply_triage, build_findings

FACTS = {
    "plays": {"state": "normal", "value": 1200, "label": "播放量", "unit": "次", "baseline": 1000},
    "like_rate": {"state": "normal", "value": 0.05, "label": "点赞率", "unit": "ratio", "baseline": 0.05},
    "bounce_2s_rate": {"state": "low", "value": 0.45, "label": "2秒跳出率", "unit": "ratio", "baseline": 0.35},
    "finish_5s_rate": {"state": "normal", "value": 0.4, "label": "5秒完播率", "unit": "ratio", "baseline": 0.42},
    "finish_rate": {"state": "low", "value": 0.05, "label": "完整完播率", "unit": "ratio", "baseline": 0.09},
    "cover_click_rate": {"state": "normal", "value": 0.1, "label": "封面点击率", "unit": "ratio", "baseline": 0.1},
    "profile_visits": {"state": "normal", "value": 50, "label": "主页访问量", "unit": "次", "baseline": 50},
    "follower_per_1k": {"state": "normal", "value": 2.0, "label": "每千次关注", "unit": "人", "baseline": 2.0},
    "follower_gain": {"state": "normal", "value": 2, "label": "粉丝增量", "unit": "人", "baseline": 2},
}


for _key, _item in FACTS.items():
    _item.setdefault("key", _key)
    _item.setdefault("percentile", 50.0)
    _item.setdefault("sample_count", 10)


def _comparison(drops):
    return {
        "facts": FACTS,
        "overall": "needs_improvement",
        "charts": {"retention": {"reliable": True, "points": [], "drops": drops}},
    }


def test_findings_quote_aligned_sentence():
    drops = [
        {
            "time_label": "00:04–00:06",
            "drop": 0.22,
            "drop_ratio": 0.3,
            "sentence": {"text": "很多人以为简历改得越漂亮越好", "start_ms": 4000, "end_ms": 6900},
        }
    ]
    findings = build_findings(_comparison(drops), "转写正文", [], [])
    trend = [item for item in findings if item["rule_key"] == "trend_drop"]
    assert trend
    assert trend[0]["content_evidence"][0]["text"] == "很多人以为简历改得越漂亮越好"
    assert "00:04–00:06" in trend[0]["content_evidence"][0]["source"]
    assert "很多人以为简历改得越漂亮越好" in trend[0]["suggestion"]


def test_findings_without_sentence_stay_generic():
    drops = [{"time_label": "00:04–00:06", "drop": 0.22, "drop_ratio": 0.3, "sentence": None}]
    findings = build_findings(_comparison(drops), "转写正文", [], [])
    trend = [item for item in findings if item["rule_key"] == "trend_drop"]
    assert trend[0]["content_evidence"] == []
    assert "没有逐句时间轴" in trend[0]["suggestion"]


def test_apply_triage_downgrades_completion_facts():
    findings = [
        {"dimension": "completion", "judgement_type": "fact", "rule_key": "trend_drop", "suggestion": "把这段提前。"},
        {"dimension": "plays", "judgement_type": "fact", "rule_key": "reach_weak", "suggestion": "换封面。"},
    ]
    triage = {"traffic": {"level": "limited", "recommended_ratio": 0.43}}
    apply_triage(findings, triage)
    assert findings[0]["judgement_type"] == "hypothesis"
    assert "推荐流量占比偏低" in findings[0]["suggestion"]
    assert findings[1]["judgement_type"] == "fact"

    normal = [{"dimension": "completion", "judgement_type": "fact", "suggestion": "x"}]
    apply_triage(normal, {"traffic": {"level": "normal"}})
    assert normal[0]["judgement_type"] == "fact"
