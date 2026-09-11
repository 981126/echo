"""R-130/R-131：人设版本归因、风格范本/样本扩容、改写稿 few-shot、结构模板、生成后自检测试。"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import Base
from app.models.draft import Draft
from app.models.feedback import Feedback
from app.models.kv import Kv
from app.models.persona import PersonaTag
from app.models.platform import Creator
from app.models.prompt import AiPrompt
from app.models.video import Transcript, Video
from app.services import generation as gen
from app.services import prompt_service as ps
from app.services.prompt_service import PromptOptimizeError


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


def _video(db, owner, title, text, *, plays=0):
    v = Video(creator_id=owner.id, filename=f"{title}.mp4", title=title, is_ad=False)
    db.add(v)
    db.flush()
    db.add(Transcript(video_id=v.id, transcript_text=text, corrected_text=text))
    db.flush()
    return v


def _set_kv(db, key, value):
    row = db.get(Kv, key)
    if row is None:
        db.add(Kv(key=key, value=value))
    else:
        row.value = value
    db.commit()


# ---------- R-130：分组 / 人设版本归因 ----------


def test_prompt_group_splits_persona_engine_from_production():
    assert ps.prompt_group("persona_init") == "persona_engine"
    assert ps.prompt_group("persona_compare") == "persona_engine"
    assert ps.prompt_group("generation") == "production"
    assert ps.prompt_group("correct") == "production"
    assert set(ps.RULE_KEYS) == {"video_tags", "correct", "diff", "review"}


def test_version_effect_marks_mixed_persona(db):
    owner = _owner(db)
    db.add_all(
        [
            Draft(creator_id=owner.id, script="一", source="ai", prompt_version=2, persona_version=5),
            Draft(creator_id=owner.id, script="二", source="ai", prompt_version=2, persona_version=6),
        ]
    )
    db.commit()
    effect = ps.version_effect(db, "generation")
    row = next(r for r in effect if r["version"] == 2)
    assert row["persona_versions"] == [5, 6]
    assert row["mixed_persona"] is True


# ---------- R-131：生成上下文数据侧增强 ----------


def test_rewrite_examples_empty_without_pairs(db):
    _owner(db)
    assert gen._rewrite_examples(db) == ""


def test_rewrite_examples_prefers_approved_pairs(db):
    owner = _owner(db)
    d1 = Draft(creator_id=owner.id, script="改后A", original_script="原稿A", source="ai", title="A")
    d2 = Draft(creator_id=owner.id, script="改后B", original_script="原稿B", source="ai", title="B")
    db.add_all([d1, d2])
    db.flush()
    db.add(Feedback(draft_id=d2.id, rating=5, liked=True))
    db.commit()
    text = gen._rewrite_examples(db, limit=1)
    assert "作者改后" in text and "改后B" in text  # 高星的那对排前
    assert "改后A" not in text


def test_style_anchor_samples_follows_kv(db):
    owner = _owner(db)
    v1 = _video(db, owner, "范本", "这是范本文案")
    _video(db, owner, "普通", "这是普通文案")
    _set_kv(db, "style_anchor_video_ids", json.dumps([v1.id]))
    assert gen._style_anchor_samples(db) == ["这是范本文案"]


def test_style_sample_count_bounds(db):
    owner = _owner(db)
    for i in range(10):
        _video(db, owner, f"v{i}", f"第{i}条文案内容")
    _set_kv(db, "style_sample_count", "99")
    assert len(gen._style_samples(db, "文案")) <= 8
    _set_kv(db, "style_sample_count", "1")
    assert len(gen._style_samples(db, "文案")) >= 1


def test_structure_templates_falls_back_to_videos_without_feedback(db):
    owner = _owner(db)
    _video(db, owner, "高表现", "第一句话。中间内容。最后一句引导。")
    text = gen._structure_templates(db)
    assert "开场" in text and "结尾" in text


def test_self_check_flags_redline_and_style_gap(db):
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
    issues, coverage = gen._self_check(db, "我不卖课不收费割韭菜，直接说重点。")
    assert any("红线" in i for i in issues)
    assert coverage == 0.0


def test_generate_draft_retries_once_and_records_quality(db, monkeypatch):
    owner = _owner(db)
    db.add(
        PersonaTag(
            creator_id=owner.id,
            label="不卖课不收费割韭菜",
            description="",
            category="redline",
            status="confirmed",
            version=7,
        )
    )
    db.commit()

    class _FakeLLM:
        def __init__(self, *a, **kw):
            self.calls = 0

        def chat_json(self, messages, **kwargs):  # noqa: ANN001, ANN003
            self.calls += 1
            return {
                "title": "标题",
                "cover_text": "封面",
                "script": "我不卖课不收费割韭菜，这是脚本正文。",
                "shells": {},
            }

    monkeypatch.setattr(gen, "_generation_llm", lambda _db, _settings=None: _FakeLLM())  # R-135：改走模型策略解析
    draft = gen.generate_draft(db, "测试选题")
    quality = json.loads(draft.quality)
    assert quality["attempts"] == 2  # 第一次自检不过 → 自动重写一次
    assert quality["passed"] is False
    assert any("红线" in i for i in quality["issues"])
    assert draft.persona_version == 7  # R-130：记录生成时的人设版本


def test_generate_draft_mock_path_records_version(db):
    owner = _owner(db)
    db.add(PersonaTag(creator_id=owner.id, label="风格", status="confirmed", version=4, category="style"))
    db.commit()
    draft = gen.generate_draft(db, "无密钥选题")  # 无密钥 → mock 兜底
    quality = json.loads(draft.quality)
    assert quality["mock"] is True
    assert draft.persona_version == 4


# ---------- R-131：降权（提醒 + 手动一键） ----------


def test_maybe_notify_prompt_refresh_threshold(db):
    assert ps.maybe_notify_prompt_refresh(db, threshold=3) is False
    assert ps.maybe_notify_prompt_refresh(db, threshold=3) is False
    assert ps.maybe_notify_prompt_refresh(db, threshold=3) is True
    from app.models.notification import Notification

    assert db.query(Notification).filter(Notification.kind == "prompt_refresh_hint").count() == 1


def test_optimize_rule_keys_task_skips_when_no_samples(db):
    _owner(db)
    result = ps.optimize_rule_keys_task(db, {"keys": ["video_tags", "correct"]})
    assert "产出候选 0 个" in result["message"]
    assert len(result["skipped"]) == 2


def test_optimize_rule_keys_task_reports_failure(db, monkeypatch):
    _owner(db)

    def _boom(_db, _key, _material=""):
        raise PromptOptimizeError("候选自检未通过：测试")

    monkeypatch.setattr(ps, "optimize", _boom)
    result = ps.optimize_rule_keys_task(db, {"keys": ["video_tags"]})
    assert len(result["failed"]) == 1
