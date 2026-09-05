"""R-030 写稿体验增强测试：角度上下文/分节反馈/金句库（mock 离线）。"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import Base
from app.models.draft import Draft
from app.models.metrics import MetricsSnapshot
from app.models.persona import PersonaTag
from app.models.platform import Creator
from app.models.video import Transcript, Video
from app.services.feedback import add_feedback
from app.services.generation import benchmark_context_lines
from app.services.persona import suggest_phrase_candidates


@pytest.fixture()
def db(tmp_path):
    eng = create_engine(f"sqlite:///{tmp_path}/t.db", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=eng)
    session = sessionmaker(bind=eng, autoflush=False, autocommit=False)()
    yield session
    session.close()
    eng.dispose()


def _owner(db):
    c = Creator(kind="owner", name="我", is_current=True)
    db.add(c)
    db.commit()
    return c


def test_benchmark_context_lines(db):
    owner = _owner(db)
    bm = Creator(kind="benchmark", parent_id=owner.id, name="对标A", note="短句犀利，常反问")
    db.add(bm)
    db.commit()
    text = benchmark_context_lines(db)
    assert "对标A" in text and "短句犀利" in text


def test_feedback_dim_scores(db):
    d = Draft(title="测试稿")
    db.add(d)
    db.commit()
    row = add_feedback(db, d.id, rating=4, hook_score=5, pace_score=3, ending_score=1, style_score=4)
    assert row.hook_score == 5
    assert row.pace_score == 3
    assert row.ending_score == 1
    assert row.style_score == 4


def test_phrase_candidates_from_transcript(db):
    owner = _owner(db)
    v = Video(filename="mock_high.mp4", creator_id=owner.id, title="高表现素材", is_ad=False)
    db.add(v)
    db.commit()
    v.transcript = Transcript(
        video_id=v.id,
        corrected_text="大家好，今天聊聊面试。薪资可以谈，但别只盯着钱。先想清楚你要什么，再开口。",
        asr_status="done",
    )
    db.add(MetricsSnapshot(video_id=v.id, snapshot_date="2026-09-05", plays=50000, likes=3000))
    db.commit()
    items = suggest_phrase_candidates(db, limit=5)
    assert items
    assert all("text" in it and len(it["text"]) >= 4 for it in items)
    # 确认流：phrase 类别可入档案
    db.add(PersonaTag(creator_id=owner.id, label=items[0]["text"], category="phrase", status="confirmed", source="manual"))
    db.commit()
    assert db.query(PersonaTag).filter(PersonaTag.category == "phrase").count() == 1
