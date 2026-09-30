"""R-208：每日「今日最佳」推送（AI 选 1 篇，通知推理由 + 口播稿全文）。"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.pipeline import today_key
from app.db import Base
from app.models.draft import Draft
from app.models.hot_topic import TopicCandidate
from app.models.notification import Notification
from app.services import pipeline as pl


@pytest.fixture()
def db(tmp_path):
    eng = create_engine(f"sqlite:///{tmp_path}/t.db", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=eng)
    session = sessionmaker(bind=eng, autoflush=False, autocommit=False)()
    yield session
    session.close()
    eng.dispose()


def _cand(db, title: str, score: int, script: str, slot: str = "hot") -> TopicCandidate:
    draft = Draft(title=title, script=script, status="draft", source="ai")
    db.add(draft)
    db.flush()
    c = TopicCandidate(run_date=today_key(), title=title, platform="douyin", score=score, slot=slot, reason="理由", draft_id=draft.id)
    db.add(c)
    db.flush()
    return c


def test_push_daily_best_picks_and_notifies(db, monkeypatch):
    _cand(db, "选题A", 90, "A 的口播稿正文")
    _cand(db, "选题B", 60, "B 的口播稿正文")
    db.commit()
    monkeypatch.setattr(pl, "_pick_daily_best_index", lambda db, items: 1)
    # R-221：显式用 spy 顶掉发信，断言「推了什么」；绝不再让夹具稿落到真实 SMTP 上
    sent: list[dict] = []
    monkeypatch.setattr(pl, "send_daily_best", lambda item, run_date, settings=None: sent.append(item) or True)
    res = pl.push_daily_best(db, today_key())
    assert res is not None and res["title"] == "选题B"
    assert len(sent) == 1 and sent[0]["title"] == "选题B"
    assert sent[0]["script"] == "B 的口播稿正文"
    assert sent[0]["reason"].startswith("【今日最佳 · 热榜】")
    assert sent[0]["cover_text"] == ""
    nt = db.query(Notification).filter(Notification.kind == "daily_best").first()
    assert nt is not None
    assert "B 的口播稿正文" in nt.message and "选题理由" in nt.message
    # 同一天不重复推送
    assert pl.push_daily_best(db, today_key()) is None
    assert db.query(Notification).filter(Notification.kind == "daily_best").count() == 1


def test_pick_index_falls_back_to_top_score(db):
    items = [
        {"title": "低", "slot": "hot", "score": 10, "reason": "x"},
        {"title": "高", "slot": "ai", "score": 88, "reason": "y"},
        {"title": "中", "slot": "comment", "score": 50, "reason": "z"},
    ]
    # 无密钥/异常 → 退回分数最高
    assert pl._pick_daily_best_index(db, items) == 1
