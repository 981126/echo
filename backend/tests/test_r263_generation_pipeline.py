"""R-263：作者资产证据、生成阶段与真实质量门禁。"""

from __future__ import annotations

import json

import pytest
from conftest import fresh_engine
from sqlalchemy.orm import sessionmaker

from app.models.author_generation import AuthorAsset, GenerationRun
from app.models.draft import Draft
from app.models.platform import Creator
from app.models.video import Transcript, Video
from app.services import generation_pipeline as pipeline
from app.services import llm_router
from app.services.author_assets import (
    content_hash,
    extract_assets_from_videos,
    resolve_evidence,
    retrieve_author_assets,
)
from app.services.generation_validators import (
    GenerationValidationError,
    compute_quality_passed,
    extract_numbers,
    validate_angles,
    validate_blueprint,
    validate_claims,
)
from app.services.llm import LLMError


@pytest.fixture()
def db():
    engine = fresh_engine()
    session = sessionmaker(bind=engine, autoflush=False, autocommit=False)()
    yield session
    session.close()


def _owner(db) -> Creator:
    owner = Creator(kind="owner", name="作者", is_current=True)
    db.add(owner)
    db.commit()
    db.refresh(owner)
    return owner


def _video(db, owner: Creator, text: str, title: str = "原文") -> Video:
    video = Video(creator_id=owner.id, filename=f"{title}-{text[:4]}.mp4", title=title)
    db.add(video)
    db.flush()
    db.add(Transcript(video_id=video.id, transcript_text=text, corrected_text=text))
    db.commit()
    db.refresh(video)
    return video


def _asset(db, owner: Creator, video: Video, content: str, quote: str, kind: str = "viewpoint") -> AuthorAsset:
    transcript = video.transcript
    text = transcript.corrected_text or transcript.transcript_text
    start = text.index(quote)
    asset = AuthorAsset(
        creator_id=owner.id,
        asset_kind=kind,
        source_kind="asr",
        source_id=f"video:{video.id}",
        content=content,
        evidence_refs=json.dumps([
            {
                "video_id": video.id,
                "transcript_id": transcript.id,
                "start_char": start,
                "end_char": start + len(quote),
                "quote": quote,
            }
        ], ensure_ascii=False),
        content_hash=content_hash(owner.id, kind, content),
        status="active",
        quality_score=0.8,
    )
    db.add(asset)
    db.commit()
    return asset


def test_asset_quote_is_exact_and_cross_creator_is_rejected(db):
    owner = _owner(db)
    other = Creator(kind="owner", name="别人", is_current=False)
    db.add(other)
    db.commit()
    video = _video(db, owner, "我认为慢就是快，但只适用于长期积累。")
    transcripts = {video.id: (video.transcript, video.transcript.corrected_text)}
    refs = resolve_evidence(
        [{"video_id": video.id, "quote": "只适用于长期积累"}],
        transcripts,
    )
    assert refs[0]["start_char"] == 9
    assert resolve_evidence([{"video_id": video.id, "quote": "一年赚一百万"}], transcripts) == []
    asset = _asset(db, owner, video, "慢就是快只适合长期积累", "只适用于长期积累")
    asset.creator_id = other.id
    assert retrieve_author_assets(db, owner.id, "长期积累") == []


def test_asset_extraction_stores_only_verified_quotes(db):
    owner = _owner(db)
    video = _video(db, owner, "我去年换了三次工作，最后学会先确认目标。")

    class _Client:
        def chat_json(self, *_args, **_kwargs):
            return {
                "assets": [
                    {
                        "asset_kind": "experience",
                        "content": "作者换过三次工作",
                        "context": {},
                        "evidence": [{"video_id": video.id, "quote": "我去年换了三次工作"}],
                    },
                    {
                        "asset_kind": "experience",
                        "content": "作者月入十万",
                        "context": {},
                        "evidence": [{"video_id": video.id, "quote": "我月入十万"}],
                    },
                ]
            }

    result = extract_assets_from_videos(db, [video], llm=_Client())
    assert result == {"created": 1, "rejected": 1}
    row = db.query(AuthorAsset).one()
    assert row.status == "active"
    assert "三次" in row.evidence_refs


