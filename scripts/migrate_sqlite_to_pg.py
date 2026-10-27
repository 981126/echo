#!/usr/bin/env python3
"""SQLite → PostgreSQL 数据迁移（R-235 收尾）。

把旧 SQLite 单文件库（默认 ECHO_DATA_DIR/echo.db）的**数据**灌进 PG 目标库
（默认取仓库根 .env 的 ECHO_DATABASE_URL）。结构不按 sqlite 搬 —— 由 Alembic
按版本化 migration 建全新结构（列类型/约束以 migration 为准），只搬数据：

- 逐表 INSERT（外键按 sqlite 的 foreign_key_list 做拓扑排序，父表先行）；
- 目标列是 BOOLEAN 的，把 sqlite 的 0/1 转成 False/True；
- 时间列原样搬（两边都是「北京时间 naive 字符串/时间戳」，不换算）；
- JSON 文本列原样搬；
- 导完把每张自增主键的序列对齐到 max(id)；
- 只迁移代码模型里存在的表；sqlite 多出来的表（如旧迁移记账）跳过并提示。

用法（仓库根目录，用 backend/.venv 跑）：
    backend/.venv/bin/python scripts/migrate_sqlite_to_pg.py
    SQLITE_PATH=/path/echo.db TARGET_URL="postgresql+psycopg://…/echo_dev" backend/.venv/bin/python scripts/migrate_sqlite_to_pg.py
"""

from __future__ import annotations

import os
import sqlite3
import sys
from pathlib import Path

import psycopg
from sqlalchemy import inspect
from sqlalchemy.sql.sqltypes import Boolean, Integer

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.db import Base, engine  # noqa: E402
from app.migrations import run_migrations  # noqa: E402
import app.models  # noqa: E402,F401


def _sqlite_path() -> Path:
    raw = os.environ.get("SQLITE_PATH", "").strip()
    if raw:
        return Path(raw)
    data_dir = os.environ.get("ECHO_DATA_DIR", "").strip()
    if not data_dir:
        env_file = ROOT / ".env"
        if env_file.exists():
            for line in env_file.read_text(encoding="utf-8").splitlines():
                if line.startswith("ECHO_DATA_DIR="):
                    data_dir = line.split("=", 1)[1].strip().strip('"').strip("'")
                    break
    base = Path(data_dir) if data_dir else ROOT / "data"
    return base / "echo.db"


def _target_dsn() -> str:
    url = os.environ.get("TARGET_URL", "").strip()
    if url:
        return url.replace("+psycopg", "", 1)
    env_file = ROOT / ".env"
    for line in env_file.read_text(encoding="utf-8").splitlines():
        if line.startswith("ECHO_DATABASE_URL="):
            return line.split("=", 1)[1].strip().strip('"').strip("'").replace("+psycopg", "", 1)
    raise SystemExit("缺少 TARGET_URL 或 .env 的 ECHO_DATABASE_URL")


def _table_order(sqlite_conn: sqlite3.Connection) -> list[str]:
    """按外键依赖拓扑排序（父表先）；循环依赖时按原顺序收尾。"""
    tables = [r[0] for r in sqlite_conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
    deps: dict[str, set[str]] = {}
    for t in tables:
        refs = {r[2] for r in sqlite_conn.execute(f"PRAGMA foreign_key_list({t})") if r[2]}
        deps[t] = refs & set(tables)
    ordered: list[str] = []
    remaining = set(tables)
    while remaining:
        ready = sorted(t for t in remaining if not (deps[t] & remaining))
        if not ready:  # 循环依赖：任意取一个打破环
            ready = [sorted(remaining)[0]]
        ordered.extend(ready)
        remaining -= set(ready)
    return ordered


def main() -> int:
    src = _sqlite_path()
    if not src.is_file():
        raise SystemExit(f"SQLite 源库不存在：{src}")
    dsn = _target_dsn()
    print(f"源：{src}")
    print(f"目标：{dsn.split('@')[-1]}（密码略）")

    # 1) 目标库按版本化 migration 重建全新结构
    with psycopg.connect(dsn, autocommit=True) as c:
        c.execute("DROP SCHEMA public CASCADE")
        c.execute("CREATE SCHEMA public")
        c.execute('GRANT ALL ON SCHEMA public TO "Yeah"')
    run_migrations(os.environ.get("TARGET_URL") or None)
    print("目标结构已按 Alembic migration 重建")

    # 2) 逐表搬数据
    src_conn = sqlite3.connect(f"file:{src}?mode=ro", uri=True)
    inspector = inspect(engine)
    bool_cols: dict[str, set[str]] = {
        t: {c["name"] for c in inspector.get_columns(t) if isinstance(c["type"], Boolean)}
        for t in Base.metadata.tables
    }
    order = _table_order(src_conn)
    skipped = [t for t in order if t not in Base.metadata.tables]

    problems: list[str] = []
    with psycopg.connect(dsn) as dst:
        with dst.cursor() as cur:
            cur.execute("SET session_replication_role = 'replica'")  # 导入期关掉 FK 检查，序列对齐后由应用保证
        for table in order:
            if table not in Base.metadata.tables:
                continue
            cols_info = inspector.get_columns(table)
            cols = [c["name"] for c in cols_info]
            qcols = [f'"{c}"' for c in cols]  # PG 保留字列名（如 desc）必须加引号
            bcols = bool_cols.get(table, set())
            rows = src_conn.execute(f"SELECT {', '.join(qcols)} FROM {table}").fetchall()
            if rows:
                adapted = [
                    tuple((bool(v) if v is not None else None) if c in bcols else v for c, v in zip(cols, row))
                    for row in rows
                ]
                placeholders = ", ".join(["%s"] * len(cols))
                with dst.cursor() as cur:
                    cur.executemany(
                        f"INSERT INTO {table} ({', '.join(qcols)}) VALUES ({placeholders})",
                        adapted,
                    )
                # 序列对齐到 max(id)（get_columns 不含主键信息，要用 get_pk_constraint；
                # 仅对自增整型主键（如 app_kv 的字符串主键没有序列））
                pk_cols = inspector.get_pk_constraint(table).get("constrained_columns") or []
                pk = pk_cols[0] if len(pk_cols) == 1 else None
                if pk and isinstance(next(c for c in cols_info if c["name"] == pk)["type"], Integer):
                    with dst.cursor() as cur:
                        seq = cur.execute("SELECT pg_get_serial_sequence(%s, %s)", (table, pk)).fetchone()[0]
                        if seq:
                            mx = cur.execute(f"SELECT max({pk}) FROM {table}").fetchone()[0]
                            cur.execute(
                                "SELECT setval(%s, COALESCE(%s, 1), %s)",
                                (seq, mx, mx is not None),
                            )
            dst.commit()
            print(f"  {table}: {len(rows)} 行")

    # 3) 汇总核对
    print("\n核对（sqlite vs pg）：")
    ok = True
    with psycopg.connect(dsn) as dst:
        for table in order:
            if table not in Base.metadata.tables:
                continue
            a = src_conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
            b = dst.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
            flag = "OK " if a == b else "!! "
            ok = ok and a == b
            print(f"  {flag}{table}: {a} -> {b}")
    src_conn.close()
    if skipped:
        print("\n跳过的 sqlite 表（代码模型中已不存在）：", "、".join(skipped))
    if not ok:
        raise SystemExit("行数核对不一致，见上方 !! 行")
    print("\n迁移完成，行数全部一致 ✔")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
