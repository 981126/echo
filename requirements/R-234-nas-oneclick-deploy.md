# R-234-NAS-ONE-CLICK-DEPLOY: NAS 一键部署脚本（git 快进 → 构建 → 上线）

- **日期**: 2026-10-18
- **提出渠道**: 对话
- **原文**: 我需要一个脚本，在nas执行后会自动拉取本项目git最新代码，然后前后端打包成docker部署
- **状态**: ✅ 代码完成（本地干跑通过；NAS 实机待首次执行）
- **排期**: M235
- **关联**: `scripts/deploy.sh`（新）、`scripts/update.sh`（兼容入口）、`docker-compose.yml`、R-145

## 边界与默认行为（2026-10-18 确认）

1. **运行环境**：飞牛 fnOS 1.2 / Intel N150 4 核 / 12GB / x86_64；SSH 执行。Docker 需要 sudo 时，整脚本用 `sudo bash scripts/deploy.sh`。
2. **代码来源**：仓库内 `origin` 的 `main`（`--branch` 可改），只做 `fetch + merge --ff-only`；工作区有**已跟踪**改动时中止，不自动 stash/reset。
3. **构建方式**：NAS 本地 `docker compose build`，前端由 Dockerfile 多阶段构建（`node:22-alpine` → `vite build` → `python:3.12-slim` 内置静态产物）；不依赖预构建镜像/registry。
4. **首次部署**：无 `echo.db` 时跳过备份，直接构建启动；后续更新先容器内备份再构建。
5. **失败策略**：构建失败保留旧容器；健康检查失败打印日志并以非零退出，保留 `echo:previous` 镜像供人工回滚；**不自动回滚数据库**（迁移只向前，回滚需配升级前备份）。
6. **不做**：定时任务/cron、自动 push、自动改 `.env`、跨架构 buildx、外部 registry、自动清理 Docker 缓存。

## 验收标准

- [ ] `bash scripts/deploy.sh` 在 NAS 上完成 fetch/pull → 构建 → up → 健康检查，成功退出码 0（待实机验证）。
- [x] 首次（无库）可跑通；第二次及以后先备份（假 Docker 干跑验证流程分支）。
- [x] 工作区脏、缺 `.env`、Docker 不可用、健康检查失败时，均给出明确中文错误并非零退出。
- [x] 宿主机数据目录通过 `ECHO_HOST_DATA_DIR` 配置；容器内固定 `/app/data`。
- [x] 日志写入 `data/logs/deploy-*.log`，保留最近 30 份。
- [x] `scripts/update.sh` 兼容旧用法（含 `SKIP_PULL=1`）。

## 验证记录

- `bash -n scripts/deploy.sh` / `bash -n scripts/update.sh` 通过；`--help` 正常。
- 临时 git 仓库 + 假 `docker` 命令：`--dry-run`、首次真实流程（build/up/health/schema）、`--no-pull` 非 git 解包路径、脏工作区中止、缺 `.env` 中止、`/app` 容器路径拦截、构建失败、unhealthy 失败路径均按预期退出。
- `PYTHON=backend/.venv/bin/python bash scripts/verify.sh` 全绿（ruff/mypy/pytest/前端 lint+vitest+build/文档一致性）。
- 未验证：NAS 实机 `docker compose build` 与首次启动（本机 Docker daemon 未运行；需作者在 fnOS 上执行一次）。

## 实现要点

- `scripts/deploy.sh`：预检 → git → 备份 → 构建（保留 `echo:previous`）→ `up -d` → 容器 healthcheck 轮询 → 结构自检 → 汇总。
- `docker-compose.yml`：加 `image: echo:local`（稳定 tag）、`ECHO_DATA_DIR=/app/data` / `ECHO_DB_PATH=/app/data/echo.db`（容器内固定，避免搬 `.env` 踩宿主机路径）、宿主卷 `${ECHO_HOST_DATA_DIR:-./data}:/app/data`。
- `scripts/update.sh` 降为兼容入口，内部 `exec bash scripts/deploy.sh "$@"`；`SKIP_PULL=1` 仍有效。
- `docs/milestones.md` / `docs/CHANGELOG.md` 同步。