def test_generation_runs_all_real_stages_and_passes(db, monkeypatch):
    owner = _owner(db)
    calls: list[str] = []

    class _Client:
        def __init__(self, _feature, _route, *, primary, fallback):
            self.primary = primary
            self.used_slot = primary
            self.used_vendor = "fake"
            self.used_model = "model-x"
            self.degraded = False

        def routing(self):
            return {"used": self.used_model, "degraded": False}

        def chat_json(self, messages, **_kwargs):
            system = messages[0]["content"]
            if system == pipeline.AUTHOR_ANGLE_SYSTEM:
                calls.append("angles")
                return {"angles": [{
                    "angle_id": "a1", "title": "先确认目标", "audience": "做选择的人",
                    "promise": "根据真实目标做可执行选择", "hook": "为什么常见建议会失效",
                    "reasoning": ["先确定目标", "再检查必要条件"], "required_asset_ids": [],
                    "external_source_ids": [], "claim_type": "inference", "author_fit": 20,
                    "evidence_fit": 20, "audience_value": 20, "distinctiveness": 20, "risk": "",
                }], "questions": []}
            if system == pipeline.AUTHOR_BLUEPRINT_SYSTEM:
                calls.append("blueprint")
                return {
                    "goal": "做出符合目标的选择", "audience": "需要做选择的人",
                    "core_promise": "根据真实目标做可执行选择",
                    "hook": {"text": "为什么常见建议会失效", "payoff": "第一步"},
                    "reasoning_steps": [{
                        "claim": "先确定目标", "claim_type": "opinion", "evidence_ids": [],
                        "inference": "目标决定必要条件", "limitations": "目标变化时结论变化",
                    }],
                    "actions": [{"precondition": "明确目标", "action": "检查必要条件", "expected_result": "排除不可行建议"}],
                    "ending": "回扣目标",
                }
            if system == pipeline.AUTHOR_WRITE_SYSTEM:
                calls.append("writing")
                return {
                    "title": "先确认目标", "cover_text": "别急着选",
                    "script": "先确定目标，再检查必要条件，才能排除不可行建议。",
                    "shells": {}, "claims": [{"text": "先确定目标", "type": "opinion", "evidence_ids": []}],
                }
            if system == pipeline.AUTHOR_REVIEW_SYSTEM:
                calls.append("review")
                return {"logic_passed": True, "hard_issues": [], "attraction_score": 4, "author_score": 4, "issues": []}
            raise AssertionError(system)

    monkeypatch.setattr(llm_router, "RoutedLLM", _Client)
    draft = Draft(creator_id=owner.id, title="怎样做准备", script=pipeline.GENERATION_PLACEHOLDER, source="ai")
    db.add(draft)
    db.commit()
    run = pipeline.create_generation_run(db, creator_id=owner.id, draft_id=draft.id, topic=draft.title)
    result = pipeline.run_generation_pipeline(db, run, draft)
    assert result["status"] == "succeeded"
    assert calls == ["angles", "blueprint", "writing", "review"]
    assert run.quality_passed is True
    assert json.loads(draft.quality)["passed"] is True
    assert "rounds" not in json.loads(draft.quality)
    assert compute_quality_passed(run) is True


def test_no_qualified_angle_does_not_write_or_pass(db, monkeypatch):
    owner = _owner(db)

    class _Client:
        def __init__(self, *_args, **_kwargs):
            self.used_slot = self.used_vendor = self.used_model = ""

        def routing(self):
            return {}

        def chat_json(self, *_args, **_kwargs):
            return {"angles": [], "questions": ["这篇内容最希望读者采取什么行动？"]}

    monkeypatch.setattr(llm_router, "RoutedLLM", _Client)
    draft = Draft(creator_id=owner.id, title="空泛主题", source="ai")
    db.add(draft)
    db.commit()
    run = pipeline.create_generation_run(db, creator_id=owner.id, draft_id=draft.id, topic=draft.title)
    result = pipeline.run_generation_pipeline(db, run, draft)
    assert result["status"] == "needs_input"
    assert result["questions"]
    assert run.quality_passed is False
    assert json.loads(run.reviews_json) == []


def test_review_failure_never_passes(db, monkeypatch):
    owner = _owner(db)
    run = GenerationRun(creator_id=owner.id, topic="主题", status="succeeded", quality_passed=True)
    assert compute_quality_passed(run) is False

    class _Client:
        def __init__(self, *_args, **_kwargs):
            pass

        def chat_json(self, *_args, **_kwargs):
            raise LLMError("评审未执行")

    monkeypatch.setattr(llm_router, "RoutedLLM", _Client)
    with pytest.raises(LLMError):
        pipeline._call_json(
            db, run, client=_Client(), stage="review", prompt_key="author_review",
            user="x", budget_key="debate_critique", require=("logic_passed",),
        )


