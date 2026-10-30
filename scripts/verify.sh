#!/usr/bin/env bash
# echo 质量门禁：lint + 类型检查 + 测试 + 构建
# 任何改动必须通过本脚本，不通过不算完成。
# 说明：本沙箱无法联网安装第三方依赖时，仍执行语法检查 + 纯逻辑测试；
#       安装 backend/requirements.txt 后自动启用 ruff/mypy/pytest 完整门禁。
set -euo pipefail
cd "$(dirname "$0")/.."
FAIL=0
if [ -n "${PYTHON:-}" ]; then
  PY=$PYTHON
else
  PY=python3
  for cand in python3.12 python3.11 python3.10; do
    if command -v "$cand" >/dev/null 2>&1; then PY=$cand; break; fi
  done
fi
# 脚本会 `cd backend` 跑测试，调用方给的相对路径（如 PYTHON=backend/.venv/bin/python）会失效 →
# 是「存在的相对路径」就转成绝对路径；裸命令名（python3）保持原样交给 PATH 查找。
case "$PY" in
  /*) ;;
  *) [ -x "$PWD/$PY" ] && PY="$PWD/$PY" ;;
esac
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
# 用 `$PY -m <工具>` 而不是裸命令名：不依赖 PATH（脚本会 cd backend，调用方传的相对 PATH 前缀会失效）
if $PY -c "import fastapi, sqlalchemy, pytest, httpx" 2>/dev/null; then
  echo "==> [backend] ruff"
  (cd backend && $PY -m ruff check app tests) || FAIL=1
  echo "==> [backend] mypy"
  (cd backend && $PY -m mypy app) || FAIL=1
  echo "==> [backend] pytest"
  (cd backend && $PY -m pytest -q) || FAIL=1
else
  echo "==> [backend] 第三方依赖未安装，跳过 ruff/mypy/pytest（安装 backend/requirements.txt 后启用）"
fi

# 4) 前端（frontend_v2，R-164；老前端 frontend/ 已于 R-208 下线）
if [ -f frontend_v2/package.json ]; then
  if [ -d frontend_v2/node_modules ]; then
    echo "==> [frontend_v2] lint"
    (cd frontend_v2 && npm run lint) || FAIL=1
    echo "==> [frontend_v2] vitest"
    (cd frontend_v2 && npx vitest run) || FAIL=1
    echo "==> [frontend_v2] build (tsc + vite)"
    (cd frontend_v2 && npm run build) || FAIL=1
  else
    echo "==> [frontend_v2] 依赖未安装，跳过（npm install 后启用）"
    FAIL=1
  fi
fi

# 5) 文档完整性 + 与代码一致性（自描述体系必须存在）
if $PY -c "import sqlalchemy, fastapi" 2>/dev/null; then
  echo "==> [docs] 表数量/路由与代码一致性"
  $PY scripts/check_doc_consistency.py || FAIL=1
fi
for f in AGENTS.md README.md docs/ARCHITECTURE.md docs/DECISIONS.md docs/milestones.md docs/CHANGELOG.md requirements/README.md scripts/update.sh scripts/deploy.sh; do
  [ -f "$f" ] || { echo "  缺少必需文件: $f"; FAIL=1; }
done

if [ "$FAIL" -ne 0 ]; then
  echo "==> 门禁未通过 ✘"
  exit 1
fi
echo "==> 门禁通过 ✔"
