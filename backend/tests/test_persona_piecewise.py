"""人设初始化逐篇喂 AI + 去重测试（R-126）。"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import Base
from app.models.persona import PersonaTag
from app.models.platform import Creator
from app.models.video import Transcript, Video
from app.services import ingest as ingest_mod


@pytest.fixture()
def db(tmp_path):
    eng = create_engine(f"sqlite:///{tmp_path}/t.db", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=eng)
    session = sessionmaker(bind=eng, autoflush=False, autocommit=False)()
    yield session
    session.close()
    eng.dispose()


def _video(db, owner, filename, text, is_ad=False):
    v = Video(creator_id=owner.id, filename=filename, title=filename, is_ad=is_ad)
    db.add(v)
    db.flush()
    db.add(Transcript(video_id=v.id, transcript_text=text, corrected_text=""))
    db.flush()
    return v


class _FakePersonaService:
    """按转写稿内容返回预设结果的假服务。"""
    def __init__(self):
        self.calls: list[str] = []

    def analyze_one(self, text: str) -> dict:
        self.calls.append(text)
        if "求职" in text:
            return {
                "tags": [{"label": "求职干货", "description": "应届求职"}, {"label": "面试技巧", "description": "套路拆解"}],
                "redlines": ["不骂人"],
            }
        if "面试" in text:
            return {
                "tags": [{"label": " 求职干货 ", "description": "简历向"}, {"label": "涨薪谈判"}],
                "redlines": ["不骂人", "不接软广"],
            }
        return {"tags": [], "redlines": []}


def test_persona_init_task_piecewise_dedupe(db, monkeypatch):
    owner = Creator(kind="owner", name="我", is_current=True)
    db.add(owner)
    db.commit()
    # 已确认「面试技巧」→ 应跳过再次建议；已拒绝「老标签」→ 允许再次出现（但本批不出现）
    db.add(PersonaTag(creator_id=owner.id, label="面试技巧", category="style", status="confirmed", version=1))
    db.add(PersonaTag(creator_id=owner.id, label="老标签", category="style", status="rejected", version=1))
    _video(db, owner, "a.mp4", "这篇讲求职干货")
    _video(db, owner, "b.mp4", "这篇讲面试技巧")
    _video(db, owner, "c.mp4", "广告视频", is_ad=True)
    db.commit()

    fake = _FakePersonaService()
    monkeypatch.setattr(ingest_mod, "PersonaService", lambda: fake)

    progress = []
    ingest_mod.persona_init_task(db, {"creator_id": owner.id}, update=lambda pct, note: progress.append((pct, note)))

    rows = db.query(PersonaTag).order_by(PersonaTag.id).all()
    new = [r for r in rows if r.version == 2]
    labels = {r.label for r in new}
    cats = {r.category for r in new}
    # 逐篇只调用了 2 篇（广告篇不参与）
    assert len(fake.calls) == 2
    # 求职干货跨两篇去重成 1 条；面试技巧因已确认被跳过；涨薪谈判保留
    assert labels == {"求职干货", "涨薪谈判", "不骂人", "不接软广"}
    assert "redline" in cats and "style" in cats
    # 描述保留第一篇（求职干货：应届求职）
    jd = next(r for r in new if r.label == "求职干货")
    assert jd.description == "应届求职"
    # 全部 suggested + 新版本
    assert all(r.status == "suggested" for r in new)
    assert all(r.version == 2 for r in new)
    # 进度回调走到 100
    assert progress and progress[-1][0] == 100


def test_persona_init_task_no_transcripts_noop(db):
    owner = Creator(kind="owner", name="我", is_current=True)
    db.add(owner)
    db.commit()
    ingest_mod.persona_init_task(db, {"creator_id": owner.id})
    assert db.query(PersonaTag).count() == 0