def test_fabricated_experience_and_number_are_rejected():
    data = {
        "title": "我的经历",
        "cover_text": "三个月",
        "script": "我试过三个月，收入翻了一倍。",
        "claims": [{"text": "我试过三个月", "type": "author_experience", "evidence_ids": ["online:1"]}],
    }
    with pytest.raises(GenerationValidationError):
        validate_claims(data, asset_kinds={}, online_source_ids={"online:1"}, evidence_text="外部数字三个月")


def test_final_hash_change_invalidates_old_review():
    run = GenerationRun(creator_id=1, topic="主题", status="succeeded", quality_passed=True)
    run.attempts_json = json.dumps({
        "stages": {name: {"status": "completed"} for name in ("assets", "angles", "blueprint", "writing", "review")},
        "write_count": 1, "review_count": 1, "revision_count": 0,
    })
    run.final_script_hash = "new-hash"
    run.reviews_json = json.dumps([{
        "executed": True, "script_hash": "old-hash", "logic_passed": True,
        "hard_issues": [], "attraction_score": 5, "author_score": 5,
    }])
    assert compute_quality_passed(run) is False


def test_daily_generation_needs_input_does_not_stay_running(db, monkeypatch):
    from app.services import draft_status

    _owner(db)
    monkeypatch.setattr(
        pipeline,
        "run_generation_pipeline",
        lambda *_args, **_kwargs: {"status": "needs_input", "message": "缺少关键目标"},
    )
    with pytest.raises(GenerationValidationError):
        pipeline.generate_author_draft(db, "缺信息的主题")
    draft = db.query(Draft).one()
    state = draft_status.read(db, draft.id)
    assert state is not None and state["state"] == "failed"
    assert "缺少关键目标" in state["note"]


def test_vague_quantity_is_not_treated_as_fabricated_precision():
    data = {
        "title": "先确定关键任务",
        "cover_text": "别贪多",
        "script": "先确定一两个关键任务，再逐个推进。",
        "claims": [{"text": "先确定一两个关键任务", "type": "opinion", "evidence_ids": []}],
    }
    validate_claims(data, asset_kinds={}, online_source_ids=set(), evidence_text="")
    assert extract_numbers(data["script"]) == []


def _angle(angle_id: str, promise: str, **patch):
    data = {
        "angle_id": angle_id,
        "title": promise,
        "audience": "受众",
        "promise": promise,
        "hook": "问题",
        "reasoning": ["一步"],
        "required_asset_ids": [],
        "external_source_ids": [],
        "claim_type": "inference",
        "author_fit": 20,
        "evidence_fit": 20,
        "audience_value": 20,
        "distinctiveness": 20,
        "risk": "",
    }
    data.update(patch)
    return data


def test_angle_threshold_duplicates_and_personal_evidence():
    accepted, rejected, _questions = validate_angles(
        {"angles": [_angle("a1", "同一承诺"), _angle("a2", "同一承诺"), _angle("a3", "低分", author_fit=1)]},
        asset_ids=set(), asset_kinds={}, online_source_ids=set(),
    )
    assert len(accepted) == 1
    assert len(rejected) == 2
    _accepted, rejected, _questions = validate_angles(
        {"angles": [_angle("a4", "我的真实经历", claim_type="author_experience")]},
        asset_ids=set(), asset_kinds={}, online_source_ids=set(),
    )
    assert "个人经历角度没有作者经历资产" in rejected[0]["reject_reasons"]


def test_blueprint_requires_action_preconditions_and_known_evidence():
    angle = _angle("a1", "唯一承诺")
    with pytest.raises(GenerationValidationError):
        validate_blueprint(
            {
                "goal": "目标",
                "audience": "受众",
                "core_promise": "唯一承诺",
                "hook": {"text": "开头", "payoff": "第一步"},
                "reasoning_steps": [{"claim": "结论", "claim_type": "opinion", "evidence_ids": [], "inference": "关系", "limitations": "边界"}],
                "actions": [{"precondition": "", "action": "行动", "expected_result": "结果"}],
                "ending": "回扣",
            },
            angle=angle,
            asset_ids=set(),
            online_source_ids=set(),
        )


def test_numbers_need_evidence_but_simple_calculation_is_allowed():
    data = {
        "title": "预算是多少",
        "cover_text": "四百元",
        "script": "两项各二百元，合计四百元。",
        "claims": [{"text": "合计四百元", "type": "inference", "evidence_ids": ["input:topic"]}],
    }
    validate_claims(
        data,
        asset_kinds={},
        online_source_ids=set(),
        evidence_text="两项各二百元，200+200=400；四百元",
    )
    data["script"] = "花了三百元。"
    data["claims"] = [{"text": "花了三百元", "type": "inference", "evidence_ids": ["input:topic"]}]
    with pytest.raises(GenerationValidationError):
        validate_claims(data, asset_kinds={}, online_source_ids=set(), evidence_text="200+200=400")


