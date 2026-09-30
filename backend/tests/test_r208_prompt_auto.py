"""R-208：提示词优化后台全自动（到量自动跑 → 评分更好自动启用 / 不更好静默丢弃）。"""

from __future__ import annotations

import sys
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import Base
from app.models.notification import Notification
from app.services import prompt_eval as pe
from app.services import prompt_service as ps


@pytest.fixture()
def db(tmp_path):
    eng = create_engine(f"sqlite:///{tmp_path}/t.db", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=eng)
    session = sessionmaker(bind=eng, autoflush=False, autocommit=False)()
    yield session
    session.close()
    eng.dispose()


def _seed_versions(db):
    ps.ensure_defaults(db)
    base = ps.save_new_version(db, "generation", "当前启用版内容")
    cand = ps.create_candidate(db, "generation", "候选版内容")
    return base, cand


def _fake_eval(monkeypatch, **kw):
    row = types.SimpleNamespace(
        supported=kw.get("supported", True),
        reason=kw.get("reason", ""),
        base_score=kw.get("base_score", 70.0),
        candidate_score=kw.get("candidate_score", 90.0),
        base_version=kw.get("base_version", 1),
    )
    monkeypatch.setattr(pe, "evaluate", lambda db, key, version, update=None: row)


def test_auto_enable_when_clearly_better(db, monkeypatch):
    base, cand = _seed_versions(db)
    _fake_eval(monkeypatch, base_score=70.0, candidate_score=85.0, base_version=base.version)
    pe.prompt_eval_task(db, {"key": "generation", "version": cand.version})
    db.refresh(cand)
    db.refresh(base)
    assert cand.status == "enabled"
    assert base.status == "archived"
    row = db.query(Notification).filter(Notification.kind == "prompt_auto_enable").first()
    assert row is not None and "可回滚" in row.message


def test_silent_discard_when_not_better(db, monkeypatch):
    base, cand = _seed_versions(db)
    _fake_eval(monkeypatch, base_score=90.0, candidate_score=80.0, base_version=base.version)
    res = pe.prompt_eval_task(db, {"key": "generation", "version": cand.version})
    db.refresh(cand)
    assert cand.status == "rejected"
    assert "已丢弃" in res["message"]
    assert db.query(Notification).filter(Notification.kind.in_(["prompt_eval", "prompt_auto_enable"])).count() == 0


def test_keep_candidate_when_base_has_no_score(db, monkeypatch):
    base, cand = _seed_versions(db)
    _fake_eval(monkeypatch, base_score=0.0, candidate_score=80.0, base_version=base.version)
    pe.prompt_eval_task(db, {"key": "generation", "version": cand.version})
    db.refresh(cand)
    assert cand.status == "candidate"
    assert db.query(Notification).filter(Notification.kind == "prompt_eval").count() == 1
