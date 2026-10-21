#!/usr/bin/env bash
# R-145：本地打包一个可部署版本。
#
# 用 `git archive HEAD` 而不是 tar 整个目录，好处是：
#   ① 只含**被 git 跟踪**的文件 → 天然排除 .env（密钥）、data/（数据）、node_modules/、.venv/；
#   ② 产出可复现：同一个 commit 打出来的包内容一致；
#   ③ 强制「先提交再打包」，避免把未提交的半成品发上线。
#
# 用法：bash scripts/release.sh
# 产出：dist_release/echo_<版本>_<时间戳>.tar.gz
set -euo pipefail
cd "$(dirname "$0")/.."

if ! command -v git >/dev/null 2>&1 || [ ! -d .git ]; then
  echo "打包失败：需要在 git 仓库里运行（本脚本用 git archive 保证只包含被跟踪文件）" >&2
  exit 1
fi

if [ -n "$(git status --porcelain)" ]; then
  echo "打包失败：工作区有未提交改动 —— 先 commit（或用 git stash），避免把半成品发上线：" >&2
  git status --short
  exit 1
fi

VERSION="$(git describe --tags --always 2>/dev/null || echo dev)"
STAMP="$(date +%Y%m%d_%H%M%S)"
OUT_DIR="dist_release"
OUT="${OUT_DIR}/echo_${VERSION//\//_}_${STAMP}.tar.gz"
mkdir -p "$OUT_DIR"

echo "==> 打包（只含被跟踪文件）"
git archive --format=tar.gz --prefix="echo/" -o "$OUT" HEAD

echo "==> 校验包内容"
fail=0
for must in backend/app/main.py backend/app/db.py scripts/backup.sh scripts/update.sh scripts/verify.sh Dockerfile docker-compose.yml; do
  if tar -tzf "$OUT" | grep -qx "echo/${must}"; then
    echo "  ✓ ${must}"
  else
    echo "  ✗ 缺少 ${must}" >&2
    fail=1
  fi
done
# 绝不允许把密钥/数据打进发布包
for forbidden in "echo/.env"; do
  if tar -tzf "$OUT" | grep -q "^${forbidden}$"; then
    echo "  ✗ 包里出现了不该有的文件：${forbidden}" >&2
    fail=1
  fi
done
if tar -tzf "$OUT" | grep -q "node_modules/\|\.venv/"; then
  echo "  ✗ 包里出现了 node_modules/.venv（不该有）" >&2
  fail=1
fi
[ "$fail" -eq 0 ] || { echo "打包校验失败" >&2; exit 1; }

echo
echo "已打包: ${OUT}  ($(du -h "$OUT" | cut -f1))"
echo "版本:   ${VERSION}"
echo "下一步: 传到 NAS 解包到仓库目录，然后执行 bash scripts/update.sh"
echo "        （数据库/封面/素材等运行时数据不在包里，仍在 NAS 的 ./data 卷里）"
