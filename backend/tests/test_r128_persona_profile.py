"""R-128：逐篇提取缓存、增量 vs 全量 5% 对齐校验、回退与落库测试。"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import Base
from app.models.notification import Notification
from app.models.persona import PersonaCheck, PersonaTag
from app.models.platform import Creator
from app.models.video import Transcript, Video
from app.services import ingest as ingest_mod
from app.services import persona_profile as pp


@pytest.fixture()
def db(tmp_path):
    eng = create_engine(f"sqlite:///{tmp_path}/t.db", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=eng)
    session = sessionmaker(bind=eng, autoflush=False, autocommit=False)()
    yield session
    session.close()
    eng.dispose()


def _owner(db) -> Creator:
    owner = Creator(kind="owner", name="我", is_current=True)
    db.add(owner)
    db.commit()
    return owner


def _add_video(db, owner, title: str, text: str) -> Video:
    v = Video(creator_id=owner.id, filename=f"{title}.mp4", title=title, is_ad=False)
    db.add(v)
    db.flush()
    db.add(Transcript(video_id=v.id, transcript_text=text, corrected_text=""))
    db.flush()
    return v


class _CountingService:
    def __init__(self):
        self.calls = 0

    def analyze_one(self, text: str) -> dict:
        self.calls += 1
        return {"tags": [{"label": f"标签{text}", "description": "", "dimension": "语气"}], "redlines": []}

    def merge_full(self, parts):
        return {"tags": [p["tags"][0] for p in parts], "redlines": []}

    def merge_incremental(self, current, new_part):
        return new_part

    def compare_profiles(self, a, b):
        return {"score": 100.0, "reason": "ok"}


def test_extract_pieces_caches_by_content(db):
    _owner(db)
    fake = _CountingService()
    texts = ["第一篇文案", "第二篇文案"]
    first = pp.extract_pieces(db, texts, service_factory=lambda: fake, use_cache=True)
    assert len(first) == 2 and fake.calls == 2
    # 同样内容再跑一次：命中缓存，不再调用 AI
    second = pp.extract_pieces(db, texts, service_factory=lambda: fake, use_cache=True)
    assert fake.calls == 2
    assert second == first


def test_profile_coverage_fuzzy_and_missing():
    full = {
        "tags": [
            {"label": "说话直接", "description": ""},
            {"label": "价值观正", "description": ""},
        ],
        "redlines": ["不接软广"],
    }
    # 「说话直接」被「说话很直接」模糊覆盖；缺「价值观正」
    incremental = {"tags": [{"label": "说话很直接", "description": ""}], "redlines": []}
    coverage, missing = pp.profile_coverage(incremental, full)
    assert 0 < coverage < 1
    assert {m["label"] for m in missing} == {"价值观正", "不接软广"}


def test_compare_profiles_pass_and_fallback():
    full = {"tags": [{"label": "A", "description": ""}, {"label": "B", "description": ""}], "redlines": []}
    same = {"tags": [{"label": "A", "description": ""}, {"label": "B", "description": ""}], "redlines": []}
    ok = pp.compare_profiles(same, full, service_factory=lambda: _CountingService())
    assert ok["passed"] and not ok["fallback"] and ok["coverage"] == 1.0

    partial = {"tags": [{"label": "A", "description": ""}], "redlines": []}
    bad = pp.compare_profiles(partial, full, service_factory=lambda: _CountingService())
    assert not bad["passed"] and bad["fallback"]
    assert bad["chosen"] == full
    assert len(bad["missing"]) == 1


class _FallbackService:
    """全量有 A/B/C，增量只并进 A → 覆盖率 1/3，语义 40 → 必须回退。"""

    def analyze_one(self, text: str) -> dict:
        return {"tags": [{"label": "A", "description": "", "dimension": "语气"}], "redlines": []}

    def merge_full(self, parts):
        return {
            "tags": [
                {"label": "A", "description": "", "dimension": "语气"},
                {"label": "B", "description": "", "dimension": "价值观"},
                {"label": "C", "description": "", "dimension": "口头禅"},
            ],
            "redlines": [],
        }

    def merge_incremental(self, current, new_part):
        return {"tags": [{"label": "A", "description": "", "dimension": "语气"}], "redlines": []}

    def compare_profiles(self, a, b):
        return {"score": 40.0, "reason": "缺 B/C"}


def test_incremental_task_fallback_to_full_and_notifies(db, monkeypatch):
    owner = _owner(db)
    _add_video(db, owner, "v1", "第一篇")
    _add_video(db, owner, "v2", "第二篇")
    db.commit()
    monkeypatch.setattr(ingest_mod, "PersonaService", lambda: _FallbackService())

    result = ingest_mod.persona_incremental_task(db, {"creator_id": owner.id, "video_id": 0})

    check = db.query(PersonaCheck).order_by(PersonaCheck.id.desc()).first()
    assert check is not None
    assert check.fallback is True and check.passed is False
    assert abs(check.coverage - 1 / 3) < 0.01
    assert check.semantic == 40.0
    # 回退后按全量结果落库 → A/B/C 三条建议都在
    labels = {t.label for t in db.query(PersonaTag).all()}
    assert labels == {"A", "B", "C"}
    detail = json.loads(check.detail)
    assert len(detail["missing"]) == 2
    assert "回退" in result["message"]
    # 超标通知已写
    assert db.query(Notification).filter(Notification.kind == "persona_check").count() == 1


def test_learning_material_includes_dimensioned_persona(db):
    from app.services.prompt_service import learning_material

    owner = _owner(db)
    db.add(
        PersonaTag(
            creator_id=owner.id,
            label="直白犀利",
            description="说话不绕弯子",
            dimension="语气",
            category="style",
            status="confirmed",
            version=1,
        )
    )
    _add_video(db, owner, "v1", "这是一篇用于语料的作者真实文案")
    db.commit()
    text = learning_material(db)
    # 候选提示词语料里带上了「归纳合并后的人设档案」（含维度）
    assert "[语气] 直白犀利" in text


def test_persist_suggestions_caps_and_flags(db):
    profile = {
        "tags": [{"label": f"标签{i}", "description": "", "dimension": ""} for i in range(200)],
        "redlines": [],
    }
    res = pp.persist_suggestions(db, None, profile, max_items=10)
    assert res["added"] == 10
    assert res["truncated"] is True
    assert db.query(PersonaTag).count() == 10


class _PassService(_FallbackService):
    def merge_incremental(self, current, new_part):
        return self.merge_full([new_part])

    def compare_profiles(self, a, b):
        return {"score": 98.0, "reason": "等价"}


def test_incremental_task_passes_without_fallback(db, monkeypatch):
    owner = _owner(db)
    _add_video(db, owner, "v1", "第一篇")
    db.commit()
    monkeypatch.setattr(ingest_mod, "PersonaService", lambda: _PassService())

    ingest_mod.persona_incremental_task(db, {"creator_id": owner.id, "manual": True})

    check = db.query(PersonaCheck).order_by(PersonaCheck.id.desc()).first()
    assert check.passed is True and check.fallback is False
    assert check.mode == "manual"
    assert db.query(Notification).filter(Notification.kind == "persona_check").count() == 0


def test_merge_full_consolidates_via_llm():
    from unittest.mock import MagicMock

    from app.services.persona import PersonaService

    llm = MagicMock()
    llm.chat_json.return_value = {
        "tags": [{"label": "合并后", "description": "", "dimension": "语气"}],
        "redlines": [],
    }
    service = PersonaService(llm=llm)
    parts = [{"tags": [{"label": f"原标签{i}", "description": "", "dimension": "语气"}], "redlines": []} for i in range(20)]
    out = service.merge_full(parts)
    assert out["tags"][0]["label"] == "合并后"
    # 小档案先走一次全局归纳
    assert llm.chat_json.call_count == 1


def test_merge_full_batches_when_model_does_not_compact():
    from unittest.mock import MagicMock

    from app.services.persona import PersonaService

    def _big(seed: int) -> list[dict]:
        return [
            {"label": hashlib.md5(f"{seed}-{i}".encode()).hexdigest()[:8], "description": "", "dimension": "语气"}
            for i in range(200)
        ]

    llm = MagicMock()

    def fake(messages, **kwargs):
        n = messages[1]["content"].count('"label"')
        # 输入很大时“模型不压缩”，返回 200 条 → 触发分批压缩路径
        return {"tags": _big(7) if n > 30 else _big(3)[:5], "redlines": []}

    llm.chat_json.side_effect = fake
    service = PersonaService(llm=llm)
    parts = [{"tags": [{"label": hashlib.md5(f"p{i}".encode()).hexdigest()[:8], "description": "", "dimension": "语气"}], "redlines": []} for i in range(200)]
    out = service.merge_full(parts)
    # 不会炸成几百条，且确实走了多轮压缩
    assert len(out["tags"]) <= 120
    assert llm.chat_json.call_count > 1


def test_merge_full_mechanical_fallback_on_exception():
    from unittest.mock import MagicMock

    from app.services.persona import PersonaService

    llm = MagicMock()
    llm.chat_json.side_effect = RuntimeError("boom")
    service = PersonaService(llm=llm)
    parts = [
        {"tags": [{"label": "A", "description": "", "dimension": ""}], "redlines": ["不接软广"]},
        {"tags": [{"label": "A", "description": "更长的描述", "dimension": ""}], "redlines": []},
    ]
    out = service.merge_full(parts)
    # AI 不可用也不能丢信号：退回机械合并并保留更完整描述
    assert out["tags"][0]["label"] == "A"
    assert out["tags"][0]["description"] == "更长的描述"
    assert out["redlines"] == ["不接软广"]
