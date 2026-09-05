"""纯逻辑测试（无第三方依赖，可离线运行；同时兼容 pytest）。"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.diff import has_meaningful_change  # noqa: E402
from app.core.digest import build_digest_html, build_failure_html  # noqa: E402
from app.core.metrics import engagement_rate, normalize_snapshot, retention_cutoff_date  # noqa: E402
from app.core.review import best_topic_by_engagement, heuristic_direction  # noqa: E402
from app.core.matching import keyword_fallback_match  # noqa: E402
from app.core.pipeline import can_run, today_key  # noqa: E402
from app.core.requirement_file import next_requirement_id, parse_requirement_file  # noqa: E402
from app.core.retrieval import TfidfIndex  # noqa: E402
from app.core.signature import (  # noqa: E402
    build_canonicalized_query,
    build_string_to_sign,
    content_md5,
    hmac_sha1_sign,
    utcnow_rfc1123,
)
from app.core.topics import is_valid_platform, normalize_main_topic  # noqa: E402
from app.core.platform_links import build_platform_page_url, extract_raw_field  # noqa: E402
from app.core.transcript import (  # noqa: E402
    estimate_duration_seconds,
    normalize_text,
    split_sentences,
)


def test_normalize_main_topic():
    assert normalize_main_topic("求职") == "求职"
    assert normalize_main_topic("面试技巧") == "面试"
    assert normalize_main_topic("如何赚钱") == "赚钱"
    assert normalize_main_topic("知识分享") == "知识"
    assert normalize_main_topic("随便什么") == "其他"
    assert normalize_main_topic("") == "其他"
    assert normalize_main_topic(None) == "其他"


def test_platform():
    assert is_valid_platform("douyin")
    assert is_valid_platform("bilibili")
    assert is_valid_platform("xiaohongshu")
    assert not is_valid_platform("youtube")
    assert not is_valid_platform("")


def test_normalize_text():
    assert normalize_text("  你好\u3000世界  ") == "你好 世界"
    assert normalize_text("") == ""


def test_estimate_duration():
    text = "大家好" * 40  # 120 字
    assert estimate_duration_seconds(text) == 30  # 120 / 4 cps


def test_split_sentences():
    parts = split_sentences("第一句。第二句！第三句？")
    assert len(parts) == 3
    assert parts[0] == "第一句。"


def test_signature_helpers():
    assert content_md5(b"") == ""
    q = build_canonicalized_query({"b": "2", "a": "1"})
    assert q == "a=1&b=2"
    signed = hmac_sha1_sign("secret", "hello")
    assert isinstance(signed, str) and len(signed) > 10
    assert "GMT" in utcnow_rfc1123()
    sts = build_string_to_sign("POST", "application/json", b"{}", "application/json", "date", "", "/api?x=1")
    assert sts.startswith("POST\napplication/json")


def test_parse_requirement_file():
    text = "# R-003: 微信推送\n\n- **状态**: 已确认\n- **原文摘要**: 测试摘要\n"
    data = parse_requirement_file(text, "R-003.md")
    assert data["id"] == "R-003"
    assert data["title"] == "微信推送"
    assert data["status"] == "已确认"
    assert data["summary"] == "测试摘要"


def test_next_requirement_id():
    assert next_requirement_id([]) == "R-001"
    assert next_requirement_id(["R-001.md", "R-003.md"]) == "R-004"
    assert next_requirement_id(["README.md"]) == "R-001"




def test_tfidf_search_returns_relevant():
    docs = [
        "今天聊聊面试官最反感的回答方式，很多人都在踩坑",
        "如何通过副业赚钱，普通人也能月入过万",
        "AI 时代哪些岗位会被替代",
    ]
    index = TfidfIndex().build(docs)
    hits = index.search("面试 回答", top_k=1)
    assert hits and hits[0]["index"] == 0


def test_keyword_fallback_match():
    items = [
        {"title": "2026 求职季，应届生怎么办", "platform": "douyin", "heat": "100"},
        {"title": "猫咪日常", "platform": "douyin", "heat": "1"},
    ]
    result = keyword_fallback_match(items, ["求职", "面试"], top_n=5)
    assert len(result) == 1
    assert result[0]["score"] == 20
    assert "求职" in result[0]["reason"]


def test_digest_html():
    items = [
        {
            "title": "测试选题",
            "platform": "douyin",
            "score": 80,
            "reason": "命中",
            "draft_id": 7,
            "cover_text": "别踩坑",
            "script": "大家好……",
        }
    ]
    html = build_digest_html(items, "http://nas:8000")
    assert "测试选题" in html
    assert "http://nas:8000/#/drafts/7" in html
    assert "别踩坑" in html
    assert "boom" in build_failure_html("boom")


def test_pipeline_idempotency():
    assert today_key().count("-") == 2
    assert can_run("done") is True
    assert can_run("failed") is True
    assert can_run("running") is False
    assert can_run(None) is True





def test_normalize_snapshot():
    assert normalize_snapshot({"plays": "100", "likes": -5, "comments": None, "bad": "x"}) == {
        "plays": 100, "likes": 0, "favorites": 0, "comments": 0, "followers_gained": 0
    }


def test_engagement_rate():
    assert engagement_rate(0, 1, 1, 1) == 0.0
    assert engagement_rate(1000, 50, 20, 10) == 8.0  # 80/1000


def test_retention_cutoff_date():
    d = retention_cutoff_date(30)
    assert d.count("-") == 2


def test_review_heuristics():
    stats = [{"topic": "求职", "engagement": 3.0}, {"topic": "赚钱", "engagement": 9.0}]
    best = best_topic_by_engagement(stats)
    assert best["topic"] == "赚钱"
    worst = min(stats, key=lambda x: x["engagement"])
    direction = heuristic_direction(best, worst)
    assert "赚钱" in direction
    assert heuristic_direction(None, None) != ""





def test_has_meaningful_change():
    assert has_meaningful_change("大家好今天我们聊聊求职", "大家好今天我们聊聊赚钱") is True
    assert has_meaningful_change(" 一样的文本 ", "一样的文本") is False
    assert has_meaningful_change("", "非空") is False
    assert has_meaningful_change("原稿", "") is False



def test_build_platform_page_url():
    assert build_platform_page_url("bilibili", "aid:123", '{"bvid":"BV1xx411c7mD"}') == "https://www.bilibili.com/video/BV1xx411c7mD"
    assert build_platform_page_url("bilibili", "aid:123", "") == "https://www.bilibili.com/video/av123"
    assert build_platform_page_url("bilibili", "BV1xx411c7mD", "") == "https://www.bilibili.com/video/BV1xx411c7mD"
    assert build_platform_page_url("douyin", "7343913432204332303", "") == "https://www.douyin.com/video/7343913432204332303"
    assert build_platform_page_url("douyin", "", '{"share_url":"https://v.douyin.com/abc/"}') == "https://v.douyin.com/abc/"
    assert build_platform_page_url("xiaohongshu", "6a1471ed000000003502de6e", "") == "https://www.xiaohongshu.com/explore/6a1471ed000000003502de6e"
    assert extract_raw_field('{"data":{"bvid":"BV1yy"}}', "bvid") == "BV1yy"


def test_default_avoid_words():
    from app.core.style_profile import default_avoid_words

    words = default_avoid_words()
    assert len(words) > 5
    assert len(set(words)) == len(words)


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for fn in fns:
        fn()
        print(f"ok: {fn.__name__}")
    print(f"全部通过：{len(fns)} 个测试")