def test_attraction_or_author_score_below_four_cannot_pass():
    run = GenerationRun(creator_id=1, topic="主题", status="succeeded")
    run.attempts_json = json.dumps({
        "stages": {name: {"status": "completed"} for name in ("assets", "angles", "blueprint", "writing", "review")},
        "write_count": 1,
        "review_count": 1,
        "revision_count": 0,
    })
    run.final_script_hash = "hash"
    run.reviews_json = json.dumps([{
        "executed": True,
        "script_hash": "hash",
        "logic_passed": True,
        "hard_issues": [],
        "attraction_score": 3.9,
        "author_score": 5,
    }])
    assert compute_quality_passed(run) is False


def test_missing_inference_evidence_defaults_to_author_input():
    raw = {
        "goal": "目标",
        "audience": "受众",
        "core_promise": "唯一承诺",
        "hook": {"text": "开头", "payoff": "第一步"},
        "reasoning_steps": [{
            "claim": "推理结论",
            "claim_type": "inference",
            "evidence_ids": None,
            "inference": "由本次输入约束推出",
            "limitations": "输入变化时结论变化",
        }],
        "actions": [{"precondition": "前提", "action": "行动", "expected_result": "结果"}],
        "ending": "回扣",
    }
    normalized = validate_blueprint(raw, angle=_angle("a1", "唯一承诺"), asset_ids=set(), online_source_ids=set())
    assert normalized["reasoning_steps"][0]["evidence_ids"] == ["input:topic"]
    draft = {
        "title": "标题",
        "cover_text": "封面",
        "script": "这是由当前约束得出的推理结论。",
        "claims": [{"text": "推理结论", "type": "inference", "evidence_ids": None}],
    }
    validate_claims(draft, asset_kinds={}, online_source_ids=set(), evidence_text="")
    assert draft["claims"][0]["evidence_ids"] == ["input:topic"]


def test_hard_review_issue_must_quote_real_script_text():
    raw = {
        "logic_passed": False,
        "hard_issues": [{"quote": "不存在的原句", "problem": "凭空挑错", "fix": "修改"}],
        "attraction_score": 4,
        "author_score": 4,
        "issues": [],
    }
    with pytest.raises(GenerationValidationError, match="原句不存在"):
        pipeline._review_shape(raw, "hash", "正文确实存在的前提")
    raw["hard_issues"][0]["quote"] = "正文确实存在的前提"
    review = pipeline._review_shape(raw, "hash", "正文确实存在的前提")
    assert review["hard_issues"][0]["quote"] == "正文确实存在的前提"


def test_contract_normalization_preserves_hard_rules():
    draft = {
        "title": "月薪一万块怎么存",
        "cover_text": "先算清楚",
        "script": "月薪一万块，先确定储蓄比例。",
        "claims": [{"text": "先确定储蓄比例。", "type": "personal_opinion", "evidence_ids": []}],
    }
    validate_claims(draft, asset_kinds={}, online_source_ids=set(), evidence_text="月薪一万")
    assert draft["claims"][0]["type"] == "opinion"
    draft["claims"] = [{"text": "不存在的句子", "type": "opinion", "evidence_ids": []}]
    with pytest.raises(GenerationValidationError):
        validate_claims(draft, asset_kinds={}, online_source_ids=set(), evidence_text="月薪一万")


def test_calculation_in_script_is_traceable():
    draft = {
        "title": "七天样本",
        "cover_text": "140张",
        "script": "每天20张，7×20=140，就是140张。",
        "claims": [{"text": "140张", "type": "inference", "evidence_ids": []}],
    }
    validate_claims(draft, asset_kinds={}, online_source_ids=set(), evidence_text="")


def test_programmatic_style_assets_have_real_multi_document_evidence(db):
    from app.services.author_assets import build_programmatic_style_assets, validate_asset_evidence

    owner = _owner(db)
    first = _video(db, owner, "为什么工作总是做不完？先只保一件。", "结构一")
    second = _video(db, owner, "别贪多，先把这件事做完。", "结构二")
    created = build_programmatic_style_assets(db, owner.id, [first, second])
    assert created == 2
    rows = db.query(AuthorAsset).all()
    assert {row.asset_kind for row in rows} == {"structure", "expression"}
    assert all(row.status == "active" for row in rows)
    assert all(validate_asset_evidence(db, row) for row in rows)
    assert all(len(json.loads(row.evidence_refs)) >= 2 for row in rows)
