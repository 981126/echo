"""R-103 对标广告过滤测试：candidates 排除广告/同款 + 转写补齐时自动判广并顺延（mock 离线）。"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import Base
from app.models.platform import Creator, CreatorAccount, PlatformPost
from app.services.benchmark import candidates, ensure_top3_with_text


@pytest.fixture()
def db(tmp_path):
    eng = create_engine(f"sqlite:///{tmp_path}/t.db", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=eng)
    session = sessionmaker(bind=eng, autoflush=False, autocommit=False)()
    yield session
    session.close()
    eng.dispose()


def _seed(db, posts):
    owner = Creator(kind="owner", name="我", is_current=True)
    db.add(owner)
    db.commit()
    bm = Creator(kind="benchmark", parent_id=owner.id, name="对标A")
    db.add(bm)
    db.commit()
    acc = CreatorAccount(creator_id=bm.id, platform="douyin", nickname="对标号", enabled=True)
    db.add(acc)
    db.commit()
    base = datetime(2026, 9, 1, 12, 0, 0)
    for i, (pid, title, is_ad) in enumerate(posts):
        db.add(
            PlatformPost(
                account_id=acc.id,
                platform="douyin",
                platform_post_id=pid,
                title=title,
                publish_time=base - timedelta(hours=i),
                is_ad=is_ad,
            )
        )
    db.commit()
    return bm


def test_candidates_exclude_ad_and_same_title_twin(db):
    bm = _seed(
        db,
        [
            ("n1", "职场干货：如何谈薪", False),
            ("adv", "某品牌手机体验评测", True),
            ("twin", "某品牌手机体验评测", False),  # 同款跨平台漏标，按标题一并排除（R-100）
            ("n2", "简历这样写更稳", False),
        ],
    )
    got = candidates(db, bm, limit=10)
    titles = [u["post"].platform_post_id for u in got]
    assert "adv" not in titles and "twin" not in titles
    assert "n1" in titles and "n2" in titles


def test_ensure_top3_skips_ad_and_flags(db, monkeypatch):
    bm = _seed(
        db,
        [
            ("adv1", "广告帖一", False),
            ("n1", "正常帖一", False),
            ("adv2", "广告帖二", False),
            ("n2", "正常帖二", False),
            ("n3", "正常帖三", False),
        ],
    )
    monkeypatch.setattr("app.services.benchmark._unit_text", lambda db, unit: "有转写文案内容")
    monkeypatch.setattr(
        "app.services.benchmark._unit_is_ad",
        lambda db, unit, text="": unit["post"].platform_post_id in ("adv1", "adv2"),
    )
    picked = ensure_top3_with_text(db, bm, limit_candidates=10)
    picked_ids = [u["post"].platform_post_id for u in picked]
    assert len(picked) == 3
    assert "adv1" not in picked_ids and "adv2" not in picked_ids
    # 广告帖被落库标记，之后 candidates 直接排除
    flags = {r.platform_post_id: r.is_ad for r in db.query(PlatformPost).all()}
    assert flags["adv1"] is True and flags["adv2"] is True
    assert flags["n1"] is False
