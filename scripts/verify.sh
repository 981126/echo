#!/usr/bin/env bash
# echo 质量门禁：lint + 类型检查 + 测试 + 构建
# 任何改动必须通过本脚本，不通过不算完成。
# 说明：本沙箱无法联网安装第三方依赖时，仍执行语法检查 + 纯逻辑测试；
#       安装 backend/requirements.txt 后自动启用 ruff/mypy/pytest 完整门禁。
set -euo pipefail
cd "$(dirname "$0")/.."
FAIL=0
PY=${PYTHON:-python3}
# 沙箱/受限环境：把 pyc 缓存指到可写临时目录，避免 PermissionError
export PYTHONPYCACHEPREFIX="${PYTHONPYCACHEPREFIX:-${TMPDIR:-/tmp}/echo-pycache}"
mkdir -p "$PYTHONPYCACHEPREFIX"

echo "==> echo 质量门禁（lint + 类型检查 + 测试 + 构建）"

# 1) 语法检查（stdlib，离线必跑）
if [ -d backend/app ]; then
  echo "==> [backend] 语法检查 (compileall)"
  $PY -m compileall -q backend/app backend/tests || FAIL=1
fi

# 2) 纯逻辑测试（stdlib 可跑，离线必跑）
if [ -f backend/tests/test_core.py ]; then
  echo "==> [backend] 纯逻辑测试 (test_core)"
  (cd backend && PYTHONPATH=. $PY tests/test_core.py) || FAIL=1
fi

# 3) 完整检查（依赖已安装时）
if $PY -c "import fastapi, sqlalchemy, pytest, httpx" 2>/dev/null; then
  echo "==> [backend] ruff"
  (cd backend && ruff check app tests) || FAIL=1
  echo "==> [backend] mypy"
  (cd backend && mypy app) || FAIL=1
  echo "==> [backend] pytest"
  (cd backend && pytest -q) || FAIL=1
else
  echo "==> [backend] 第三方依赖未安装，跳过 ruff/mypy/pytest（安装 backend/requirements.txt 后启用）"
fi

# 4) 前端
if [ -f frontend/package.json ]; then
  echo "==> [frontend] lint"
  (cd frontend && npm run lint) || FAIL=1
  echo "==> [frontend] build"
  (cd frontend && npm run build) || FAIL=1
else
  echo "==> [frontend] 暂无代码（M2 起启用检查）"
fi

# 5) 文档与需求归档完整性（自描述体系必须存在）
for f in AGENTS.md README.md docs/PRD.md docs/ARCHITECTURE.md docs/WORKFLOW.md docs/DECISIONS.md docs/milestones.md docs/CHANGELOG.md requirements/README.md scripts/update.sh; do
  [ -f "$f" ] || { echo "  缺少必需文件: $f"; FAIL=1; }
done

if [ "$FAIL" -ne 0 ]; then
  echo "==> 门禁未通过 ✘"
  exit 1
fi
echo "==> 门禁通过 ✔"
