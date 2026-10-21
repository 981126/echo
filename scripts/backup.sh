#!/usr/bin/env bash
# echo 备份：PostgreSQL 逻辑备份（pg_dump）+ docs/ + requirements/ 快照，保留最近 10 份。
#
# R-235：SQLite 热备下线。数据库连接串从环境变量 / .env 的 ECHO_DATABASE_URL 读取；
# 要求运行环境有 pg_dump（PG 客户端工具）；源库连不上或 dump 文件为空一律非零退出
#（调用方 _backup_job 会告警）。需要 pg_dump 与本仓库 .venv 的 psycopg 可用。
set -euo pipefail
cd "$(dirname "$0")/.."

STAMP=$(date +%Y%m%d_%H%M%S)
BK_DIR=data/backups/$STAMP
mkdir -p "$BK_DIR"

# ---------- 解析数据库连接串 ----------
# 优先**环境变量**（容器里没有 .env 文件，只有注入的环境变量），其次读 .env（本地运行）。
_env_get() {
  [ -f .env ] || return 0
  grep -E "^$1=" .env | tail -1 | cut -d= -f2- | sed -e 's/^["'\'']//' -e 's/["'\'']$//' | xargs || true
}
DB_URL="${ECHO_DATABASE_URL:-$(_env_get ECHO_DATABASE_URL)}"
if [ -z "${DB_URL:-}" ]; then
  echo "备份失败：未配置 ECHO_DATABASE_URL（请检查 .env 或环境变量）" >&2
  exit 1
fi

if ! command -v pg_dump >/dev/null 2>&1; then
  echo "备份失败：找不到 pg_dump（请安装 PostgreSQL 客户端工具，或在 NAS 上对 PG 容器执行 pg_dump）" >&2
  exit 1
fi

# Python 预检/统计优先用后端 venv（含 SQLAlchemy + psycopg），退而求其次系统 python3
PYBIN=backend/.venv/bin/python
[ -x "$PYBIN" ] || PYBIN=python3

DUMP_FILE="$BK_DIR/echo.dump"

# 连通性预检（不真正发邮件式静默失败：连不上直接非零退出）
if ! "$PYBIN" - "$DB_URL" <<'PY'
import sys

from sqlalchemy import create_engine, text

url = sys.argv[1]
eng = create_engine(url, pool_pre_ping=True)
try:
    with eng.connect() as conn:
        conn.execute(text("SELECT 1"))
except Exception as exc:  # noqa: BLE001
    print(f"备份失败：数据库连不上（{exc}）", file=sys.stderr)
    sys.exit(1)
finally:
    eng.dispose()
PY
then
  exit 1
fi

pg_dump --format=custom --file="$DUMP_FILE" "$DB_URL"

if [ ! -s "$DUMP_FILE" ]; then
  echo "备份失败：dump 文件为空或不存在 -> ${DUMP_FILE}" >&2
  exit 1
fi

TABLES=$("$PYBIN" - "$DB_URL" <<'PY'
import sys

from sqlalchemy import create_engine, inspect

eng = create_engine(sys.argv[1], pool_pre_ping=True)
try:
    n = len(inspect(eng).get_table_names())
finally:
    eng.dispose()
print(n)
PY
)
if [ "${TABLES:-0}" -le 0 ]; then
  echo "备份失败：源库没有表（连接串可能指错库）" >&2
  exit 1
fi

echo "数据库已备份 -> ${DUMP_FILE}（$(stat -f%z "$DUMP_FILE" 2>/dev/null || stat -c%s "$DUMP_FILE") bytes, ${TABLES} 张表）"

# 文档与需求归档快照
cp -R docs "$BK_DIR/docs" 2>/dev/null || true
cp -R requirements "$BK_DIR/requirements" 2>/dev/null || true

# 保留最近 10 份
ls -1d data/backups/*/ 2>/dev/null | sort -r | tail -n +11 | xargs -I{} rm -rf {} 2>/dev/null || true

echo "备份完成：${BK_DIR}"
