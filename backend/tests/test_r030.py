"""R-030 写稿体验增强测试：角度上下文/分节反馈/金句库（mock 离线）。"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest
from conftest import ensure_schema, fresh_engine
from sqlalchemy.orm import sessionmaker

from app.models.draft import Draft
from app.models.metrics import MetricsSnapshot
from app.models.persona import PersonaTag
from app.models.platform import Creator
from app.models.video import Transcript, Video
from app.services.feedback import add_feedback
from app.services.generation import benchmark_context_lines
from app.services.persona import suggest_phrase_candidates
from app.core.draft_check import check_script


@pytest.fixture()
def db(tmp_path):
    eng = fresh_engine()
    ensure_schema(eng)
    session = sessionmaker(bind=eng, autoflush=False, autocommit=False)()
    yield session
    session.close()


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


def test_draft_check_flags():
    good_text = (
        "为什么你总在面试翻车？先想清楚这三件事。第一，别背模板；第二，讲具体的事；"
        "第三，把每句话落到你能证明的结果上。很多人不是能力不行，是表达顺序错了。"
        "把逻辑理顺，把例子讲细，对方自然会记住你。还有一个小技巧，答完每个问题用一句总结收住，"
        "显得你条理清楚。别怕冷场，停顿一下再开口，往往更有分量。"
        "把上面这些用在自己下一场面试里，回来告诉我结果。想看更多面试干货，评论区聊聊你的问题。"
    )
    good = check_script(good_text, redlines=["不碰政zhi"])
    assert good["ok"] is True
    bad = check_script("大家好今天讲一下面试技巧然后就没有了", redlines=["借钱"])
    assert bad["ok"] is False
    assert any(("钩子" in i) or ("结尾" in i) or ("篇幅" in i) for i in bad["issues"])
    red = check_script("想赚钱就来找我借钱刷课", redlines=["借钱"])
    assert any("红线" in i for i in red["issues"])


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
