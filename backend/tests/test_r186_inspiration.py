"""R-186：灵感随手记 CRUD + 提炼选题（LLM 不可用时兜底）。"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest
from conftest import ensure_schema, fresh_engine
from sqlalchemy.orm import sessionmaker

from app.models.platform import Creator
from app.api.inspiration import NoteIn, create_note, delete_note, list_notes
from app.services.inspiration import refine_topic


@pytest.fixture()
def db(tmp_path):
    eng = fresh_engine()
    ensure_schema(eng)
    session = sessionmaker(bind=eng, autoflush=False, autocommit=False)()
    yield session
    session.close()


def test_note_crud(db):
    db.add(Creator(kind="owner", name="我", is_current=True))
    db.commit()
    note = create_note(NoteIn(text="试用期被裁，其实是入职前7天没做这件事"), db)
    assert note["id"] and note["status"] == "new"
    assert len(list_notes(db=db)) == 1
    delete_note(note["id"], db)
    assert list_notes(db=db) == []


def test_create_note_rejects_empty(db):
    from fastapi import HTTPException

    with pytest.raises(HTTPException):
        create_note(NoteIn(text="   "), db)


def test_refine_topic_falls_back_to_text(db):
    # 未配置模型时 refine_topic 不应抛错，直接返回原文
    out = refine_topic(db, "面试被问离职原因怎么说")
    assert out
    assert "离职原因" in out
