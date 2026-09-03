"""风格画像与加权检索测试（纯逻辑，离线可跑）。"""

from __future__ import annotations

from app.core.retrieval import TfidfIndex
from app.core.style_profile import build_style_profile, format_style_profile


def test_profile_counts_and_format():
    texts = [
        "说实话，面试就是聊天。其实不用紧张，真的。",
        "说实话，谈薪就是讨价还价。其实敢开口就赢了一半，真的。",
        "说实话，找工作就是信息差。其实多投几轮，真的就有戏。",
    ]
    profile = build_style_profile(texts)
    assert profile["empty"] is False
    assert profile["doc_count"] == 3
    assert profile["avg_sent_len"] > 0
    assert "说实话" in profile["top_triples"]
    assert profile["style_words"].get("其实", 0) >= 3
    text = format_style_profile(profile)
    assert "共统计 3 条文案" in text
    assert "说实话" in text


def test_profile_empty():
    profile = build_style_profile([])
    assert profile["empty"] is True
    assert "素材不足" in format_style_profile(profile)


def test_weighted_search_prefers_weighted_doc():
    docs = ["今天聊聊面试怎么准备。", "今天聊聊面试怎么准备。"]
    index = TfidfIndex().build(docs, weights=[0.0, 100.0])
    hits = index.search("面试", top_k=1)
    assert hits and hits[0]["index"] == 1
