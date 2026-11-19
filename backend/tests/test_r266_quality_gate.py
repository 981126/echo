"""R-266：质量门禁（吸引力降权/开头必过）与「只改开头」重写。"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest
from conftest import ensure_schema, fresh_engine
from sqlalchemy.orm import sessionmaker

from app.models.author_generation import GenerationRun
from app.models.platform import Creator
from app.services import generation_pipeline as pipeline
from app.services.generation_validators import compute_quality_passed

REQUIRED = ("assets", "angles", "blueprint", "writing", "review")


@pytest.fixture()
def db(tmp_path):
    eng = fresh_engine()
    ensure_schema(eng)
    session = sessionmaker(bind=eng, autoflush=False, autocommit=False)()
    yield session
    session.close()


def _run(*, opening: bool | None = True, attraction: float = 3, author: float = 4, logic: bool = True) -> GenerationRun:
    run = GenerationRun(creator_id=1, topic="主题", status="succeeded", quality_passed=True)
    run.final_script_hash = "hash-1"
    stages = {name: {"status": "completed"} for name in REQUIRED}
    if opening is not None:
        stages["opening_check"] = {"status": "completed", "passed": opening}
    run.attempts_json = json.dumps(
        {"stages": stages, "write_count": 1, "review_count": 1, "revision_count": 0}
    )
    run.reviews_json = json.dumps(
        [
            {
                "executed": True,
                "script_hash": "hash-1",
                "logic_passed": logic,
                "hard_issues": [],
                "attraction_score": attraction,
                "author_score": author,
            }
        ]
    )
    return run


def test_attraction_is_diagnostic_only():
    assert compute_quality_passed(_run(opening=True, attraction=3)) is True
    assert compute_quality_passed(_run(opening=True, attraction=1)) is True


def test_opening_check_is_required():
    assert compute_quality_passed(_run(opening=False)) is False
    assert compute_quality_passed(_run(opening=None)) is False


def test_logic_still_blocks():
    assert compute_quality_passed(_run(opening=True, logic=False)) is False


def _owner(db) -> int:
    creator = Creator(kind="owner", name="我", is_current=True)
    db.add(creator)
    db.commit()
    return creator.id


def test_ensure_opening_rewrites_only_head(db, monkeypatch):
    run = GenerationRun(creator_id=_owner(db), topic="主题", status="running")
    db.add(run)
    db.commit()
    old = (
        "大家好，我是小明，今天想聊面试这件事里面很多值得说的细节问题。"
        "正文第二句。"
        "正文第三句很长很长很长。"
    )
    new = "被拒三次后我才明白。先看目标。" + "正文第三句很长很长很长。"
    monkeypatch.setattr(pipeline, "_call_json", lambda *args, **kwargs: {"script": new})
    data = {"script": old, "title": "旧标题", "claims": []}
    merged, stage = pipeline._ensure_opening(db, run, data, {"hook": {"payoff": ""}}, object(), "ctx")
    assert merged["script"] == new
    assert stage["rewritten"] is True
    assert stage["passed"] is True


def test_ensure_opening_rejects_body_rewrite(db, monkeypatch):
    run = GenerationRun(creator_id=_owner(db), topic="主题", status="running")
    db.add(run)
    db.commit()
    old = (
        "大家好，我是小明，今天想聊面试这件事里面很多值得说的细节问题。"
        "正文第二句。"
        "正文第三句很长很长很长。"
    )
    monkeypatch.setattr(pipeline, "_call_json", lambda *args, **kwargs: {"script": "完全换掉的一段话。又一段。再一段。"})
    data = {"script": old, "title": "旧标题", "claims": []}
    merged, stage = pipeline._ensure_opening(db, run, data, {"hook": {"payoff": ""}}, object(), "ctx")
    assert merged["script"] == old
    assert stage["rewritten"] is False
    assert stage["rewrite_rejected"] == "正文被改动"
