#!/usr/bin/env bash
# echo 备份：SQLite 热备份 + docs/ + requirements/ 快照，保留最近 10 份。
set -euo pipefail
cd "$(dirname "$0")/.."

STAMP=$(date +%Y%m%d_%H%M%S)
BK_DIR=data/backups/$STAMP
mkdir -p "$BK_DIR"

# SQLite 热备份（官方 backup API，避免拷出坏库）
python3 - "$BK_DIR/echo.db" <<'PY'
import sqlite3, sys
src, dst = "data/echo.db", sys.argv[1]
con = sqlite3.connect(src)
try:
    bck = sqlite3.connect(dst)
    try:
        con.backup(bck)
    finally:
        bck.close()
finally:
    con.close()
print("数据库已备份 ->", dst)
PY

# 文档与需求归档快照
cp -R docs "$BK_DIR/docs" 2>/dev/null || true
cp -R requirements "$BK_DIR/requirements" 2>/dev/null || true

# 保留最近 10 份
ls -1d data/backups/*/ 2>/dev/null | sort -r | tail -n +11 | xargs -I{} rm -rf {} 2>/dev/null || true

echo "备份完成：$BK_DIR"
