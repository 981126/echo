# R-168 老前端 frontend/ 标记废弃：启动/修改项目一律指 frontend_v2

- **日期**: 2026-09-28
- **状态**: ✅ 已完成（2026-09-28，M157）
- **关联**: `AGENTS.md`、`README.md`、`docs/QUICKSTART.md`、`docs/PRD.md`、`docs/ARCHITECTURE.md`；R-164

## 原文（作者原话，未改动）
> 在文档中将老的前端项目标成废弃，以后说启动项目、修改项目都不修改老前端项目，而是新前端项目

## 确认结论（2026-09-28）
- `frontend/`（Vue 3 + Naive UI）标记为**废弃（deprecated）**：不再新增功能、不再修 bug、不改代码。
- 以后「启动项目」「修改项目」**一律指** `frontend_v2/`（React，dev 3000 / 生产 /v2）。
- 老前端暂不删除（生产仍挂根路径可访问，作为历史兜底；verify.sh 仍保留其 lint/build 防腐，
  直到后续决定下线/删除——删除属新需求）。

## 范围
- 文档标注：`AGENTS.md`（目录速览 + 技术栈 + 默认前端约定）、`README.md`（运行命令与说明）、
  `docs/QUICKSTART.md`（启动命令改 frontend_v2:3000）、`docs/PRD.md`、`docs/ARCHITECTURE.md`、
  milestones/CHANGELOG/需求索引。

## 不包含
- 不删除/不改动 `frontend/` 目录内任何代码。
- 不改 Docker/verify 中老前端构建（保留构建防腐，根路径仍可访问）。

## 验收
- 文档中老前端均标注废弃、默认前端为 frontend_v2；QUICKSTART 启动命令指向 3000。
- `scripts/verify.sh` 全绿；服务保持运行。

## 排期
M157
