#!/usr/bin/env bash
# R-234：NAS 一键部署 —— 拉取最新代码 → 备份 → 构建前后端镜像 → 启动 → 健康检查 → 结构自检
#
# 在 NAS 的仓库目录执行：
#   sudo bash scripts/deploy.sh
#   sudo bash scripts/deploy.sh --branch main --force
#
# 选项：
#   --branch <name>   部署分支（默认 main；也可用 ECHO_DEPLOY_BRANCH）
#   --no-pull         跳过 git 拉取（兼容 SKIP_PULL=1）
#   --force           代码没变也强制重建镜像
#   --skip-backup     跳过升级前备份
#   --pull-base       构建时 --pull（更新基础镜像）
#   --dry-run         只做检查并打印将执行的命令，不拉取/构建/启动
#   -h, --help        显示帮助
#
# 设计约束：
#   - 单实例：APScheduler 在进程内，绝不加 --workers / 多副本
#   - 失败不自动回滚数据库：迁移只向前，回滚需用升级前备份
#   - 不自动 stash/reset：工作区有已跟踪改动时中止，避免覆盖作者改动
set -Eeuo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

BRANCH="${ECHO_DEPLOY_BRANCH:-main}"
DO_PULL="${DO_PULL:-1}"
FORCE=0
SKIP_BACKUP="${SKIP_BACKUP:-0}"
PULL_BASE=0
DRY_RUN=0
IMAGE_NAME="echo:local"
PREV_IMAGE_NAME="echo:previous"
CONTAINER_NAME="echo"
PROJECT_NAME="echo"
# 无人值守：缺凭据时直接失败，别卡在 git 用户名/密码提示
export GIT_TERMINAL_PROMPT=0

usage() {
  cat <<'USAGE'
NAS 一键部署：拉取最新代码 → 备份 → 构建前端+后端镜像 → 启动 → 健康检查

用法：
  sudo bash scripts/deploy.sh [选项]

选项：
  --branch <name>   部署分支（默认 main；也可用 ECHO_DEPLOY_BRANCH）
  --no-pull         跳过 git 拉取（兼容 SKIP_PULL=1）
  --force           代码没变也强制重建镜像
  --skip-backup     跳过升级前备份
  --pull-base       构建时 --pull（更新基础镜像）
  --dry-run         只做检查并打印将执行的命令，不拉取/构建/启动
  -h, --help        显示本帮助

首次部署没有 echo.db 时会自动跳过备份；之后每次升级前都会先备份。
日志：data/logs/deploy-*.log（保留最近 30 份）
USAGE
}

step() { printf '\n\033[1;36m==> %s\033[0m\n' "$*"; }
info() { printf '    %s\n' "$*"; }
warn() { printf '\033[1;33m    ⚠ %s\033[0m\n' "$*"; }
die() {
  trap - ERR
  printf '\n\033[1;31m✘ %s\033[0m\n' "$*" >&2
  exit 1
}

while [ $# -gt 0 ]; do
  case "$1" in
    --branch)
      [ $# -ge 2 ] || die "--branch 缺少参数"
      BRANCH="$2"
      shift 2
      ;;
    --no-pull)
      DO_PULL=0
      shift
      ;;
    --force)
      FORCE=1
      shift
      ;;
    --skip-backup)
      SKIP_BACKUP=1
      shift
      ;;
    --pull-base)
      PULL_BASE=1
      shift
      ;;
    --dry-run)
      DRY_RUN=1
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      die "未知参数：$1（用 --help 查看用法）"
      ;;
  esac
done

# 兼容旧 update.sh 的 SKIP_PULL=1
if [ "${SKIP_PULL:-0}" = "1" ]; then
  DO_PULL=0
fi

START_TS="$(date +%s)"
LOG=""
LOG_DIR="$ROOT/data/logs"
if [ "${ECHO_DEPLOY_NO_LOG:-0}" = "1" ]; then
  : # 测试/受限环境：ECHO_DEPLOY_NO_LOG=1 关闭文件日志（仍输出到终端）
