"""R-136：复盘正式下线 + 文档一致性检查测试。"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def test_review_fully_sunset():
    import app.models as models
    from app.services import chat_service, prompt_contract, prompt_eval, prompt_service

    assert not hasattr(models, "ReviewReport")
    assert "review" not in prompt_service.PROMPT_META
    assert "review" not in prompt_service.RULE_KEYS
    assert "review" not in prompt_contract.CONTRACTS
    assert "review" not in prompt_contract.REQUIRED_MARKERS
    assert "review" not in prompt_eval.OUTPUT_FIELDS
    names = [t["function"]["name"] for t in chat_service.TOOLS]
    assert "get_review_report" not in names
    assert "get_radar" in names  # 赛道雷达能力保留


def test_sunset_review_table_stays_dropped():
    """R-136 复盘表已随 R-235 迁移下线（历史迁移全部删除）；若有人重新引入 review_reports 表则失败。"""
    from sqlalchemy import inspect

    from app.db import engine

    inspector = inspect(engine)
    assert "review_reports" not in set(inspector.get_table_names())


def test_metrics_radar_available():
    from app.db import SessionLocal
    from app.services.metrics import radar

    db = SessionLocal()
    try:
        assert isinstance(radar(db), list)
    finally:
        db.close()


def test_doc_consistency_script_passes():
    repo = Path(__file__).resolve().parents[2]
    proc = subprocess.run(
        [sys.executable, str(repo / "scripts" / "check_doc_consistency.py")],
        capture_output=True,
        text=True,
        cwd=repo,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "一致" in proc.stdout
