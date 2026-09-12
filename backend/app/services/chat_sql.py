"""`sql_query` 工具（R-147 P1）：让 AI 对话能安全地自己查数据。

**安全边界（四层，缺一不可）**
1. **只读连接**：`file:…?mode=ro` + `PRAGMA query_only=1` —— 物理上写不了；
2. **只允许单条 SELECT/WITH**：拒绝 `;` 多语句与全部写/管理关键字（ATTACH/PRAGMA/DROP…）；
3. **表引用白名单**：正则抽出 `FROM`/`JOIN` 后的标识符，**必须全部是 `analytics_views` 里的视图**
   —— 所以 `app_kv`（含明文模型 Key）、`ai_prompts` 等原始表根本查不到；
4. **资源上限**：自动补 `LIMIT`（≤200）、单元格截断、语句超时（progress handler 中断）。

返回 `{columns, rows, row_count, truncated, sql}`（延续 R-146：必须让模型知道"是不是被截断"）。
"""

from __future__ import annotations

import re
import sqlite3
import time
from pathlib import Path

from ..core import analytics_views
from ..core.log import get_logger

log = get_logger("chat_sql")

MAX_ROWS = 200
MAX_CELL_CHARS = 200
MAX_SQL_CHARS = 2000
TIMEOUT_SECONDS = 5.0

# 单条只读语句：以 SELECT / WITH 开头
_SELECT_RE = re.compile(r"^\s*(select|with)\b", re.IGNORECASE)
# 明确拒绝的关键字（写/管理/多语句）
_FORBIDDEN_RE = re.compile(
    r"\b(insert|update|delete|drop|alter|create|replace|truncate|attach|detach|pragma|vacuum|"
    r"reindex|begin|commit|rollback|savepoint|release|analyze|grant|revoke|into\s+outfile)\b",
    re.IGNORECASE,
)
# 表引用：FROM / JOIN 后面跟的标识符（含 schema 前缀的写法一并抓）
_TABLE_REF_RE = re.compile(r"\b(?:from|join)\s+([A-Za-z_][A-Za-z0-9_$.]*)", re.IGNORECASE)
# 注释会干扰关键字/表名识别，直接拒（正常提问不需要 SQL 注释）
_COMMENT_RE = re.compile(r"(--[^\n]*)|(/\*)")


class SqlGuardError(ValueError):
    """SQL 被安全规则拒绝：API/工具层转成可读提示。"""


def validate(sql: str) -> str:
    """校验并返回规范化后的 SQL（只做检查，不执行）。"""
    text = (sql or "").strip()
    if not text:
        raise SqlGuardError("SQL 不能为空")
    if len(text) > MAX_SQL_CHARS:
        raise SqlGuardError(f"SQL 过长（>{MAX_SQL_CHARS} 字符）")
    if _COMMENT_RE.search(text):
        raise SqlGuardError("SQL 里不要写注释")
    if ";" in text.rstrip().rstrip(";"):
        raise SqlGuardError("一次只能执行一条 SELECT（不要用分号拼多条语句）")
    text = text.rstrip().rstrip(";")
    if not _SELECT_RE.match(text):
        raise SqlGuardError("只允许 SELECT 查询（可以是 WITH … SELECT）")
    banned = _FORBIDDEN_RE.search(text)
    if banned:
        raise SqlGuardError(f"不允许使用 {banned.group(0).upper()}：这个工具只能只读查询")
    allowed = analytics_views.allowed_views()
    refs = {m.group(1).split(".")[-1].lower() for m in _TABLE_REF_RE.finditer(text)}
    unknown = sorted(r for r in refs if r not in allowed)
    if unknown:
        raise SqlGuardError(
            f"只能查询这些只读视图：{'、'.join(sorted(allowed))}；不允许的表：{'、'.join(unknown)}"
        )
    return text


def run(db_path: str | Path, sql: str) -> dict:
    """执行只读查询；任何失败都返回可读 error（不抛，避免打断对话）。"""
    try:
        text = validate(sql)
    except SqlGuardError as exc:
        return {"error": str(exc), "columns": [], "rows": [], "row_count": 0, "truncated": False}

    if not re.search(r"\blimit\b", text, re.IGNORECASE):
        text = f"{text} LIMIT {MAX_ROWS}"

    path = Path(db_path)
    conn: sqlite3.Connection | None = None
    deadline = time.monotonic() + TIMEOUT_SECONDS
    try:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        conn.execute("PRAGMA query_only=1")
        # 每 1000 条 VM 指令检查一次是否超时 → 超时中断（SQLite 会抛 OperationalError）
        conn.set_progress_handler(lambda: 1 if time.monotonic() > deadline else 0, 1000)
        cur = conn.execute(text)
        columns = [d[0] for d in (cur.description or [])]
        fetched = cur.fetchmany(MAX_ROWS + 1)
        truncated = len(fetched) > MAX_ROWS
        rows = [
            [(str(v)[:MAX_CELL_CHARS] if v is not None else None) for v in row]
            for row in fetched[:MAX_ROWS]
        ]
        return {
            "columns": columns,
            "rows": rows,
            "row_count": len(rows),
            "truncated": truncated,
            "sql": text,
            "note": "rows 只含本次取回的行；row_count 是取回条数，truncated=true 表示还有更多",
        }
    except sqlite3.OperationalError as exc:
        msg = str(exc)
        if "interrupted" in msg.lower():
            msg = f"查询超时（>{TIMEOUT_SECONDS}s），请缩小范围或加更严格的筛选条件"
        return {"error": msg, "columns": [], "rows": [], "row_count": 0, "truncated": False}
    except Exception as exc:  # noqa: BLE001 工具失败不能打断对话
        log.exception("sql_query 执行失败")
        return {"error": f"{type(exc).__name__}: {exc}", "columns": [], "rows": [], "row_count": 0, "truncated": False}
    finally:
        if conn is not None:
            conn.close()


__all__ = ["MAX_ROWS", "SqlGuardError", "run", "validate"]
