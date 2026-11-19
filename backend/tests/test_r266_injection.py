"""R-266 Phase B：样本注入的触发条件、上限与防照抄。"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest
from conftest import ensure_schema, fresh_engine
from sqlalchemy.orm import sessionmaker

from app.models.opening_sample import OpeningSample
from app.models.platform import Creator
from app.models.video import Video
from app.services.opening_checks import evaluate_opening, max_sample_overlap
from app.services.opening_injection import select_opening_samples


@pytest.fixture()
def db(tmp_path):
    eng = fresh_engine()
    ensure_schema(eng)
    session = sessionmaker(bind=eng, autoflush=False, autocommit=False)()
    yield session
    session.close()


def _owner(db) -> Creator:
    row = Creator(kind="owner", name="我", is_current=True)
    db.add(row)
    db.commit()
    return row


def _sample(db, *, creator_id: int, index: int, text: str, source: str = "own", polarity: str = "neutral", rank: float = 50, finish: float | None = 0.4):
    video = Video(filename=f"r266b-{creator_id}-{index}.mp4", title=f"作品{index}", creator_id=creator_id)
    db.add(video)
    db.commit()
    row = OpeningSample(
        creator_id=creator_id,
        source_kind=source,
        video_id=video.id,
        text=text,
        chars=len(text),
        hook_type="statement",
        finish_5s_rate=finish if source == "own" else None,
        rank_score=rank,
        polarity=polarity,
        baseline_note="" if source == "own" else "同行公开播放，非留人数据",
    )
    db.add(row)
    db.commit()
    return row


def _seed_own(db, owner: Creator, count: int = 21, topic: str = "面试 简历 职场") -> None:
    for index in range(count):
        polarity = "high" if index < 6 else "low" if index < 9 else "neutral"
        _sample(
            db,
            creator_id=owner.id,
            index=index,
            text=f"{topic} 开头 {index}：投简历被拒后我才明白",
            polarity=polarity,
            rank=90 if polarity == "high" else 10 if polarity == "low" else 50,
        )


def test_skips_when_samples_below_threshold(db):
    owner = _owner(db)
    _seed_own(db, owner, count=5)
    result = select_opening_samples(db, owner.id, "面试 简历")
    assert result["injected"] is False
    assert "只有 5 条" in result["reason"]


def test_skips_when_relevance_low(db):
    owner = _owner(db)
    _seed_own(db, owner, count=21, topic="做饭 菜谱 厨房")
    result = select_opening_samples(db, owner.id, "量子物理 黑洞")
    assert result["injected"] is False
    assert "相关度" in result["reason"]


def test_injects_own_high_low_and_peer(db):
    owner = _owner(db)
    _seed_own(db, owner)
    for index in range(4):
        _sample(
            db,
            creator_id=owner.id,
            index=100 + index,
            text="面试 简历 职场 同行开头",
            source="peer",
            polarity="high",
            rank=3.5,
        )
    result = select_opening_samples(db, owner.id, "面试 简历")
    assert result["injected"] is True
    assert result["counts"] == {"own": 21, "peer": 3}
    assert len(result["samples"]) <= 11
    assert sum(1 for item in result["samples"] if item["polarity"] == "low") == 3
    assert sum(1 for item in result["samples"] if item["source_kind"] == "peer") == 3
    assert "不得连续照抄 8 字以上" in result["prompt"]


def test_experience_topic_excludes_peer(db):
    owner = _owner(db)
    _seed_own(db, owner)
    _sample(db, creator_id=owner.id, index=200, text="面试 简历 职场 同行开头", source="peer", polarity="high", rank=3.0)
    result = select_opening_samples(db, owner.id, "面试 简历", has_experience=True)
    assert result["injected"] is True
    assert all(item["source_kind"] == "own" for item in result["samples"])


def test_pure_experience_with_few_high_skips(db):
    owner = _owner(db)
    for index in range(21):
        _sample(
            db,
            creator_id=owner.id,
            index=index,
            text="面试 简历 职场 开头",
            polarity="high" if index < 2 else "neutral",
            rank=80,
        )
    result = select_opening_samples(db, owner.id, "面试 简历", has_experience=True)
    assert result["injected"] is False
    assert "宁缺毋滥" in result["reason"]


def test_overlap_eight_chars_fails():
    script = "投简历被拒三次之后我才明白问题不在简历。"
    samples = ["投简历被拒三次之后我才明白，要先看目标。"]
    result = evaluate_opening(script, samples=samples)
    assert result["passed"] is False
    assert "opening_sample_overlap" in [item["rule"] for item in result["issues"]]
    assert result["metrics"]["max_overlap"] >= 8


def test_overlap_seven_chars_passes():
    script = "投简历被拒三次后我才明白问题不在简历。"
    samples = ["投简历被拒三次以上，要先看目标。"]
    assert max_sample_overlap(script, samples) == 7
    result = evaluate_opening(script, samples=samples)
    overlap_rules = [item["rule"] for item in result["issues"]]
    assert "opening_sample_overlap" not in overlap_rules


def test_overlap_ignores_punctuation():
    script = "投简历，被拒三次后我才明白。"
    samples = ["投简历被拒三次后我才明白"]
    assert max_sample_overlap(script, samples) >= 8