elif mkdir -p "$LOG_DIR" 2>/dev/null && [ -w "$LOG_DIR" ]; then
  LOG="$LOG_DIR/deploy-$(date +%Y%m%d-%H%M%S).log"
  exec > >(tee -a "$LOG") 2>&1
  ln -sfn "$(basename "$LOG")" "$LOG_DIR/latest.log" 2>/dev/null || true
fi

trap 'rc=$?; trap - ERR; die "第 ${LINENO} 行执行失败（退出码 ${rc}）"' ERR

# 单实例锁：优先 flock；没有 flock（如 macOS）时用 mkdir 锁
LOCK_FILE="${TMPDIR:-/tmp}/echo-deploy.lock"
LOCK_DIR=""
cleanup() {
  if [ -n "$LOCK_DIR" ]; then
    rmdir "$LOCK_DIR" 2>/dev/null || true
  fi
}
trap cleanup EXIT
if command -v flock >/dev/null 2>&1; then
  exec 9>"$LOCK_FILE"
  flock -n 9 || die "已有部署进程在运行（锁：${LOCK_FILE}）"
else
  LOCK_DIR="${LOCK_FILE}.d"
  mkdir "$LOCK_DIR" 2>/dev/null || die "已有部署进程在运行（锁：${LOCK_DIR}）"
fi

run() {
  if [ "$DRY_RUN" = 1 ]; then
    printf '    [dry-run]'
    printf ' %q' "$@"
    printf '\n'
  elif ! "$@"; then
    die "命令失败：$(printf '%q ' "$@")"
  fi
}

env_get() {
  local key="$1" line=""
  [ -f "$ROOT/.env" ] || return 0
  line="$(grep -E "^${key}=" "$ROOT/.env" 2>/dev/null | tail -1 || true)"
  [ -n "$line" ] || return 0
  printf '%s' "${line#*=}" | sed -e 's/\r$//' -e 's/^["'\'']//' -e 's/["'\'']$//'
}

git_run() {
  local -a args
  args=(-c "safe.directory=$ROOT" -C "$ROOT")
  if [ "$(id -u)" -eq 0 ] && [ -n "${SUDO_USER:-}" ] && [ "$SUDO_USER" != "root" ]; then
    local owner=""
    owner="$(stat -c %U "$ROOT" 2>/dev/null || stat -f %Su "$ROOT" 2>/dev/null || true)"
    if [ "$owner" = "$SUDO_USER" ] && sudo -n -u "$SUDO_USER" true 2>/dev/null; then
      sudo -u "$SUDO_USER" git "${args[@]}" "$@"
      return
    fi
  fi
  git "${args[@]}" "$@"
}

# ---------- ① 预检 ----------
step "① 预检"
[ -f "$ROOT/.env" ] || die "缺少 .env：先 cp .env.example .env，填好 ECHO_ACCESS_TOKEN 等配置再部署"
command -v docker >/dev/null 2>&1 || die "未安装 docker"
HAS_GIT=0
if command -v git >/dev/null 2>&1; then
  HAS_GIT=1
fi
if [ "$HAS_GIT" = 0 ] && [ "$DO_PULL" = 1 ]; then
  die "未安装 git：请先安装，或用 --no-pull 部署已解包的代码"
fi

if docker compose version >/dev/null 2>&1; then
  COMPOSE=(docker compose -p "$PROJECT_NAME")
elif command -v docker-compose >/dev/null 2>&1; then
  COMPOSE=(docker-compose -p "$PROJECT_NAME")
else
  die "缺少 docker compose（Docker 20.10+ 自带 compose 插件；老版本请装 docker-compose）"
fi
docker info >/dev/null 2>&1 || die "无法连接 Docker。若当前用户不在 docker 组，请用 sudo bash scripts/deploy.sh"
COMPOSE_VER="$("${COMPOSE[@]}" version --short 2>/dev/null | head -1 || true)"
info "Docker: $(docker --version)"
info "Compose: ${COMPOSE_VER:-unknown}"

IS_GIT=0
if [ "$HAS_GIT" = 1 ] && git_run rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  IS_GIT=1
fi
if [ "$IS_GIT" = 1 ]; then
  git_run remote get-url origin >/dev/null 2>&1 || die "仓库没有 origin 远程，无法拉取最新代码"
