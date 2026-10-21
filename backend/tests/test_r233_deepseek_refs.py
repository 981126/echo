"""R-233：豆包 + DeepSeek 双源联网参考（并行/去重/去营销/正文/生成方选文/留痕）。"""

from __future__ import annotations

import json
import sys
import time
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest
from conftest import ensure_schema, fresh_engine
from sqlalchemy.orm import sessionmaker

from app.models.web_search import WebSearchLog
from app.services import deepseek_search, evidence, web_search


@pytest.fixture()
def db(tmp_path):
    eng = fresh_engine()
    ensure_schema(eng)
    session = sessionmaker(bind=eng, autoflush=False, autocommit=False)()
    yield session
    session.close()


class FakePicker:
    """假生成方：记录 messages，返回预设 picks（或抛错）。"""

    def __init__(self, picks):
        self.picks = picks
        self.messages: list[dict] = []

    def chat_json(self, messages, temperature=0.3, max_tokens=800, require=()):
        self.messages = messages
        if isinstance(self.picks, Exception):
            raise self.picks
        return {"picks": self.picks}


def _patch(monkeypatch, doubao, deepseek, fetch=None):
    monkeypatch.setattr(web_search, "enabled", lambda: True)
    monkeypatch.setattr(web_search, "search", lambda *a, **k: doubao)
    monkeypatch.setattr(deepseek_search, "enabled", lambda: True)
    monkeypatch.setattr(deepseek_search, "search", lambda *a, **k: deepseek)
    monkeypatch.setattr(deepseek_search, "fetch", fetch or (lambda url: ""))


def _doubao() -> list[dict]:
    return [
        {
            "title": "面试反问薪资结构：先问这三句",
            "url": "https://a.com/1?utm_source=x",
            "summary": "面试反问薪资结构时，先问团队编制与绩效口径。",
            "site": "a.com",
            "content": "豆包短正文" * 200,
        },
        {
            "title": "面试反问课程 报名立减",
            "url": "https://ok.com/course",
            "summary": "报名咨询加微信领取资料",
            "site": "ok.com",
        },
        {
            "title": "面试反问技巧（GitHub skill）",
            "url": "https://github.com/foo/bar/blob/main/skill.md",
            "summary": "面试反问",
            "site": "GitHub",
        },
        {
            "title": "今天天气真好",
            "url": "https://weather.com/a",
            "summary": "适合出去走走",
            "site": "weather",
        },
    ]


def _deepseek() -> list[dict]:
    return [
        {
            "provider": "deepseek",
            "title": "面试反问薪资结构：先问这三句",
            "url": "https://a.com/1",
            "summary": "面试反问薪资结构时，先问团队编制与绩效口径（长摘要）。",
            "content": "深度长正文" * 800,
            "site": "a.com",
            "date": "2026-10-01T08:00:00+00:00",
            "rank": 2.1,
            "authority": 3,
        },
        {
            "provider": "deepseek",
            "title": "面试官最怕你反问这三句",
            "url": "https://b.com/2",
            "summary": "面试反问的关键是把主动权拿回来。",
            "content": "正文内容" * 500,
            "site": "b.com",
            "date": "2026-09-20T08:00:00+00:00",
            "rank": 1.8,
            "authority": 2,
        },
    ]


def test_two_providers_parallel_dedupe_and_filter(db, monkeypatch):
    _patch(monkeypatch, _doubao(), _deepseek())
    res = evidence.gather_online(db, "面试反问薪资结构")

    # 双路都跑：queries 两条，日志两行
    assert {q["provider"] for q in res["queries"]} == {"doubao", "deepseek"}
    logs = db.query(WebSearchLog).all()
    assert {row.source for row in logs} == {"doubao", "deepseek"}

    # 同篇合并（URL 去掉 utm_ 后相同），保留更长正文并记录双 provider
    assert len(res["sources"]) == 2
    merged = next(s for s in res["sources"] if s["url"].startswith("https://a.com/1"))
    assert set(merged["providers"]) == {"doubao", "deepseek"}
    assert merged["content_chars"] == len("深度长正文" * 800)
    assert len(merged["content"]) <= 2000

    # 营销 / 代码页 / 不相关都在规则层被剔除，并留原因
    reasons = " ".join(r["reason"] for r in res["rejected"])
    assert "转化话术" in reasons and "代码" in reasons and "不相关" in reasons
    urls = [s["url"] for s in res["sources"]]
    assert not any("ok.com" in u or "github.com" in u or "weather.com" in u for u in urls)

    # 无 picker → 自动兜底 2 篇，证据块带选文理由
    assert 2 <= len(res["selected"]) <= 3
    assert "生成方已按人设选文" in res["block"]
    assert "选文理由" in res["block"]


def test_picker_selects_by_persona_and_fills_short_list(db):
    cands = [
        {"title": f"文章{i}", "url": f"https://x.com/{i}", "summary": "摘要", "content": "正文"}
        for i in range(1, 4)
    ]
    picker = FakePicker([{"id": 1, "reason": "提供薪资数据"}, {"id": 99, "reason": "越界"}])
    picked = evidence.select_references(
        picker, cands, topic="面试反问", persona="标签：犀利敢说", min_pick=2, max_pick=3
    )

    assert [p["url"] for p in picked] == ["https://x.com/1", "https://x.com/2"]
    assert picked[0]["reason"] == "提供薪资数据"
    assert picked[1]["reason"].startswith("生成方未点名")
    assert "犀利敢说" in picker.messages[1]["content"]
    assert "面试反问" in picker.messages[1]["content"]


