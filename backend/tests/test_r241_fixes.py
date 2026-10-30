"""R-241 复核修复回归：persona 增量补跑去重误杀、预算超卖 savepoint、模型/迁移元数据一致性。"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from conftest import ensure_schema, fresh_engine  # noqa: E402
from sqlalchemy import inspect, text  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

from app.models.kv import Kv  # noqa: E402
from app.models.platform import PlatformPostStat  # noqa: E402
from app.models.task import BackgroundTask  # noqa: E402
from app.models.video import Video  # noqa: E402


def _session_factory():
    eng = fresh_engine()
    ensure_schema(eng)
    return eng, sessionmaker(bind=eng, autoflush=False, autocommit=False)


# ---------- P1：persona 增量补跑不能被去重吞掉 ----------


def test_persona_incremental_rerun_not_deduped(monkeypatch) -> None:
    """增量任务 running 时又导入新素材 → 补跑必须新建任务（旧的自动去重会吞掉并清 pending 标记）。"""
    from app.models.platform import Creator
    from app.services import ingest

    _eng, S = _session_factory()
    s = S()
    try:
        creator = Creator(kind="owner", name="我", is_current=True)
        s.add(creator)
        s.commit()
        # 模拟「重启恢复的 persona_incremental 正在跑 + 期间又导入素材」
        running = BackgroundTask(
            kind="persona_incremental",
            status="running",
            payload=json.dumps({"creator_id": creator.id, "video_id": 0}, ensure_ascii=False),
        )
        s.add(running)
        s.add(Kv(key="persona_incremental_pending", value="1"))
        s.commit()
        running_id = running.id
        monkeypatch.setattr(ingest, "persona_incremental_task", lambda db, payload: None)

        ingest._rerun_if_pending(s, creator.id)

        tasks = s.query(BackgroundTask).filter(BackgroundTask.kind == "persona_incremental").all()
        assert len(tasks) >= 2, f"补跑任务被去重吞掉：只剩 {len(tasks)} 条"
        assert any(t.id != running_id for t in tasks)
        pending = s.get(Kv, "persona_incremental_pending")
        assert pending is not None and pending.value == "0"  # 入队成功后才清标记
    finally:
        s.close()


# ---------- 预算超卖兜底：只回滚本次增量，不误伤同 Session 业务写 ----------


def test_budget_oversell_savepoint_keeps_other_session_writes(monkeypatch) -> None:
    from app.services.platform import budget as budget_mod
    from app.services.platform.budget import BudgetExceeded, _charge, get_budget

    _eng, S = _session_factory()
    s = S()
    try:
        from app.core.pipeline import today_key

        s.add(Kv(key="tikhub_budget_limit", value="1"))
        s.add(Kv(key=f"tikhub_budget_used:{today_key()}", value="1"))  # 已用满
        s.commit()
        # 模拟「预检读到旧值」：跳过 ensure_budget，让 _charge 进入原子更新/超卖兜底分支
        monkeypatch.setattr(budget_mod, "ensure_budget", lambda db, count=1: None)
        s.add(Kv(key="r241_sentinel", value="待提交的业务写"))
        assert get_budget(s)["used"] == 1

        try:
            _charge(s, 1)
        except BudgetExceeded:
            pass
        else:  # pragma: no cover
            raise AssertionError("额度已满时 _charge 必须抛 BudgetExceeded")

        # 超卖兜底只回滚 savepoint：同 Session 的其它未提交写应仍可提交，计费不变
        s.commit()
        s2 = S()
        try:
            assert s2.get(Kv, "r241_sentinel") is not None, "超卖回滚误伤了同 Session 未提交业务写"
            assert get_budget(s2)["used"] == 1, "超卖兜底后计费数不应变化"
        finally:
            s2.close()
    finally:
        s.close()


# ---------- 迁移/模型元数据一致性 ----------


def test_updated_at_db_default_is_beijing_time() -> None:
    eng, _S = _session_factory()
    try:
        with eng.connect() as conn:
            for table in ("videos", "platform_post_stats"):
                default = conn.execute(
                    text(
                        "SELECT column_default FROM information_schema.columns "
                        "WHERE table_name = :t AND column_name = 'updated_at'"
                    ),
                    {"t": table},
                ).scalar()
                assert default is not None, f"{table}.updated_at 缺少库默认值"
                assert "Asia/Shanghai" in default, f"{table}.updated_at 库默认不是北京时间：{default}"
    finally:
        eng.dispose()


def test_models_declare_migration_metadata() -> None:
    """模型元数据与迁移一致（避免 alembic autogenerate 假差异）。"""
    index_names = {idx.name for idx in BackgroundTask.__table__.indexes}
    assert "ix_background_tasks_status_created" in index_names
    assert Video.__table__.c.updated_at.server_default is not None
    assert PlatformPostStat.__table__.c.updated_at.server_default is not None
    # 索引确实在库里（migration 已应用）
    _eng, _S = _session_factory()
    try:
        names = {idx["name"] for idx in inspect(_eng).get_indexes("background_tasks")}
        assert "ix_background_tasks_status_created" in names
    finally:
        _eng.dispose()
