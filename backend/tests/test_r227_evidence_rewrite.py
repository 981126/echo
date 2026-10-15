"""R-227：洗稿联网事实证据层（豆包搜索）+ 引用校验 + 提示词内容契约。"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import Base
from app.models.web_search import WebSearchLog
from app.services import evidence, web_search


@pytest.fixture()
def db(tmp_path):
    eng = create_engine(f"sqlite:///{tmp_path}/t.db", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=eng)
    session = sessionmaker(bind=eng, autoflush=False, autocommit=False)()
    yield session
    session.close()
    eng.dispose()


def test_gather_online_disabled_returns_empty(db):
    # 无 key（未 monkeypatch）→ 静默返回空，不落库
    res = evidence.gather_online(db, "某选题")
    assert res == {"sources": [], "queries": [], "block": ""}
    assert db.query(WebSearchLog).count() == 0


def test_build_search_query_combines_topic_and_material():
    assert evidence.build_search_query("面试反问", "") == "面试反问"
    q = evidence.build_search_query("面试反问", "面试官让我跑三四趟刷KPI，我反问一句就安排完了")
    assert q.startswith("面试反问 ")
    assert len(q) <= 100


def test_filter_relevant_drops_unrelated():
    query = "面试反问薪资社保"
    sources = [
        {"title": "面试时如何反问薪资与社保", "summary": "面试反问的正确姿势"},
        {"title": "今天天气真好", "summary": "适合出去走走"},
    ]
    kept = evidence.filter_relevant(query, sources)
    assert kept == [sources[0]]


def test_gather_online_writes_log_and_block(db, monkeypatch):
    fake = [{"title": "2025应届生起薪数据", "url": "https://x.com/a", "summary": "本科8698元", "site": "x.com"}]
    monkeypatch.setattr(web_search, "enabled", lambda: True)
    monkeypatch.setattr(web_search, "search", lambda q, count=None, time_range="", query_rewrite=True: fake)

    res = evidence.gather_online(db, "应届生起薪", draft_id=None, creator_id=None)

    assert res["sources"] == fake
    assert "[1]" in res["block"] and "8698" in res["block"]
    assert res["queries"][0]["query"] == "应届生起薪"
    logs = db.query(WebSearchLog).all()
    assert len(logs) == 1
    assert logs[0].query == "应届生起薪"
    assert "x.com/a" in logs[0].results


def test_resolve_used_filters_out_of_range():
    sources = [{"url": "a"}, {"url": "b"}]
    assert evidence.resolve_used(sources, [1, 3, "2", 0, "x", None]) == [sources[0], sources[1]]
    assert evidence.resolve_used(sources, []) == []


def test_rewrite_system_requires_claim_example_and_contract():
    from app.services.benchmark import REWRITE_SYSTEM

    assert "论点" in REWRITE_SYSTEM and "具体" in REWRITE_SYSTEM
    assert '"outlines"' in REWRITE_SYSTEM and '"sources"' in REWRITE_SYSTEM


def test_parse_outlines_multi_and_legacy():
    from app.services.debate import _parse_outlines

    got = _parse_outlines(
        {"outlines": [{"claim": "论点一", "support": "事例A"}, {"claim": " 论点二 "}, "纯字符串论点", {"x": 1}]}
    )
    assert got == [
        {"claim": "论点一", "support": "事例A"},
        {"claim": "论点二", "support": ""},
        {"claim": "纯字符串论点", "support": ""},
    ]
    # 旧数据只有单个 outline 字符串 → 包成一条
    assert _parse_outlines({"outline": "唯一论点"}) == [{"claim": "唯一论点", "support": ""}]


def test_rewrite_user_injects_topic_and_evidence(db, monkeypatch):
    from app.services import benchmark

    monkeypatch.setattr(
        "app.services.generation.author_style_context",
        lambda _db, topic="", mode="": f"STYLE:{topic}",
    )
    text = benchmark._rewrite_user(db, "我的选题", "素材正文", "EVIDENCE-BLOCK")
    assert "STYLE:我的选题" in text  # R-227：风格样本检索传了 topic（原先为空）
    assert "EVIDENCE-BLOCK" in text
    assert "素材正文" in text
