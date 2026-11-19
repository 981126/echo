"""R-254：洗稿/生成文案放开参考素材经历归属。

作者确认放开：对标/站内/联网素材里的经历、案例、数字可以写成作者本人第一人称，
允许基于素材补全、扩写细节；保留「整篇不逐字照抄（可偶尔沿用素材 1-2 句原句）」、
联网引用编号/来源留痕、人设红线检查。本文件回归：
1. 洗稿/生成/原文改写三条提示词不再含旧限制；
2. 站内对标参考块标签中性化；
3. DB 已启用 generation 提示词的一次性补丁（旧句替换 + 另存启用 + Kv 标记幂等）。
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest
from conftest import ensure_schema, fresh_engine
from sqlalchemy.orm import sessionmaker

from app.models.prompt import AiPrompt
from app.services.benchmark import REWRITE_SYSTEM
from app.services.rewrite_debate import ALLOW_EXPANSION_RULE, SOURCE_REWRITE_SYSTEM
from app.services.station_evidence import build_block


@pytest.fixture()
def db(tmp_path):
    eng = fresh_engine()
    ensure_schema(eng)
    session = sessionmaker(bind=eng, autoflush=False, autocommit=False)()
    yield session
    session.close()




def test_rewrite_prompt_allows_reference_as_own() -> None:
    """洗稿提示词：允许素材经历写成作者本人，同时保留「不逐字照抄 + 偶尔 1-2 句原句」。"""
    assert "禁止写成你自己的经历" not in REWRITE_SYSTEM
    assert "严禁编造" not in REWRITE_SYSTEM
    assert "【需作者补充】" not in REWRITE_SYSTEM
    assert "也可以把其中的经历、案例、观点写成作者本人的" in REWRITE_SYSTEM
    assert "允许基于素材补全、扩写细节" in REWRITE_SYSTEM
    assert "整篇不逐字照抄" in REWRITE_SYSTEM
    assert "可以偶尔直接沿用素材的 1-2 句原句" in REWRITE_SYSTEM


def test_source_rewrite_prompt_allows_reference_as_own() -> None:
    """草稿「讨论」基于原文的初稿提示词同步放开。"""
    assert "严禁编造" not in SOURCE_REWRITE_SYSTEM
    assert "需作者补充" not in SOURCE_REWRITE_SYSTEM
    assert "可以把素材里的经历、案例、观点写成作者本人的" in SOURCE_REWRITE_SYSTEM
    assert "1-2 句原句" in SOURCE_REWRITE_SYSTEM


def test_allow_expansion_rule() -> None:
    """评审/修订共用规则：允许扩写，不再要求「这里需要作者补充真实经历」。"""
    assert "允许" in ALLOW_EXPANSION_RULE
    assert "补全" in ALLOW_EXPANSION_RULE
    assert "扩写" in ALLOW_EXPANSION_RULE
    assert "严禁" not in ALLOW_EXPANSION_RULE
    assert "不要再要求" in ALLOW_EXPANSION_RULE


def test_station_block_benchmark_label() -> None:
    """站内对标参考块改成中性标签，不再标注「他人/禁止写成你的经历」。"""
    block = build_block(
        [],
        [{"kind": "benchmark", "title": "对标标题", "text": "某段经历", "blogger": "某博主", "score": 3}],
    )
    assert "对标博主内容（可参考，可写成作者本人的经历/观点）" in block
    assert "禁止写成" not in block
    assert "非本人" not in block


def _seed_generation(db, content: str, version: int = 1, status: str = "enabled") -> None:
    db.add(AiPrompt(key="generation", version=version, content=content, status=status, note="seed"))
    db.commit()


def _enabled_generation(db) -> AiPrompt:
    return (
        db.query(AiPrompt)
        .filter(AiPrompt.key == "generation", AiPrompt.status == "enabled")
        .order_by(AiPrompt.version.desc())
        .first()
    )


def _old_generation_content() -> str:
    return (
        "3) 优先用【站内真实素材·你的】里的真实经历/说法；"
        "【对标】素材只能当参考，**禁止写成你自己的经历**；\n"
        "4) 严禁编造具体数字/人名/机构/经历；没有可靠事实就只讲作者的判断，宁可不要数字；\n"
        "论据缺素材处标【需作者补充】，不要编一个填上；\n"
        "观点必须用作者自己的。"
    )