elif [ "$DO_PULL" = 1 ]; then
  die "$ROOT 不是 git 仓库；请用 git clone 部署，或加 --no-pull 用解包代码构建"
else
  info "非 git 仓库：跳过 git 拉取/版本检查（--no-pull）"
fi

DATA_DIR_ENV="$(env_get ECHO_DATA_DIR)"
DB_PATH_ENV="$(env_get ECHO_DB_PATH)"
# 容器 WORKDIR=/app，所以 ./data 也等价于 /app/data；只对真正像宿主机路径的值告警
case "$DATA_DIR_ENV" in
  ""|"/app/data"|"/app/data/"|"./data"|"./data/"|"data"|"data/") ;;
  *) warn ".env 里 ECHO_DATA_DIR=${DATA_DIR_ENV}；compose 会强制为 /app/data，宿主机目录请用 ECHO_HOST_DATA_DIR" ;;
esac
case "$DB_PATH_ENV" in
  ""|"/app/data/"*|"./data/"*|"data/"*) ;;
  *) warn ".env 里 ECHO_DB_PATH=${DB_PATH_ENV}；compose 会强制为 /app/data/echo.db" ;;
esac
TOKEN="$(env_get ECHO_ACCESS_TOKEN)"
if [ -z "$TOKEN" ] || [ "$TOKEN" = "change-me" ]; then
  warn "ECHO_ACCESS_TOKEN 仍是空值/change-me，强烈建议改成强口令"
fi

