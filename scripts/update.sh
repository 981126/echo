#!/usr/bin/env bash
# R-234：兼容入口 —— 一键部署的实际逻辑已收敛到 scripts/deploy.sh。
# 保留本文件是为了让旧文档/旧习惯（bash scripts/update.sh、SKIP_PULL=1）继续可用。
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec bash "$SCRIPT_DIR/deploy.sh" "$@"
