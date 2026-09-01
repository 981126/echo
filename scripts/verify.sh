#!/usr/bin/env bash
# echo 质量门禁：lint + 类型检查 + 测试 + 构建
# 任何改动必须通过本脚本，不通过不算完成。离线可跑（外部依赖全部 mock）。
set -euo pipefail
cd "$(dirname "$0")/.."
FAIL=0

echo "==> echo 质量门禁（lint + 类型检查 + 测试 + 构建）"

# 后端
if [ -f backend/pyproject.toml ] || [ -f backend/requirements.txt ]; then
  echo "==> [backend] ruff lint"
  (cd backend && ruff check app tests) || FAIL=1
  echo "==> [backend] 类型检查"
  (cd backend && mypy app) || FAIL=1
  echo "==> [backend] pytest"
  (cd backend && pytest -q) || FAIL=1
else
  echo "==> [backend] 暂无代码（M1 起启用检查）"
fi

# 前端
if [ -f frontend/package.json ]; then
  echo "==> [frontend] lint"
  (cd frontend && npm run lint) || FAIL=1
  echo "==> [frontend] build"
  (cd frontend && npm run build) || FAIL=1
else
  echo "==> [frontend] 暂无代码（M1/M2 起启用检查）"
fi

# 文档与需求归档完整性（M0 自描述体系必须存在）
for f in AGENTS.md README.md docs/PRD.md docs/ARCHITECTURE.md docs/WORKFLOW.md docs/DECISIONS.md docs/milestones.md requirements/README.md scripts/update.sh; do
  [ -f "$f" ] || { echo "  缺少必需文件: $f"; FAIL=1; }
done

if [ "$FAIL" -ne 0 ]; then
  echo "==> 门禁未通过 ✘"
  exit 1
fi
echo "==> 门禁通过 ✔"