HOST_DATA_DIR="$(env_get ECHO_HOST_DATA_DIR)"
[ -n "$HOST_DATA_DIR" ] || HOST_DATA_DIR="./data"
case "$HOST_DATA_DIR" in
  /*) ;;
  *) HOST_DATA_DIR="$ROOT/${HOST_DATA_DIR#./}" ;;
esac
HOST_DATA_DIR="${HOST_DATA_DIR%/}"
[ -n "$HOST_DATA_DIR" ] || HOST_DATA_DIR="/"
case "$HOST_DATA_DIR" in
  /app/*) die "ECHO_HOST_DATA_DIR=$HOST_DATA_DIR 是容器内路径；请填 NAS 宿主机路径，如 /vol1/1000/docker/echo/data" ;;
esac
if [ "$DRY_RUN" = 0 ]; then
  mkdir -p "$HOST_DATA_DIR" || die "无法创建数据目录：${HOST_DATA_DIR}（检查权限/挂载）"
fi
info "宿主机数据目录: $HOST_DATA_DIR"

if [ "$IS_GIT" = 1 ]; then
  DIRTY="$(git_run status --porcelain --untracked-files=no)"
  if [ -n "$DIRTY" ]; then
    printf '%s\n' "$DIRTY" >&2
    die "工作区有未提交的已跟踪改动，已停止（脚本不会 stash/reset）。请先 commit 或手动处理"
  fi
fi

# ---------- ② 拉取最新代码 ----------
step "② 拉取最新代码"
OLD_HEAD=""
NEW_HEAD=""
if [ "$IS_GIT" = 1 ] && [ "$DO_PULL" = 1 ] && [ "$DRY_RUN" = 1 ]; then
  OLD_HEAD="$(git_run rev-parse HEAD)"
  NEW_HEAD="$OLD_HEAD"
  info "[dry-run] 将执行 git fetch + merge --ff-only origin/$BRANCH"
  info "当前版本：$(git_run log -1 --pretty='%h %s')"
elif [ "$IS_GIT" = 1 ] && [ "$DO_PULL" = 1 ]; then
  OLD_HEAD="$(git_run rev-parse HEAD)"
  git_run fetch --prune origin || die "git fetch 失败：检查网络/仓库权限（也可 --no-pull 用本地代码部署）"
  git_run rev-parse --verify --quiet "origin/$BRANCH" >/dev/null || die "远程没有分支 origin/$BRANCH"
  CURRENT_BRANCH="$(git_run rev-parse --abbrev-ref HEAD)"
  if [ "$CURRENT_BRANCH" != "$BRANCH" ]; then
    info "切换分支：${CURRENT_BRANCH:-detached} → $BRANCH"
    if git_run show-ref --verify --quiet "refs/heads/$BRANCH"; then
      git_run checkout "$BRANCH"
    else
      git_run checkout -b "$BRANCH" --track "origin/$BRANCH"
    fi
  fi
  git_run merge --ff-only "origin/$BRANCH" || die "无法快进到 origin/${BRANCH}（本地有分叉提交）。请手动处理后再部署"
  NEW_HEAD="$(git_run rev-parse HEAD)"
  info "当前版本：$(git_run log -1 --pretty='%h %s')"
  if [ "$OLD_HEAD" = "$NEW_HEAD" ]; then
    info "代码无变化"
  else
    info "更新：${OLD_HEAD:0:7} → ${NEW_HEAD:0:7}"
  fi
elif [ "$IS_GIT" = 1 ]; then
  OLD_HEAD="$(git_run rev-parse HEAD)"
  NEW_HEAD="$OLD_HEAD"
  info "已跳过 git 拉取（--no-pull / SKIP_PULL=1）"
  info "当前版本：$(git_run log -1 --pretty='%h %s')"
else
  info "已跳过 git 拉取（非 git 仓库，--no-pull）"
fi

# ---------- ③ 备份 ----------
step "③ 备份数据库"
DB_HOST="$HOST_DATA_DIR/echo.db"
if [ ! -s "$DB_HOST" ] && [ -s "$ROOT/data/echo.db" ] && [ "$HOST_DATA_DIR" != "$ROOT/data" ]; then
  warn "当前数据目录没有 echo.db，但仓库 ./data/echo.db 存在；确认 ECHO_HOST_DATA_DIR 是否改错（改错会像换了一个空库）"
fi
if [ "$SKIP_BACKUP" = 1 ]; then
  info "已跳过（--skip-backup）"
elif [ ! -s "$DB_HOST" ]; then
  info "首次部署（$DB_HOST 不存在），跳过备份"
elif [ "$DRY_RUN" = 1 ]; then
  info "[dry-run] 将在容器内执行 scripts/backup.sh"
else
  CID="$("${COMPOSE[@]}" ps -q "$CONTAINER_NAME" 2>/dev/null || true)"
  if [ -n "$CID" ]; then
    info "备份到容器内 data/backups/"
    if ! "${COMPOSE[@]}" exec -T "$CONTAINER_NAME" bash scripts/backup.sh; then
      die "备份失败，已停止部署（未构建/未重启；旧容器仍在运行）"
    fi
  elif docker image inspect "$IMAGE_NAME" >/dev/null 2>&1; then
    warn "容器未运行，用一次性容器执行备份"
    if ! "${COMPOSE[@]}" run --rm --no-deps --entrypoint bash "$CONTAINER_NAME" scripts/backup.sh; then
      die "备份失败，已停止部署（未构建/未重启）"
    fi
  else
    warn "容器/镜像都不存在，无法备份；继续部署（请确认 $DB_HOST 不是重要库）"
  fi
fi

# ---------- ④ 构建 ----------
step "④ 构建镜像（前端 + 后端）"
if docker image inspect "$IMAGE_NAME" >/dev/null 2>&1; then
  run docker tag "$IMAGE_NAME" "$PREV_IMAGE_NAME"
  info "已保留上一版镜像：$PREV_IMAGE_NAME"
fi
if [ "$IS_GIT" = 1 ] && [ "$DO_PULL" = 1 ] && [ "$FORCE" = 0 ] && [ "$OLD_HEAD" = "$NEW_HEAD" ] && docker image inspect "$IMAGE_NAME" >/dev/null 2>&1; then
  info "代码未变化且镜像已存在，跳过构建（--force 可强制重建）"
else
  BUILD_ARGS=(build)
  if [ "$PULL_BASE" = 1 ]; then
    BUILD_ARGS+=(--pull)
  fi
  run "${COMPOSE[@]}" "${BUILD_ARGS[@]}"
fi

# ---------- ⑤ 启动 ----------
step "⑤ 启动新版本"
run "${COMPOSE[@]}" up -d --remove-orphans --no-build --force-recreate

# ---------- ⑥ 健康检查 ----------
step "⑥ 健康检查"
if [ "$DRY_RUN" = 1 ]; then
  info "[dry-run] 跳过"
else
  CID=""
  for _ in $(seq 1 10); do
    CID="$("${COMPOSE[@]}" ps -q "$CONTAINER_NAME" 2>/dev/null || true)"
    [ -n "$CID" ] && break
    sleep 1
  done
  [ -n "$CID" ] || die "容器未启动"

  HEALTH_TIMEOUT="${HEALTH_TIMEOUT:-180}"
  i=0
  STATUS="unknown"
  while [ "$i" -lt "$HEALTH_TIMEOUT" ]; do
    STATUS="$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' "$CID" 2>/dev/null || echo unknown)"
    case "$STATUS" in
      healthy) break ;;
      unhealthy|exited|dead) break ;;
    esac
    sleep 2
    i=$((i + 2))
  done
  if [ "$STATUS" != "healthy" ]; then
    "${COMPOSE[@]}" ps >&2 || true
    "${COMPOSE[@]}" logs --tail=100 "$CONTAINER_NAME" >&2 || true
    die "健康检查失败（状态：${STATUS}）。上一版镜像保留为 ${PREV_IMAGE_NAME}；数据库迁移不会自动回滚"
  fi
  info "健康：$STATUS"
fi

# ---------- ⑦ 结构自检 ----------
step "⑦ 结构自检"
if [ "$DRY_RUN" = 1 ]; then
  info "[dry-run] 跳过"
else
  if ! "${COMPOSE[@]}" exec -T "$CONTAINER_NAME" python - <<'PY'
from sqlalchemy import inspect
from backend.app.db import engine
from backend.app.core import schema_guard

miss = schema_guard.missing_schema(engine)
st = schema_guard.migration_status(engine)
tables = len(inspect(engine).get_table_names())
print(f"  表数量={tables} 已应用迁移={st['applied']} 最新={st['latest']} 结构一致={miss['ok']}")
if not miss["ok"]:
    raise SystemExit(f"结构不一致：{miss}")
PY
  then
    die "结构自检失败（服务已启动，但库结构与代码不一致）。请查看上面的输出/容器日志"
  fi
fi

# ---------- 汇总 ----------
step "完成"
if [ "$IS_GIT" = 1 ]; then
  info "版本：$(git_run log -1 --pretty='%h %s')"
else
  info "版本：非 git 仓库（解包部署）"
fi
if [ "$DRY_RUN" = 0 ]; then
  info "镜像：$(docker image inspect --format '{{.Id}}' "$IMAGE_NAME" 2>/dev/null | cut -c1-19 || echo unknown)"
fi
WEB_URL="$(env_get ECHO_WEB_BASE_URL)"
if [ -z "$WEB_URL" ] || printf '%s' "$WEB_URL" | grep -Eq '://(localhost|127\.0\.0\.1)(:|$)'; then
  IP=""
  if command -v ip >/dev/null 2>&1; then
    IP="$(ip route get 1.1.1.1 2>/dev/null | awk '{for (i=1; i<=NF; i++) if ($i=="src") {print $(i+1); exit}}' || true)"
  fi
  [ -n "$IP" ] || IP="$(hostname -I 2>/dev/null | tr ' ' '\n' | grep -E '^[0-9]+\.' | head -1 || true)"
  if [ -n "$IP" ]; then
    WEB_URL="http://$IP:8000"
  fi
fi
if [ -n "$WEB_URL" ]; then
  info "访问：$WEB_URL"
fi
if [ -n "$LOG" ]; then
  info "日志：$LOG"
fi
info "耗时：$(( $(date +%s) - START_TS ))s"
if [ "$DRY_RUN" = 1 ]; then
  info "dry-run 完成：未拉取/构建/启动"
fi

# 日志保留最近 30 份
if [ -n "$LOG" ]; then
  OLD_LOGS="$(ls -1t "$LOG_DIR"/deploy-*.log 2>/dev/null | tail -n +31 || true)"
  if [ -n "$OLD_LOGS" ]; then
    printf '%s\n' "$OLD_LOGS" | while IFS= read -r f; do
      rm -f "$f" || true
    done
  fi
fi
