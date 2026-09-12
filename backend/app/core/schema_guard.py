"""库结构护栏（R-144 B/D）：启动自检「模型声明 vs 实际库」+ 迁移记账。

**为什么需要**：`create_all` 只建「缺失的表」，**不会给已存在的表补列**
（所以 `app/db.py` 里有 24 个手写 `_migrate_*`）。一旦「往模型里加了字段却忘了写迁移」，
线上老库会在第一次访问该列时报 `no such column`，而**启动时毫无提示**；
更麻烦的是 pytest 全部用全新库，漏写迁移在本地 100% 绿。

所以这里提供两件事：
1. `missing_schema(bind)`：把模型声明的表/列与实际库对一遍，返回缺失项（启动时跑，缺了就报警）；
2. 迁移记账：`record_migration` / `migration_status` —— 回答「这个库升到哪一版了」。

所有函数都接受**显式 `bind`**（engine），不依赖模块级全局，便于在测试里指向任意库。
"""

from __future__ import annotations

from typing import Any, Callable

from sqlalchemy import Engine, inspect

from ..core.log import get_logger
from ..db import Base

log = get_logger("schema_guard")

SCHEMA_CHECK_KV = "schema_check_result"

# 引入 R-144 之前的所有结构变更统称基线（这些迁移在 init_db 里每次都会幂等跑一遍）
BASELINE_MIGRATION = "baseline_pre_r144"


def ensure_migrations_table(bind: Engine) -> None:
    """确保 `schema_migrations` 存在（走模型定义，避免手写 DDL 与模型漂移）。"""
    from ..models.schema_migration import SchemaMigration

    Base.metadata.create_all(bind=bind, tables=[SchemaMigration.__table__])  # type: ignore[list-item]


def missing_schema(bind: Engine) -> dict:
    """对比模型声明与实际库，返回缺失的表与列。

    返回 `{"missing_tables": [...], "missing_columns": ["表.列", ...], "ok": bool}`
    """
    inspector = inspect(bind)
    existing_tables = set(inspector.get_table_names())
    missing_tables: list[str] = []
    missing_columns: list[str] = []
    for table in Base.metadata.sorted_tables:
        if table.name not in existing_tables:
            missing_tables.append(table.name)
            continue
        actual = {col["name"] for col in inspector.get_columns(table.name)}
        for column in table.columns:
            if column.name not in actual:
                missing_columns.append(f"{table.name}.{column.name}")
    return {
        "missing_tables": missing_tables,
        "missing_columns": missing_columns,
        "ok": not missing_tables and not missing_columns,
    }


# ---------- 迁移记账（D） ----------


def applied_migrations(bind: Engine) -> list[str]:
    from sqlalchemy.orm import Session

    from ..models.schema_migration import SchemaMigration

    ensure_migrations_table(bind)
    with Session(bind) as session:
        rows = session.query(SchemaMigration).order_by(SchemaMigration.id).all()
        return [row.name for row in rows]


def record_migration(bind: Engine, name: str, note: str = "") -> bool:
    """记一条迁移（幂等：同名已存在就跳过）。返回是否新写入。"""
    from sqlalchemy.orm import Session

    from ..models.schema_migration import SchemaMigration

    ensure_migrations_table(bind)
    with Session(bind) as session:
        exists = session.query(SchemaMigration).filter(SchemaMigration.name == name).first()
        if exists is not None:
            return False
        session.add(SchemaMigration(name=name, note=note[:255]))
        session.commit()
        return True


def ensure_baseline(bind: Engine) -> bool:
    """空记录时写入基线行：说明「R-144 之前的所有迁移均已应用过」（init_db 每次都幂等跑过）。"""
    if applied_migrations(bind):
        return False
    return record_migration(bind, BASELINE_MIGRATION, note="R-144 之前的结构变更基线")


def migration_status(bind: Engine) -> dict:
    """库结构版本视图：已应用迁移数 + 最新迁移名 + 是否有基线记录。"""
    names = applied_migrations(bind)
    return {
        "applied": len(names),
        "latest": names[-1] if names else "",
        "has_baseline": BASELINE_MIGRATION in names,
        "names": names,
    }


def run_startup_check(bind: Engine, session_factory: Callable[[], Any] | None = None) -> dict:
    """启动自检（B）：把「模型声明的表/列」和实际库对一遍，缺了就在日志与站内通知里说清楚。

    **绝不阻塞启动**：本函数内部任何异常都只记日志。
    返回 `{ok, missing_tables, missing_columns, migration, checked_at}`。
    """
    import time

    report: dict = {"ok": True, "missing_tables": [], "missing_columns": [], "checked_at": time.strftime("%Y-%m-%d %H:%M:%S")}
    try:
        report.update(missing_schema(bind))
        report["migration"] = migration_status(bind)
    except Exception as exc:  # noqa: BLE001 自检本身不能影响启动
        log.exception("结构自检执行失败：%s", exc)
        report["ok"] = False
        report["error"] = f"{type(exc).__name__}: {exc}"
        return report

    if report["ok"]:
        log.info(
            "结构自检通过：%d 张表；库结构版本=%s（已应用 %d 条迁移）",
            len(Base.metadata.tables),
            report["migration"].get("latest") or "（无记录）",
            report["migration"].get("applied", 0),
        )
        return report

    detail = []
    if report["missing_tables"]:
        detail.append("缺表：" + "、".join(report["missing_tables"]))
    if report["missing_columns"]:
        detail.append("缺列：" + "、".join(report["missing_columns"]))
    message = "；".join(detail)
    log.error(
        "结构自检发现问题：%s —— 多半是「加了模型字段但忘了在 app/db.py 写 _migrate_* 迁移」，"
        "请补迁移后重启（详见 docs/QUICKSTART.md 的增量上线说明）",
        message,
    )
    _persist_report(report, message, session_factory)
    return report


def _persist_report(report: dict, message: str, session_factory: Callable[[], Any] | None) -> None:
    """落 app_kv + 站内通知（都失败也不影响启动）。"""
    import json

    session = None
    try:
        if session_factory is None:
            from ..db import SessionLocal

            session_factory = SessionLocal
        session = session_factory()
        from ..models.kv import Kv

        payload = json.dumps(report, ensure_ascii=False)
        row = session.get(Kv, SCHEMA_CHECK_KV)
        if row is None:
            session.add(Kv(key=SCHEMA_CHECK_KV, value=payload))
        else:
            row.value = payload
        session.commit()
        from ..tasks import push_notification

        push_notification(
            session,
            kind="schema_check",
            status="failed",
            title="库结构自检发现问题（可能有迁移没写）",
            message=message[:200],
            target="/prompts",
        )
    except Exception:  # noqa: BLE001 通知/KV 失败不影响启动
        if session is not None:
            session.rollback()
        log.exception("结构自检结果落库/通知失败")
    finally:
        if session is not None:
            session.close()


__all__ = [
    "BASELINE_MIGRATION",
    "SCHEMA_CHECK_KV",
    "run_startup_check",
    "applied_migrations",
    "ensure_baseline",
    "ensure_migrations_table",
    "migration_status",
    "missing_schema",
    "record_migration",
]
