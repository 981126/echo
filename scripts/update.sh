#!/usr/bin/env bash
# NAS 一键更新 / 部署（R-145 升级版）：升级前备份 → 构建 → 启动 → 健康检查 → 打印库结构版本
#
# 适用两种上线方式：
#   A) 解包/拉到新版本代码后执行本脚本；
#   B) 直接执行本脚本 —— 它会先尝试 git pull（非 git 仓库自动跳过，兼容解包部署；也可 SKIP_PULL=1 强制跳过）。
#
# 关键点：**先备份**。启动时应用会自动把库结构增量升级
# （新表由 create_all 建、新字段跑 _migrate_*），并且升级前应用自己还会再自动备份一份到
# data/backups/pre_upgrade/（R-145），双保险。任一步失败即非零退出。
set -euo pipefail
cd "$(dirname "$0")/.."

echo "==> ① 升级前备份（回滚预案的前提）"
if [ -f scripts/backup.sh ]; then
  bash scripts/backup.sh
else
  echo "  警告：找不到 scripts/backup.sh，跳过（请在完整仓库里执行）" >&2
fi

if [ -d .git ] && [ "${SKIP_PULL:-0}" != "1" ]; then
  echo "==> ② 拉取代码（git pull --ff-only）"
  git pull --ff-only
else
  echo "==> ② 跳过 git pull（非 git 仓库，或 SKIP_PULL=1）"
fi

echo "==> ③ 构建镜像"
docker compose build

echo "==> ④ 启动/滚动重启"
docker compose up -d

echo "==> ⑤ 健康检查"
ok=0
for _ in $(seq 1 30); do
  sleep 2
  if docker compose exec -T echo python -c "import sys,urllib.request; sys.exit(0 if urllib.request.urlopen('http://localhost:8000/health', timeout=5).status == 200 else 1)" 2>/dev/null; then
    ok=1
    break
  fi
done
if [ "$ok" != "1" ]; then
  echo "健康检查失败：最近日志如下" >&2
  docker compose logs --tail=80 echo >&2
  exit 1
fi
echo "  /health OK"

echo "==> ⑥ 结构自检与库结构版本"
docker compose logs --tail=200 echo | grep -E "结构自检|库结构版本|已自动备份|待应用的结构变更" || true
docker compose exec -T echo python -c "
from sqlalchemy import inspect
from app.db import engine
from app.core import schema_guard

miss = schema_guard.missing_schema(engine)
st = schema_guard.migration_status(engine)
tables = len(inspect(engine).get_table_names())
print(f'  表数量={tables} 已应用迁移={st[\"applied\"]} 最新={st[\"latest\"]} 结构一致={miss[\"ok\"]}')
if not miss['ok']:
    raise SystemExit(f'结构不一致：{miss}')
"

echo "==> 更新完成"
