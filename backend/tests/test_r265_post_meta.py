"""R-265：时长解析/分桶、流量分诊与复盘分诊快照。"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.post_meta import (
    build_triage,
    duration_bucket,
    parse_duration_seconds,
    recommended_ratio,
    traffic_triage,
)


def test_parse_duration_creator_and_public_shapes():
    assert parse_duration_seconds({"item": {"video_info": {"duration": "85774"}}}) == 86
    assert parse_duration_seconds({"duration": 147469}) == 147
    assert parse_duration_seconds('{"duration": 45000}') == 45
    # 小于 1000 按秒处理（部分接口直接给秒）
    assert parse_duration_seconds({"duration": 42}) == 42
    assert parse_duration_seconds({}) is None
    assert parse_duration_seconds("not-json") is None
    assert parse_duration_seconds(None) is None


def test_duration_bucket_boundaries():
    assert duration_bucket(None) == ""
    assert duration_bucket(29) == "<30"
    assert duration_bucket(30) == "30-60"
    assert duration_bucket(59) == "30-60"
    assert duration_bucket(60) == "60-120"
    assert duration_bucket(119) == "60-120"
    assert duration_bucket(120) == ">120"


def test_recommended_ratio_and_triage():
    traffic = [
        {"name": "推荐", "ratio": 0.43, "keys": ["homepage_hot"]},
        {"name": "关注", "ratio": 0.27, "keys": ["follow"]},
        {"name": "搜索", "ratio": 0.12, "keys": ["search"]},
    ]
    assert recommended_ratio(traffic) == 0.43
    assert traffic_triage(traffic) == {"recommended_ratio": 0.43, "level": "limited"}
    strong = [{"name": "推荐", "ratio": 0.82, "keys": ["homepage_hot"]}, {"name": "主页", "ratio": 0.1, "keys": ["homepage"]}]
    assert traffic_triage(strong)["level"] == "normal"
    assert traffic_triage([])["level"] == "unknown"
    assert traffic_triage("[]")["level"] == "unknown"


def test_build_triage_notes():
    facts = {"finish_5s_rate": {"state": "normal"}, "finish_rate": {"state": "low"}}
    triage = build_triage(150, [{"name": "推荐", "ratio": 0.4}], facts)
    assert triage["duration_bucket"] == ">120"
    assert triage["traffic"]["level"] == "limited"
    assert any("推荐流量占比" in note for note in triage["notes"])
    assert any("长视频完播天然更低" in note for note in triage["notes"])

    short = build_triage(45, [{"name": "推荐", "ratio": 0.9}], facts)
    assert short["notes"] == []
