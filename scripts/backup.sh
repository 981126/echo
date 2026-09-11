#!/usr/bin/env bash
# echo 备份：SQLite 热备份 + docs/ + requirements/ 快照，保留最近 10 份。
#
# R-133 修复：原来硬编码 src="data/echo.db"（该文件不存在），而 sqlite3.connect 对不存在的
# 路径会**新建空库**，于是脚本「成功」备份了一个 4KB 空库（实测）。现在从 .env 解析真实库路径，
# 并做完整性校验；源库缺失或校验失败一律非零退出（调用方 _backup_job 会告警）。
set -euo pipefail
cd "$(dirname "$0")/.."

STAMP=$(date +%Y%m%d_%H%M%S)
BK_DIR=data/backups/$STAMP
mkdir -p "$BK_DIR"

# ---------- 解析运行时库路径（优先 .env 的 ECHO_DB_PATH） ----------
_env_get() {
  [ -f .env ] || return 0
  grep -E "^$1=" .env | tail -1 | cut -d= -f2- | sed -e 's/^["'\'']//' -e 's/["'\'']$//' | xargs || true
}
DB_PATH="$(_env_get ECHO_DB_PATH)"
DATA_DIR="$(_env_get ECHO_DATA_DIR)"
if [ -z "${DB_PATH:-}" ] && [ -n "${DATA_DIR:-}" ]; then DB_PATH="$DATA_DIR/echo.db"; fi
if [ -z "${DB_PATH:-}" ]; then DB_PATH="data/echo.db"; fi

if [ ! -f "$DB_PATH" ]; then
  echo "备份失败：数据库不存在 -> ${DB_PATH} （请检查 .env 的 ECHO_DB_PATH）" >&2
  exit 1
fi

# SQLite 热备份（官方 backup API）+ 备份后完整性校验
python3 - "$DB_PATH" "$BK_DIR/echo.db" <<'PY'
import os
import sqlite3
import sys

src, dst = sys.argv[1], sys.argv[2]
if not os.path.isfile(src):
    print(f"备份失败：源库不存在 {src}", file=sys.stderr)
    sys.exit(1)

con = sqlite3.connect(src)
try:
    bck = sqlite3.connect(dst)
    try:
        con.backup(bck)
    finally:
        bck.close()
finally:
    con.close()

chk = sqlite3.connect(dst)
try:
    integrity = chk.execute("PRAGMA integrity_check").fetchone()[0]
    tables = chk.execute("SELECT count(*) FROM sqlite_master WHERE type='table'").fetchone()[0]
finally:
    chk.close()

if integrity != "ok" or tables <= 0:
    print(f"备份校验失败：integrity={integrity} tables={tables}", file=sys.stderr)
    sys.exit(1)

print(f"数据库已备份并校验 -> {dst}（{os.path.getsize(dst)} bytes, {tables} 张表）")
PY

# 文档与需求归档快照
cp -R docs "$BK_DIR/docs" 2>/dev/null || true
cp -R requirements "$BK_DIR/requirements" 2>/dev/null || true

# 保留最近 10 份
ls -1d data/backups/*/ 2>/dev/null | sort -r | tail -n +11 | xargs -I{} rm -rf {} 2>/dev/null || true

echo "备份完成：${BK_DIR} （源库 ${DB_PATH}）"
