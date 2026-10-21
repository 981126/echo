"""R-183：生成提示词退回方向盘 + 创作模式注入。"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest
from conftest import ensure_schema, fresh_engine
from sqlalchemy.orm import sessionmaker

@pytest.fixture()
def db(tmp_path):
    eng = fresh_engine()
    ensure_schema(eng)
    session = sessionmaker(bind=eng, autoflush=False, autocommit=False)()
    yield session
    session.close()


def test_generation_prompt_is_steering_wheel(db):
    from app.services.prompt_service import default_content

    content = default_content("generation")
    # 不再写死具体句式/画像
    for banned in ("先破后立", "第一句必须", "全程断言", "抬杠"):
        assert banned not in content
    # 保留输出契约
    assert "输出契约" in content and '"script"' in content


def test_generation_user_message_injects_mode(db):
    from app.models.platform import Creator
    from app.services.generation import generation_user_message

    db.add(Creator(kind="owner", name="我", is_current=True))
    db.commit()
    text = generation_user_message(db, "如何谈薪", mode="sharp")
    assert "本次创作模式：犀利干货" in text
    # 不指定模式时不注入
    assert "本次创作模式" not in generation_user_message(db, "如何谈薪")
