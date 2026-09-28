# R-166 NAS Docker 部署包含 frontend_v2 构建（/v2 在 NAS 可用）

- **日期**: 2026-09-28
- **状态**: ✅ 已完成（2026-09-28，M155）
- **关联**: `Dockerfile`、`.dockerignore`、`backend/app/main.py`；R-164、R-145

## 原文（作者原话，未改动）
> 还有什么没做的

（逐项盘点时发现：Dockerfile 只构建老前端 `frontend/`，NAS 部署后 `frontend_v2/dist` 缺失，
后端 `/v2` 挂载会是 404——R-164 的部署链路没闭环。）

## 范围
- `Dockerfile`：新增阶段 `frontend-v2-build`（node:22-alpine，vite 7 需要 Node ^20.19/>=22.12），
  `npm install` + `npm run build`，产物 COPY 到镜像 `/app/frontend_v2/dist`（与 `main.py` 挂载路径一致）。
- `.dockerignore`：排除 `frontend_v2/dist/`（与老前端同规则，宿主机产物不进构建上下文）。

## 不包含
- 不改老前端构建阶段；不改 docker-compose / update.sh / release.sh（它们只调 docker build，自动涵盖新阶段）。

## 验收
- `docker compose build` 后容器内存在 `/app/frontend_v2/dist`，访问 `http://<NAS>:8000/v2/` 返回新前端。
- 本地无 docker 环境时以静态审查 + verify.sh 全绿为准；NAS 侧下次部署时实测确认。

## 排期
M155
