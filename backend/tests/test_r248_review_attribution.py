"""R-248：视频复盘 AI 归因 + 低粉爆款方向相关自测。

覆盖（设计 §5.8）：
1. `verdict_for`：high→strength、low→weak、样本<5→unknown、normal→neutral、无指标→unknown；
2. `build_attribution`：数字白名单 / 文案与评论子串 / 维度校验，合法候选保留且 verdict/证据由程序构造；
3. 模型不可用/异常：规则 findings 保留；规则为空 → 1 条「暂时还不能判断整体好坏」且含真实样本数与指标数字；
4. `run_analysis` 落库 verdict；
5. `owner_direction_terms`：近 30 条 main_topics 计数排序、排除「其他/知识」泛化类目、无数据兜底；
6. `low_fan_references`：只返回命中方向词/同义扩展的条目，按命中数排序；旧行封面回退 raw.thumbnail。
"""

from __future__ import annotations

import json
import sys
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest
from conftest import ensure_schema, fresh_engine
from sqlalchemy.orm import sessionmaker

from app.core.timeutil import now
from app.models.platform import Creator, CreatorAccount, PlatformPost, PlatformPostComment, PlatformPostStat
from app.models.video import Transcript, Video
from app.models.video_review import DouyinReferenceVideo, VideoReview, VideoReviewFinding
from app.services import video_review_attribution as attribution
from app.services.video_review_comparison import (
    DIRECTION_FALLBACK,
    direction_keywords,
    low_fan_references,
    owner_direction_terms,
)
from app.services.video_review_service import run_analysis


@pytest.fixture()
def db():
    eng = fresh_engine()
    ensure_schema(eng)
    session = sessionmaker(bind=eng, autoflush=False, autocommit=False)()
    yield session
    session.close()


def _owner(db) -> tuple[Creator, CreatorAccount]:
    owner = Creator(kind="owner", name="作者", is_current=True)
    db.add(owner)
    db.flush()
    account = CreatorAccount(creator_id=owner.id, platform="douyin", nickname="作者抖音")
    db.add(account)
    db.commit()
    return owner, account