def test_picker_timeout_falls_back(db, monkeypatch):
    class SlowPicker:
        def chat_json(self, *a, **k):
            time.sleep(1.5)
            return {"picks": [{"id": 1, "reason": "太慢"}]}

    monkeypatch.setattr(
        evidence,
        "get_settings",
        lambda: types.SimpleNamespace(
            online_ref_pick_min=2,
            online_ref_pick_max=3,
            online_pick_timeout_seconds=1,
        ),
    )
    cands = [
        {"title": f"文章{i}", "url": f"https://x.com/{i}", "summary": "摘要"} for i in range(1, 4)
    ]
    started = time.monotonic()
    picked = evidence.select_references(SlowPicker(), cands, topic="选题", min_pick=2, max_pick=3)
    assert time.monotonic() - started < 1.4
    assert len(picked) == 3
    assert all(p["reason"].startswith("自动兜底") for p in picked)


def test_picker_failure_falls_back(db):
    cands = [
        {"title": f"文章{i}", "url": f"https://x.com/{i}", "summary": "摘要"} for i in range(1, 4)
    ]
    picked = evidence.select_references(
        FakePicker(RuntimeError("llm down")), cands, topic="选题", min_pick=2, max_pick=3
    )
    assert len(picked) == 3
    assert all(p["reason"].startswith("自动兜底") for p in picked)


@pytest.mark.parametrize(
    "item,blacklist",
    [
        ({"url": "https://k.sina.com.cn/article_1.html", "title": "普通标题"}, ["k.sina.com.cn"]),
        ({"url": "https://item.taobao.com/x", "title": "普通标题"}, []),
        ({"url": "https://a.com/x", "title": "9.9元训练营报名中"}, []),
        ({"url": "https://a.com/x", "title": "面试反问", "summary": "加微信 扫码 进群 领取"}, []),
    ],
)
def test_marketing_rules(item, blacklist):
    assert evidence._marketing_reason(item, blacklist)


def test_marketing_allows_clean_article():
    item = {
        "url": "https://a.com/x",
        "title": "面试反问薪资结构的三个口径",
        "summary": "先问团队编制、绩效周期与晋升节奏，别一上来就问加班。",
    }
    assert evidence._marketing_reason(item, ["k.sina.com.cn"]) == ""
    assert (
        evidence._article_reason({"url": "https://github.com/a/b/blob/main/x.md"})
        == "代码/仓库页"
    )
    assert evidence._article_reason({"url": "https://a.com/x"}) == ""


def test_fetch_fills_short_content_and_trims(db, monkeypatch):
    doubao = [
        {
            "title": "面试反问技巧",
            "url": "https://a.com/1",
            "summary": "短摘要",
            # 豆包 Content 常与 Summary 等长：同样应触发 Fetch 补正文
            "content": "短摘要",
            "site": "a.com",
        }
    ]
    full = "长正文。" * 600
    _patch(monkeypatch, doubao, [], fetch=lambda url: full)

    res = evidence.gather_online(db, "面试反问")

    assert len(res["sources"]) == 1
    item = res["sources"][0]
    assert item["fetched"] is True
    assert item["content_chars"] == len(full)
    assert len(item["content"]) <= 2000


def test_mark_used_updates_both_provider_logs(db, monkeypatch):
    _patch(monkeypatch, _doubao(), _deepseek())
    picker = FakePicker([{"id": 1, "reason": "提供事实"}])
    res = evidence.gather_online(db, "面试反问薪资结构", picker=picker)

    used = evidence.resolve_used(res["selected"], [1])
    evidence.mark_logs_used(db, res["log_ids"], used)

    logs = db.query(WebSearchLog).all()
    assert len(logs) == 2
    for row in logs:
        payload = json.loads(row.used)
        assert payload and payload[0]["url"] == used[0]["url"]
    assert res["selected"][0]["reason"] == "提供事实"


def test_single_provider_when_other_down(db, monkeypatch):
    _patch(monkeypatch, [], _deepseek())
    monkeypatch.setattr(web_search, "enabled", lambda: False)

    res = evidence.gather_online(db, "面试反问")

    assert len(res["queries"]) == 1
    assert res["queries"][0]["provider"] == "deepseek"
    assert len(res["sources"]) == 2
    logs = db.query(WebSearchLog).all()
    assert [row.source for row in logs] == ["deepseek"]


def test_deepseek_normalize_maps_fields():
    item = deepseek_search._normalize(
        {
            "title": "标题",
            "url": "https://z.com/a",
            "summary": "摘要",
            "content": "正文",
            "site_name": "站点",
            "date": "2026-10-01T00:00:00+00:00",
            "rerank_score": 2.5,
            "authority": 4,
        }
    )
    assert item is not None
    assert item["provider"] == "deepseek"
    assert item["content"] == "正文"
    assert item["site"] == "站点"
    assert item["rank"] == 2.5
    assert item["authority"] == 4
