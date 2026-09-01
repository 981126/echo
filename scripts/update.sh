#!/usr/bin/env bash
# NAS 一键更新：拉取代码 + 重建 + 健康检查
set -euo pipefail
cd "$(dirname "$0")/.."
echo "==> git pull"
git pull --ff-only
echo "==> docker compose build"
docker compose build
echo "==> docker compose up"
docker compose up -d
echo "==> 健康检查"
sleep 5
curl -fsS http://localhost:8000/health && echo " OK"
echo "==> 更新完成"
