"""R-230：删除稿计入负反馈 + 论点漂移标注。

① 作者处理不满意稿的习惯是删除，原反馈回流只把 status='archived' 当负例——
负例库实际为空；本需求把 deleted 的 AI 稿一并计入（纯手写稿仍排除，R-210）。
② quality.outlines/sources 取的是初稿口径，N 轮讨论后正文可能整体漂移
（draft 128：初稿谈自由职业、终稿谈求职）——detect_outline_drift 纯文本检测
（claim 关键词命中终稿），outline_drift 落 quality，前端依据卡片提示「以正文为准」。
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest
from conftest import ensure_schema, fresh_engine
from sqlalchemy.orm import sessionmaker

from app.models.draft import Draft
from app.services.debate import detect_outline_drift
from app.services.prompt_service import feedback_context


@pytest.fixture()
def db(tmp_path):
    eng = fresh_engine()
    ensure_schema(eng)
    session = sessionmaker(bind=eng, autoflush=False, autocommit=False)()
    yield session
    session.close()


# ---------- 负反馈口径：deleted 的 AI 稿计入 ----------


def _draft(db, status: str, script: str, source: str = "ai") -> Draft:
    d = Draft(title=f"稿{status}{source}", script=script, status=status, source=source)
    db.add(d)
    db.commit()
    return d


def test_feedback_negatives_include_deleted_ai_drafts(db):
    _draft(db, "deleted", "被删掉的 AI 稿正文")
    ctx = feedback_context(db)
    assert "被删掉的 AI 稿正文" in ctx
    assert "避免这种腔调" in ctx  # 负例区标题仍在


def test_feedback_negatives_include_archived_too(db):
    _draft(db, "archived", "被归档的 AI 稿正文")
    ctx = feedback_context(db)
    assert "被归档的 AI 稿正文" in ctx


def test_feedback_negatives_exclude_deleted_manual_drafts(db):
    """R-210 口径：手写稿被放弃只是作者不想做，不代表写得差，不进负向。"""
    _draft(db, "deleted", "被删掉的手写稿正文", source="manual")
    ctx = feedback_context(db)
    assert "被删掉的手写稿正文" not in ctx


def test_feedback_positives_unchanged(db):
    _draft(db, "done", "作者完成的稿子正文")
    ctx = feedback_context(db)
    assert "作者完成的稿子正文" in ctx
    assert "保持这种腔调" in ctx


# ---------- 论点漂移检测 ----------


def test_drift_false_when_claims_preserved():
    outlines = [
        {"claim": "别跟公司养老，不爽就跳", "support": ""},
        {"claim": "简历该吹就吹，背调不过就换", "support": ""},
    ]
    script = "第一条，别跟公司养老。第二条，简历该吹就吹，背调不过就换下一家。"
    assert detect_outline_drift(outlines, script) is False


def test_drift_true_when_claim_vanished():
    """draft 128 形态：初稿论点在终稿里完全消失。"""
    outlines = [{"claim": "不上班还有收入的人是把技能变成可反复卖的东西", "support": ""}]
    script = "别跟公司养老。简历必须包装。求职就是运气活。投就完了。"
    assert detect_outline_drift(outlines, script) is True


def test_drift_partial_claim_gone_marks_drift():
    outlines = [
        {"claim": "别跟公司养老", "support": ""},
        {"claim": "自由职业是把技能产品化", "support": ""},
    ]
    script = "别跟公司养老，跳了才过万。"
    assert detect_outline_drift(outlines, script) is True


def test_drift_empty_inputs():
    assert detect_outline_drift([], "任何正文") is False
    assert detect_outline_drift([{"claim": "论点", "support": ""}], "") is False
    assert detect_outline_drift(None, "正文") is False
