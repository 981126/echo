"""R-129：按 key 语料、候选契约自检、分层拼接、评测打分、版本归因测试。"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import Base
from app.models.draft import Draft
from app.models.feedback import Feedback
from app.models.persona import PersonaTag
from app.models.platform import Creator
from app.models.prompt import AiPrompt
from app.models.video import Transcript, Video
from app.services import prompt_contract as pc
from app.services import prompt_eval as pe
from app.services import prompt_service as ps
from app.services.prompt_service import PromptOptimizeError, optimize


@pytest.fixture()
def db(tmp_path):
    eng = create_engine(f"sqlite:///{tmp_path}/t.db", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=eng)
    session = sessionmaker(bind=eng, autoflush=False, autocommit=False)()
    for key in ps.PROMPT_META:
        session.add(AiPrompt(key=key, version=1, content=ps.default_content(key), status="enabled", note="t"))
    session.commit()
    yield session
    session.close()
    eng.dispose()


def _owner(db) -> Creator:
    owner = Creator(kind="owner", name="我", is_current=True)
    db.add(owner)
    db.commit()
    return owner


def _video(db, owner, title, text, *, raw="", tags=None, is_ad=False, confirmed=False):
    v = Video(creator_id=owner.id, filename=f"{title}.mp4", title=title, is_ad=is_ad)
    if tags is not None:
        v.tags = tags
    v.tags_confirmed = confirmed
    db.add(v)
    db.flush()
    db.add(Transcript(video_id=v.id, transcript_text=raw or text, corrected_text=text))
    db.flush()
    return v


# ---------- 按 key 语料 ----------


def test_material_video_tags_uses_real_labels(db):
    owner = _owner(db)
    _video(db, owner, "v1", "讲简历包装的转写稿", tags='["简历包装"]', confirmed=True)
    text, sources = pc.material_for("video_tags", db)
    assert "真实标注" in text and "简历包装" in text
    assert sources


def test_material_correct_pairs_raw_and_fixed(db):
    owner = _owner(db)
    _video(db, owner, "v1", "修正后的稿子", raw="休正前的稿子")
    text, sources = pc.material_for("correct", db)
    assert "【原始转写】" in text and "【校对后】" in text
    assert sources


def test_material_missing_returns_empty(db):
    _owner(db)
    text, sources = pc.material_for("review", db)  # 无复盘报告
    assert text == "" and sources == []


def test_material_diff_uses_rewrite_pairs(db):
    owner = _owner(db)
    db.add(Draft(creator_id=owner.id, original_script="AI 原稿内容", script="作者改后的内容", source="ai"))
    db.commit()
    text, sources = pc.material_for("diff", db)
    assert "【AI 原稿】" in text and "【作者改后】" in text
    assert sources


# ---------- 候选契约自检 ----------


def test_validate_candidate_blocks_written_in_redline_and_identity(db):
    owner = _owner(db)
    db.add(
        PersonaTag(
            creator_id=owner.id,
            label="不卖课不收费割韭菜",
            description="",
            category="redline",
            status="confirmed",
            version=1,
        )
    )
    db.commit()
    contract = pc.contract_for("generation")
    base = "你是脚本创作专家，围绕选题写作。\n\n" + contract

    ok, reason = pc.validate_candidate("generation", base, db)
    assert ok, reason

    bad_redline = base + "\n不卖课不收费割韭菜"
    ok, reason = pc.validate_candidate("generation", bad_redline, db)
    assert not ok and "红线" in reason

    bad_identity = "你是 R-128 本人，来上海打拼。\n\n" + contract
    ok, reason = pc.validate_candidate("generation", bad_identity, db)
    assert not ok and "身份" in reason


def test_validate_candidate_checks_markers_and_budget(db):
    ok, reason = pc.validate_candidate("generation", "写了很长一段但没有任何契约字段的内容，长度足够二十字以上")
    assert not ok and "缺少输出契约字段" in reason

    ok, reason = pc.validate_candidate("correct", "修" * 2000)
    assert not ok and "长度预算" in reason


def test_assemble_candidate_appends_fixed_contract():
    full = pc.assemble_candidate("video_tags", "你是视频内容标注助手。")
    assert full.endswith(pc.contract_for("video_tags"))
    assert "main_topics" in full


# ---------- optimize 流程 ----------


class _FakeLLM:
    def __init__(self, outputs: list[str]):
        self.outputs = list(outputs)
        self.calls = 0

    def chat(self, messages, **kwargs):  # noqa: ANN001, ANN003
        self.calls += 1
        return self.outputs.pop(0) if self.outputs else ""


def test_optimize_uses_key_material_and_appends_contract(db, monkeypatch):
    owner = _owner(db)
    _video(db, owner, "v1", "讲简历包装", tags='["简历包装"]', confirmed=True)
    db.commit()
    fake = _FakeLLM(["你是视频内容标注助手，按作者口径判断赛道与广告。"])
    monkeypatch.setattr(ps, "_optimize_llm", lambda _db: (fake, "deepseek"))
    monkeypatch.setattr(ps, "_start_eval", lambda _db, _key, _version: None)

    row = optimize(db, "video_tags")
    assert row.status == "candidate"
    assert row.content.endswith(pc.contract_for("video_tags"))
    assert "已确认标签素材" in row.note  # 用的是 video_tags 自己的样本
    assert fake.calls == 1


def test_optimize_retries_once_then_raises(db, monkeypatch):
    owner = _owner(db)
    _video(db, owner, "v1", "讲简历包装", tags='["简历包装"]', confirmed=True)
    db.commit()
    # 契约段由程序拼接，所以「缺字段」不会失败；真正的自检失败是「写死事实」（这里是身份写死）
    fake = _FakeLLM(["你是 R-128 本人，中专学历来上海打拼。", "你是 R-128 本人，月入三万。"])
    monkeypatch.setattr(ps, "_optimize_llm", lambda _db: (fake, "deepseek"))
    monkeypatch.setattr(ps, "_start_eval", lambda _db, _key, _version: None)

    with pytest.raises(PromptOptimizeError) as exc:
        optimize(db, "video_tags")
    assert "自检未通过" in str(exc.value)
    assert fake.calls == 2  # 失败自动重试 1 次
    assert db.query(AiPrompt).filter(AiPrompt.status == "candidate").count() == 0


def test_optimize_sample_insufficient_raises(db, monkeypatch):
    _owner(db)
    monkeypatch.setattr(ps, "_start_eval", lambda _db, _key, _version: None)
    with pytest.raises(PromptOptimizeError) as exc:
        optimize(db, "video_tags")  # 没有任何已确认标签素材
    assert "样本不足" in str(exc.value)


# ---------- 拒绝候选 / 版本效果 ----------
def test_reject_candidate_marks_rejected(db):
    db.add(AiPrompt(key="generation", version=2, content="候选内容占位符超过二十个字符", status="candidate"))
    db.commit()
    row = ps.reject_candidate(db, "generation", 2)
    assert row is not None and row.status == "rejected"
    assert ps.reject_candidate(db, "generation", 2) is None  # 已处理不能再拒


def test_version_effect_aggregates_feedback(db):
    owner = _owner(db)
    d1 = Draft(creator_id=owner.id, script="一稿", source="ai", prompt_version=3)
    d2 = Draft(creator_id=owner.id, script="二稿", source="ai", prompt_version=3)
    d3 = Draft(creator_id=owner.id, script="三稿", source="ai", prompt_version=1)
    db.add_all([d1, d2, d3])
    db.flush()
    db.add_all(
        [
            Feedback(draft_id=d1.id, rating=5, liked=True),
            Feedback(draft_id=d2.id, rating=3),
            Feedback(draft_id=d3.id, rating=2),
        ]
    )
    db.commit()
    effect = ps.version_effect(db, "generation")
    by_ver = {r["version"]: r for r in effect}
    assert by_ver[3]["drafts"] == 2 and by_ver[3]["avg_rating"] == 4.0 and by_ver[3]["used"] == 1
    assert by_ver[1]["avg_rating"] == 2.0
    assert ps.version_effect(db, "correct") == []


# ---------- 评测 ----------


def test_format_ok_and_score_outputs():
    assert pe._format_ok("generation", '{"title":"t","script":"s"}')
    assert not pe._format_ok("generation", '{"title":"t"}')
    assert not pe._format_ok("generation", "```json\n{}\n```")
    assert pe._format_ok("correct", "这是校对后的文本。")

    good = pe._score_outputs("generation", ['{"title":"t","script":"s"}'] * 2, [], [])
    bad = pe._score_outputs("generation", ["不是 JSON", "也不是"], [], [])
    assert good["score"] > bad["score"]
    assert good["format_rate"] == 1.0 and bad["format_rate"] == 0.0


def test_evaluate_unsupported_key_stores_reason(db):
    db.add(AiPrompt(key="chat", version=2, content="候选内容占位符超过二十个字符", status="candidate"))
    db.commit()
    row = pe.evaluate(db, "chat", 2)
    assert row is not None and row.supported is False
    assert "暂不支持" in row.reason


def test_evaluate_without_golden_samples(db):
    db.add(AiPrompt(key="video_tags", version=2, content="候选内容占位符超过二十个字符", status="candidate"))
    db.commit()
    row = pe.evaluate(db, "video_tags", 2)
    assert row is not None and row.supported is False
    assert "样本不足" in row.reason


def test_generate_draft_records_prompt_version(db, monkeypatch):
    from app.services import generation

    _owner(db)
    # 无密钥 → generate_draft 走 mock 兜底，仍应记录当前启用版本
    draft = generation.generate_draft(db, "测试选题")
    assert draft.prompt_version == 1


# ---------- R-132：变更说明 / 长度约束 ----------


def test_split_change_note():
    body, note = pc.split_change_note("正文内容\n【变更说明】\n- 补充了广告判定")
    assert body == "正文内容"
    assert "补充了广告判定" in note
    body2, note2 = pc.split_change_note("只有正文")
    assert body2 == "只有正文" and note2 == ""


def test_split_change_note_strips_body_header():
    # 真实模型会输出「【提示词】/【变更说明】」两个小标题，都不能留进正文（实测踩过）
    body, note = pc.split_change_note("【提示词】\n你是标注助手。\n【变更说明】\n- 调整了广告判定")
    assert body == "你是标注助手。"
    assert "调整了广告判定" in note
    body2, note2 = pc.split_change_note("【提示词】\n只有正文没有说明")
    assert body2 == "只有正文没有说明" and note2 == ""


def test_optimize_rejects_header_only_body(db, monkeypatch):
    owner = _owner(db)
    _video(db, owner, "v1", "讲简历包装", tags='["简历包装"]', confirmed=True)
    db.commit()
    fake = _FakeLLM(["【提示词】\n【变更说明】\n- 没写正文", "【提示词】\n【变更说明】\n- 还是没写"])
    monkeypatch.setattr(ps, "_optimize_llm", lambda _db: (fake, "deepseek"))
    monkeypatch.setattr(ps, "_start_eval", lambda _db, _key, _version: None)

    with pytest.raises(PromptOptimizeError) as exc:
        optimize(db, "video_tags")
    assert "过短" in str(exc.value)
    assert db.query(AiPrompt).filter(AiPrompt.status == "candidate").count() == 0


def test_max_candidate_chars_floor_and_ratio():
    limit = pc.max_candidate_chars("video_tags", "短")
    assert limit == 300  # 下限兜底
    long_current = "提示词" * 200
    expected = max(int((len(long_current) + len(pc.contract_for("video_tags"))) * 1.5), 300)
    assert pc.max_candidate_chars("video_tags", long_current) == expected


def test_optimize_rejects_overlong_candidate(db, monkeypatch):
    owner = _owner(db)
    _video(db, owner, "v1", "讲简历包装", tags='["简历包装"]', confirmed=True)
    db.commit()
    fake = _FakeLLM(["很长" * 3000, "还是" * 3000])
    monkeypatch.setattr(ps, "_optimize_llm", lambda _db: (fake, "deepseek"))
    monkeypatch.setattr(ps, "_start_eval", lambda _db, _key, _version: None)

    with pytest.raises(PromptOptimizeError) as exc:
        optimize(db, "video_tags")
    assert "过长" in str(exc.value)
    assert fake.calls == 2  # 重试 1 次后仍超限 → 丢弃
    assert db.query(AiPrompt).filter(AiPrompt.status == "candidate").count() == 0


def test_optimize_stores_change_note_and_strips_it_from_body(db, monkeypatch):
    owner = _owner(db)
    _video(db, owner, "v1", "讲简历包装", tags='["简历包装"]', confirmed=True)
    db.commit()
    fake = _FakeLLM(["你是视频内容标注助手，请按作者的真实口径判断赛道、广告与标签。\n【变更说明】\n- 补充了广告判定标准\n- 依据：已确认标签素材"])
    monkeypatch.setattr(ps, "_optimize_llm", lambda _db: (fake, "deepseek"))
    monkeypatch.setattr(ps, "_start_eval", lambda _db, _key, _version: None)

    row = optimize(db, "video_tags")
    assert "变更说明" in row.note
    assert "补充了广告判定标准" in row.note
    assert "变更说明" not in row.content  # 变更说明不进提示词正文
    assert row.content.endswith(pc.contract_for("video_tags"))
