#!/usr/bin/env bash
# echo 测试库初始化（R-235）：把 echo_dev 的**表结构 + 数据**复制到 echo_test。
#
# - 复制方式：DROP/CREATE echo_test 库 + pg_dump echo_dev | psql echo_test（最稳，跨实例也行）；
# - 要求本机有 pg_dump / psql / dropdb / createdb（PostgreSQL 客户端工具）；
# - 注意：pytest 每个用例前会清掉 echo_test 全部表，复制进去的数据仅供人工核查/兜底，
#   不是测试运行时的数据基础（测试语义 = 空库起点）。
# - 用法：
#     bash scripts/init_test_db.sh                          # 从 .env 的 ECHO_DATABASE_URL 推导源库（改库名为 echo_dev）
#     SOURCE_URL="postgresql+psycopg://…/echo_dev" bash scripts/init_test_db.sh
#     TARGET_URL="postgresql+psycopg://…/echo_test" bash scripts/init_test_db.sh
set -euo pipefail
cd "$(dirname "$0")/.."

_env_get() {
  [ -f .env ] || return 0
  grep -E "^$1=" .env | tail -1 | cut -d= -f2- | sed -e 's/^["'\'']//' -e 's/["'\'']$//' | xargs || true
}

BASE_URL="${SOURCE_URL:-$(_env_get ECHO_DATABASE_URL)}"
[ -n "${BASE_URL:-}" ] || { echo "缺少 SOURCE_URL / .env ECHO_DATABASE_URL" >&2; exit 1; }

SOURCE="${SOURCE_URL:-${BASE_URL%/*}/echo_dev}"
TARGET="${TARGET_URL:-${BASE_URL%/*}/echo_test}"
# pg_dump/psql 走 libpq，不认识 SQLAlchemy 的 +psycopg 驱动后缀 → 剥掉（postgresql+psycopg:// → postgresql://）
PSQL_SOURCE=$(printf '%s' "$SOURCE" | sed -E 's/^([a-z0-9]+)\+[a-z0-9]+:/\1:/')
PSQL_URL=$(printf '%s' "$TARGET" | sed -E 's/^([a-z0-9]+)\+[a-z0-9]+:/\1:/')

for bin in pg_dump psql dropdb createdb; do
  command -v "$bin" >/dev/null 2>&1 || { echo "找不到 ${bin}（请安装 PostgreSQL 客户端工具）" >&2; exit 1; }
done

echo "复制 ${SOURCE##*/} -> ${TARGET##*/} ..."
dropdb --if-exists "$PSQL_URL" 2>/dev/null || psql "${PSQL_URL%/*}/postgres" -c "DROP DATABASE IF EXISTS ${TARGET##*/};" >/dev/null
createdb "$PSQL_URL" 2>/dev/null || psql "${PSQL_URL%/*}/postgres" -c "CREATE DATABASE ${TARGET##*/};" >/dev/null
pg_dump --clean --if-exists "$PSQL_SOURCE" | psql -q -v ON_ERROR_STOP=1 "$PSQL_URL"
echo "完成：${TARGET##*/}（表数量：$(psql -tAc 'SELECT count(*) FROM information_schema.tables WHERE table_schema='"'"'public'"'"' AND table_type='"'"'BASE TABLE'"'"';' "$PSQL_URL")）"
