"""R-221：测试环境绝不允许真发邮件（R-208 推送用例曾把夹具稿当「今日最佳」发给作者）。"""

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
from app.services import notify as notify_mod
from app.services import pipeline as pl
from conftest import RealMailAttempted


@pytest.fixture()
def db(tmp_path):
    eng = create_engine(f"sqlite:///{tmp_path}/t.db", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=eng)
    session = sessionmaker(bind=eng, autoflush=False, autocommit=False)()
    yield session
    session.close()
    eng.dispose()


def test_test_env_mail_config_is_blanked():
    """conftest 清空了 SMTP 配置 → 校验层必然拦下，默认配置下任何用例都发不出邮件。"""
    assert notify_mod.mail_config_problem() != ""
    assert notify_mod._send("主题", "<p>正文</p>") is False


def test_tripwire_blocks_smtp_even_with_valid_config():
    """有人把配置补回来也连不出去：兜底闸门抛 RealMailAttempted（BaseException，_send 吞不掉）。"""
    from unittest.mock import MagicMock

    good = MagicMock(
        smtp_user="me@qq.com",
        smtp_auth_code="abcdefghijklmnop",
        mail_to="you@qq.com",
        smtp_host="smtp.qq.com",
        smtp_port=465,
    )
    with pytest.raises(RealMailAttempted):
        notify_mod._send("中文主题", "<p>正文</p>", good)


def test_push_daily_best_sends_no_mail_in_tests(db, monkeypatch):
    """回归：R-208 那组夹具（选题B / B 的口播稿正文）在测试环境只能写站内通知，邮件通道是空操作。"""
    draft = Draft(title="选题B", script="B 的口播稿正文", status="draft", source="ai")
    db.add(draft)
    db.flush()
    db.add(
        TopicCandidate(
            run_date=today_key(),
            title="选题B",
            platform="douyin",
            score=60,
            slot="hot",
            reason="理由",
            draft_id=draft.id,
        )
    )
    db.commit()

    real_send = pl.send_daily_best
    sent: list[dict] = []
    monkeypatch.setattr(pl, "send_daily_best", lambda item, run_date, settings=None: sent.append(item) or real_send(item, run_date, settings))

    res = pl.push_daily_best(db, today_key())
    assert res is not None and res["title"] == "选题B"
    assert len(sent) == 1, "推送通道应被调用一次（但测试环境不允许真的发出去）"
    # 通知照写（作者在站内仍能看到今日最佳）
    nt = db.query(Notification).filter(Notification.kind == "daily_best").first()
    assert nt is not None and "B 的口播稿正文" in nt.message
