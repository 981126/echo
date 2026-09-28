"""R-190/R-191：评论聚类过滤与相似度 + 已讲话题接口。"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import Base
from app.models.draft import Draft
from app.models.platform import Creator
from app.services import opportunity


@pytest.fixture()
def db(tmp_path):
    eng = create_engine(f"sqlite:///{tmp_path}/t.db", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=eng)
    session = sessionmaker(bind=eng, autoflush=False, autocommit=False)()
    yield session
    session.close()
    eng.dispose()


def test_low_value_filters_praise_but_keeps_questions():
    assert opportunity._low_value("这期含金量很高，支持！") is True
    assert opportunity._low_value("666") is True
    assert opportunity._low_value("试用期被裁怎么办？") is False
    assert opportunity._low_value("怎么谈薪资") is False


def test_sim_bigram_groups_paraphrase():
    a = opportunity._norm("试用期被裁怎么办")
    b = opportunity._norm("试用期被裁员了咋办")
    assert opportunity._sim(a, b) >= 0.5


def test_covered_returns_titles(db):
    owner = Creator(kind="owner", name="我", is_current=True)
    db.add(owner)
    db.commit()
    db.add(Draft(creator_id=owner.id, title="谈薪技巧", status="done"))
    db.add(Draft(creator_id=owner.id, title="草稿不该算", status="draft"))
    db.commit()
    res = opportunity.covered(db)
    assert "谈薪技巧" in res["titles"]
    assert "草稿不该算" not in res["titles"]