def _post(db, account: CreatorAccount, index: int, plays: int, days_ago: int = 10) -> PlatformPost:
    published = now() - timedelta(days=days_ago)
    post = PlatformPost(
        account_id=account.id,
        platform="douyin",
        platform_post_id=f"r248-{account.id}-{index}",
        title=f"面试自我介绍怎么做 {index}",
        publish_time=published,
        raw="{}",
    )
    db.add(post)
    db.flush()
    db.add(PlatformPostStat(
        post_id=post.id,
        stat_date=(published + timedelta(days=3)).date().isoformat(),
        plays=plays,
        likes=max(1, plays // 20),
        comments=max(1, plays // 500),
        favorites=max(1, plays // 300),
        shares=max(1, plays // 800),
    ))
    db.commit()
    return post


def _comparison() -> dict:
    facts = {
        "finish_rate": {
            "key": "finish_rate", "label": "完整完播率", "unit": "ratio",
            "value": 0.05, "baseline": 0.12, "percentile": 10.0, "state": "low",
            "sample_count": 10, "missing": False,
        },
        "like_rate": {
            "key": "like_rate", "label": "点赞率", "unit": "ratio",
            "value": 0.05, "baseline": 0.05, "percentile": 50.0, "state": "normal",
            "sample_count": 10, "missing": False,
        },
        "plays": {
            "key": "plays", "label": "播放量", "unit": "次",
            "value": 800.0, "baseline": 6000.0, "percentile": 3.0, "state": "low",
            "sample_count": 4, "missing": False,
        },
    }
    return {
        "facts": facts,
        "charts": {"retention": {"points": [], "reliable": False}},
        "overall": "unknown",
        "comparison": {"count": 4, "post_ids": [1, 2, 3, 4]},
        "warnings": [],
    }


class _FakeLLM:
    used_model = "fake-model"

    def __init__(self, payload: dict) -> None:
        self.payload = payload

    def chat_json(self, messages, temperature=0.3, max_tokens=2000, require=(), timeout_seconds=None) -> dict:
        return self.payload


def _enable_fake_llm(monkeypatch, payload: dict) -> None:
    monkeypatch.setattr(
        attribution.model_settings, "resolve_slots", lambda db: {"model1": {"api_key": "fake"}}
    )
    monkeypatch.setattr(
        attribution, "primary_llm", lambda db, feature, target="": _FakeLLM(payload)
    )


def _rule_finding() -> dict:
    return {
        "dimension": "completion",
        "rule_key": "early_retention_weak",
        "title": "开头留人表现低于平时",
        "judgement_type": "fact",
        "conclusion": "开头流失高于平时。",
        "suggestion": "下一条先给结果。",
        "target_metric": "completion",
        "metric_evidence": [{
            "evidence_id": "metric:finish_rate", "key": "finish_rate", "label": "完整完播率",
            "value": 0.05, "baseline": 0.12, "unit": "ratio", "state": "low", "sample_count": 10,
        }],
        "content_evidence": [],
        "comparison_post_ids": [],
    }


def test_verdict_from_metric_states():
    facts = _comparison()["facts"]
    facts["finish_5s_rate"] = {
        "key": "finish_5s_rate", "label": "5秒完播率", "unit": "ratio",
        "value": 0.4, "baseline": 0.3, "percentile": 90.0, "state": "high",
        "sample_count": 10, "missing": False,
    }
    facts["avg_play_seconds"] = {
        "key": "avg_play_seconds", "label": "平均播放时长", "unit": "秒",
        "value": 18.0, "baseline": 17.0, "percentile": 50.0, "state": "limited",
        "sample_count": 4, "missing": False,
    }
    assert attribution.verdict_for(["finish_5s_rate"], facts) == "strength"
    assert attribution.verdict_for(["finish_rate"], facts) == "weak"
    assert attribution.verdict_for(["avg_play_seconds"], facts) == "unknown"  # 样本 <5
    assert attribution.verdict_for(["like_rate"], facts) == "neutral"
    assert attribution.verdict_for([], facts) == "unknown"
    assert attribution.verdict_for(["not_a_metric"], facts) == "unknown"


def test_attribution_validates_numbers_and_quotes(db, monkeypatch):
    comparison = _comparison()
    transcript = "大家好我是小王。今天聊聊理财。我把五十万存款亏到不敢看。"
    comments = [
        PlatformPostComment(post_id=1, platform="douyin", text="面试自我介绍应该怎么说？", likes=8),
        PlatformPostComment(post_id=1, platform="douyin", text="看完很有收获", likes=3),
    ]
    payload = {"findings": [
        {
            "dimension": "completion",
            "title": "完整完播率低于平时",
            "conclusion": "完整完播率 5.0%，低于自己平时 12.0%（样本 10 条），可能与中段铺垫有关",
            "suggestion": "开头 3 秒先给结果，每 15 秒一个信息点",
            "metric_keys": ["finish_rate"],
            "content_quotes": ["我把五十万存款亏到不敢看"],
        },
        {
            "dimension": "engagement",
            "title": "点赞率与平时接近",
            "conclusion": "点赞率和自己平时接近",
            "suggestion": "保持现在的互动引导方式",
            "metric_keys": ["like_rate"],
            "content_quotes": [],
        },
        {
            "dimension": "completion",
            "title": "播放量还能提升",
            "conclusion": "下一条可以优化开头",
            "suggestion": "播放量能提升 99%",
            "metric_keys": ["finish_rate"],
            "content_quotes": [],
        },
        {
            "dimension": "engagement",
            "title": "观众评论很热情",
            "conclusion": "评论区都在问问题",
            "suggestion": "多回复评论",
            "metric_keys": [],
            "content_quotes": ["这句话不在转写里"],
        },
    ]}
    _enable_fake_llm(monkeypatch, payload)

    findings, model_name, warning = attribution.build_attribution(
        db, comparison, transcript, comments, [], [], post_title="我的理财复盘"
    )

    assert model_name == "fake-model"
    assert warning == ""
    assert len(findings) == 2  # 非法数字 / 非子串引用且无指标的候选被丢弃
    first, second = findings
    assert first["dimension"] == "completion"
    assert first["verdict"] == "weak"  # 程序按真实指标 state 判定，不采用 AI 自报
    assert first["judgement_type"] == "hypothesis"
    assert first["metric_evidence"][0]["key"] == "finish_rate"
    assert first["metric_evidence"][0]["unit"] == "ratio"
    assert first["metric_evidence"][0]["state"] == "low"
    assert first["metric_evidence"][0]["value"] == 0.05  # 证据数字由程序从 facts 构造
    assert first["content_evidence"][0]["text"] == "我把五十万存款亏到不敢看"
    assert first["content_evidence"][0]["source"] == "视频文案"
    assert first["rule_key"] == "attribution:completion:1"
    assert second["dimension"] == "engagement"
    assert second["verdict"] == "neutral"
    assert second["judgement_type"] == "fact"
    assert second["metric_evidence"][0]["key"] == "like_rate"


def test_attribution_fallback_when_llm_unavailable(db, monkeypatch):
    comparison = _comparison()
    # 1) 未配置模型：规则 findings 保留，并按真实指标补 verdict
    monkeypatch.setattr(
        attribution.model_settings, "resolve_slots", lambda db: {"model1": {"api_key": ""}}
    )
    findings, model_name, warning = attribution.build_attribution(
        db, comparison, "", [], [], [_rule_finding()], post_title=""
    )
    assert model_name == ""
    assert "AI 归因暂不可用" in warning
    assert len(findings) == 1
    assert findings[0]["rule_key"] == "early_retention_weak"
    assert findings[0]["verdict"] == "weak"

    # 2) 规则也为空：给 1 条「暂时还不能判断整体好坏」，含真实样本数与差异最大指标
    findings, _, warning = attribution.build_attribution(
        db, comparison, "", [], [], [], post_title=""
    )
    assert "AI 归因暂不可用" in warning
    assert len(findings) == 1
    fallback = findings[0]
    assert fallback["title"] == "暂时还不能判断整体好坏"
    assert fallback["verdict"] == "unknown"
    assert fallback["judgement_type"] == "fact"
    assert "4 条" in fallback["conclusion"]  # 真实样本数
    assert "样本少于 5 条" in fallback["conclusion"]
    assert "5.0%" in fallback["conclusion"]
    assert "≥5 条" in fallback["suggestion"]
    assert len(fallback["metric_evidence"]) == 2
    assert [item["unit"] for item in fallback["metric_evidence"]] == ["次", "ratio"]

    # 3) 调用异常：同样回退规则 findings
    _enable_fake_llm(monkeypatch, {"findings": []})
    monkeypatch.setattr(
        attribution, "primary_llm",
        lambda db, feature, target="": (_ for _ in ()).throw(RuntimeError("模型超时")),
    )
    findings, _, warning = attribution.build_attribution(
        db, comparison, "", [], [], [_rule_finding()], post_title=""
    )
    assert "AI 归因暂不可用" in warning
    assert findings[0]["rule_key"] == "early_retention_weak"


def test_analysis_saves_verdict(db):
    owner, account = _owner(db)
    for index in range(6):
        _post(db, account, index, 5000 + index * 100, 20 + index)
    target = _post(db, account, 99, 1000, 3)  # 播放明显低于平时 → 规则产出「播放量低于平时」
    video = Video(
        filename="r248-analysis.mp4", title=target.title, creator_id=owner.id,
        main_topics='["面试"]', status="published",
    )
    db.add(video)
    db.flush()
    db.add(Transcript(video_id=video.id, transcript_text="面试自我介绍先给结果，再讲经历。", asr_status="done"))
    target.local_video_id = video.id
    db.add(PlatformPostComment(post_id=target.id, platform="douyin", text="面试自我介绍应该怎么说？", likes=8))
    db.commit()
    review = VideoReview(account_id=account.id, post_id=target.id, input_fingerprint="r248-verdict")
    db.add(review)
    db.commit()

    run_analysis(db, {"review_id": review.id}, lambda pct, note: None)

    findings = db.query(VideoReviewFinding).filter_by(review_id=review.id).all()
    assert findings
    assert {row.verdict for row in findings} <= {"strength", "weak", "neutral", "unknown"}
    assert any(row.verdict == "weak" for row in findings)
    evidence = json.loads(findings[0].metric_evidence or "[]")
    assert evidence and "unit" in evidence[0] and "state" in evidence[0]


def test_owner_direction_terms(db):
    owner, _ = _owner(db)
    topics = [
        ["其他"], ["其他"], ["知识"], ["知识"], ["知识"],
        ["面试"], ["面试"], ["赚钱"],
    ]
    for index, values in enumerate(topics):
        db.add(Video(filename=f"dir-{index}.mp4", creator_id=owner.id, main_topics=json.dumps(values)))
    db.commit()
    # 「知识」是泛化类目，不作为内容方向；剩余按出现次数排序
    assert owner_direction_terms(db, owner) == ["面试", "赚钱"]

    # 不足 3 个时仅用已有词，不强行补满
    only = Creator(kind="owner", name="只有一个方向", is_current=False)
    db.add(only)
    db.flush()
    db.add(Video(filename="dir-only.mp4", creator_id=only.id, main_topics='["赚钱"]'))
    db.commit()
    assert owner_direction_terms(db, only) == ["赚钱"]

    # 无任何主赛道 → 兜底方向词
    empty = Creator(kind="owner", name="没有方向", is_current=False)
    db.add(empty)
    db.commit()
    assert owner_direction_terms(db, empty) == list(DIRECTION_FALLBACK)
    assert direction_keywords(["求职"]) >= {"求职", "找工作", "面试", "offer"}

    # 只有泛化类目时回退原始词，保证仍有方向词可搜
    generic = Creator(kind="owner", name="泛化类目", is_current=False)
    db.add(generic)
    db.flush()
    db.add(Video(filename="dir-generic.mp4", creator_id=generic.id, main_topics='["知识", "其他"]'))
    db.commit()
    assert owner_direction_terms(db, generic) == ["知识"]


def test_low_fan_references_filters_unrelated(db):
    owner, _ = _owner(db)
    for index in range(3):
        db.add(Video(
            filename=f"lf-owner-{index}.mp4", creator_id=owner.id, main_topics='["面试"]', tags="[]",
        ))
    db.commit()
    rows = [
        ("lf-related-2", "面试官最讨厌的自我介绍", "面试"),
        ("lf-related-1", "面试时应该怎么回答", "面试"),
        ("lf-unrelated-1", "猫咪搞笑合集", ""),
        ("lf-unrelated-2", "演唱会现场直拍", ""),
    ]
    base = now()
    for index, (external_id, title, keyword) in enumerate(rows):
        db.add(DouyinReferenceVideo(
            external_post_id=external_id,
            title=title,
            keyword=keyword,
            category_id="628",
            duration_seconds=60,
            last_seen_at=base - timedelta(hours=index),
        ))
    db.commit()

    items = low_fan_references(db, owner, limit=20)
    titles = [item["title"] for item in items]
    # 不相关赛道被过滤；命中数多的「面试官」排在前面
    assert "猫咪搞笑合集" not in titles
    assert "演唱会现场直拍" not in titles
    assert titles == ["面试官最讨厌的自我介绍", "面试时应该怎么回答"]


def test_low_fan_cover_falls_back_to_raw_thumbnail(db):
    owner, _ = _owner(db)
    db.add(Video(filename="lf-cover-owner.mp4", creator_id=owner.id, main_topics='["面试"]', tags="[]"))
    db.add(DouyinReferenceVideo(
        external_post_id="lf-cover-1",
        title="面试时怎么自我介绍",
        keyword="面试",
        cover_url="",
        raw=json.dumps({"thumbnail": "https://example.com/cover.jpg"}, ensure_ascii=False),
        last_seen_at=now(),
    ))
    db.commit()
    items = low_fan_references(db, owner, limit=20)
    assert items and items[0]["cover_url"] == "https://example.com/cover.jpg"
