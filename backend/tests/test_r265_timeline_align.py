"""R-265：留存曲线掉点 → 句子对齐的阈值、合并、去重与降级。"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.video_review_timeline import align_drops


def _points(values: list[float], step: int = 2) -> list[dict]:
    return [
        {"time_seconds": index * step, "time_label": f"00:{index * step:02d}", "current": value}
        for index, value in enumerate(values)
    ]


SENTENCES = [
    {"start_ms": 4000, "end_ms": 6900, "text": "很多人以为简历改得越漂亮越好"},
    {"start_ms": 7000, "end_ms": 12000, "text": "其实方向才是第一位的"},
    {"start_ms": 12000, "end_ms": 18000, "text": "先说结论再说原因"},
]


def test_hit_needs_both_thresholds():
    # 0.90 → 0.60：跌 30 个百分点、相对 33% → 命中
    points = _points([1.0, 0.95, 0.9, 0.6, 0.58, 0.56])
    drops, reason = align_drops(points, SENTENCES, "sentence", 1000, True, 30)
    assert reason == "ok"
    assert len(drops) == 1
    assert drops[0]["start_seconds"] == 4
    assert drops[0]["end_seconds"] == 6
    assert abs(drops[0]["drop"] - 0.3) < 1e-9

    # 0.70 → 0.65：跌 5 个百分点（过绝对阈值），但相对 7.1% < 8% → 不单独成掉点
    points = _points([1.0, 0.9, 0.8, 0.7, 0.65, 0.64])
    drops, _ = align_drops(points, [], "sentence", 1000, True, 30)
    assert all(abs(item["drop"] - 0.05) > 1e-9 for item in drops)


def test_relative_threshold_blocks_small_percentage_drop():
    # 0.62 → 0.57：跌 5 个百分点但相对 8.06%… 取 0.70 → 0.65（相对 7.14%）必不命中
    points = _points([1.0, 0.9, 0.7, 0.65, 0.64, 0.63])
    drops, _ = align_drops(points, [], "sentence", 1000, True, 30)
    labels = [item["time_label"] for item in drops]
    assert "00:04–00:06" not in labels


def test_adjacent_hits_merge_into_one_span():
    # 连续两段都命中 → 合并成一段，跌幅按首尾差
    points = _points([1.0, 0.9, 0.8, 0.6, 0.4, 0.35, 0.3])
    drops, _ = align_drops(points, [], "sentence", 1000, True, 30)
    assert drops[0]["start_seconds"] == 2
    assert drops[0]["end_seconds"] == 6
    assert abs(drops[0]["drop"] - 0.3) < 1e-9


def test_top3_and_sentence_dedup():
    points = _points([1.0, 0.9, 0.7, 0.5, 0.2, 0.1, 0.05])
    drops, _ = align_drops(points, SENTENCES, "sentence", 1000, True, 30)
    assert len(drops) <= 3
    texts = [item["sentence"]["text"] for item in drops if item.get("sentence")]
    assert len(texts) == len(set(texts))


def test_sentence_matches_window_with_padding():
    # 8→10 秒跌 25 个百分点，落在第二句时间窗（7~12 秒）内
    points = _points([1.0, 0.95, 0.9, 0.85, 0.8, 0.55, 0.5])
    drops, _ = align_drops(points, SENTENCES, "sentence", 1000, True, 30)
    top = drops[0]
    assert top["confidence"] == "sentence"
    assert top["sentence"]["text"] == "其实方向才是第一位的"


def test_precision_flags_without_sentence():
    points = _points([1.0, 0.9, 0.8, 0.6, 0.55, 0.5])
    drops, _ = align_drops(points, SENTENCES, "chunk", 1000, True, 30)
    assert drops and drops[0]["sentence"] is None
    assert drops[0]["confidence"] == "window"

    drops, _ = align_drops(points, SENTENCES, "none", 1000, True, 30)
    assert drops[0]["confidence"] == "none"


def test_degradation_reasons():
    points = _points([1.0, 0.9, 0.8, 0.6, 0.55, 0.5])
    assert align_drops(points, SENTENCES, "sentence", 1000, False, 30) == ([], "unreliable")
    assert align_drops(points, SENTENCES, "sentence", 100, True, 30) == ([], "low_plays")
    assert align_drops(_points([1.0, 0.5, 0.4, 0.3]), SENTENCES, "sentence", 1000, True, 30) == ([], "few_points")


def test_category_labels():
    points = _points([1.0, 0.7, 0.4, 0.38, 0.37, 0.36])
    drops, _ = align_drops(points, [], "none", 1000, True, 85)
    assert drops[0]["category"] == "hook"

    # 结尾：85 秒视频，掉点落在 70 秒之后
    long_points = [
        {"time_seconds": 68, "time_label": "01:08", "current": 0.5},
        {"time_seconds": 70, "time_label": "01:10", "current": 0.3},
        {"time_seconds": 72, "time_label": "01:12", "current": 0.28},
        {"time_seconds": 74, "time_label": "01:14", "current": 0.27},
        {"time_seconds": 76, "time_label": "01:16", "current": 0.26},
    ]
    drops, _ = align_drops(long_points, [], "none", 1000, True, 85)
    assert drops[0]["category"] == "tail"
