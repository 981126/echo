# R-161 博主管理：多个账号逐个点「同步」后，新点击的按钮不再显示动画

- **日期**: 2026-09-18
- **状态**: ✅ 已完成（2026-09-18，M150）
- **关联**: `frontend/src/views/CreatorsView.vue`、`frontend/src/components/CreatorAccountRow.vue`、
  `frontend/src/components/CreatorHeaderRow.vue`、`backend/app/api/platform.py`（`GET /api/platform/jobs`）；R-070、R-088、R-110

## 原文（作者原话，未改动）
> 2.还有一个bug当我一个一个点击每个账号下的同步前15条，只要点击的账号过多，新点击的就不会出现动画

## 复现与根因（2026-09-18 定位）
- `CreatorsView.vue` 用**单个共享变量** `syncingAcct`（以及 `syncingOwner`）表示「当前哪个账号在转圈」。
- 逐个连点多个账号时，`runSync()` 并发发出多个请求；每个请求结束都会在 `finally` 里执行
  `syncingAcct.value = 0`（`syncingOwner.value = 0`）。**先返回的请求把后点账号的 loading 状态清零**，
  于是点击越多、后点的越容易看不到动画。
- 其次 `pollJobs()` 固定拉 `GET /api/platform/jobs?limit=12` 且**不过滤状态**；
  当运行中的同步 job 较多、又有新的历史 job 时，`runningCreators` 可能被挤掉，进一步导致动画丢失。

## 范围
- **前端**
  - `CreatorsView.vue`：`syncingAcct` / `syncingOwner` 改为 `reactive(new Set())` 按 id 独立记录，
    每个请求只清自己的 id；传给子组件改为布尔（`syncing`）。
  - `CreatorAccountRow.vue`：prop `syncingAcctId`（Number）→ `syncing`（Boolean）；
    `CreatorHeaderRow.vue`：prop `syncingOwnerId`（Number）→ `syncing`（Boolean）。
  - `pollJobs()` 改 `GET /api/platform/jobs?status=running&limit=50`，确保只统计运行中任务、
    且不会被历史 job 挤占；「每 creator 取最新一条」的既有行为不变。
- **后端**
  - `api/platform.py` `list_jobs()` 增加可选 `status` 查询参数（无值行为不变）。

## 不包含
- 不改同步任务本身的入队/并发/预算逻辑。
- 不改素材库卡片同步动画（R-080/R-081/R-091）。
- 无表结构变更。

## 验收标准
- 连续逐个点击多个账号「同步」，每个被点账号都保持 loading，直到自己的请求/任务结束，互不干扰。
- 运行中任务的进度条不再因历史 job 被挤出而消失。
- `scripts/verify.sh` 全绿 + 前端点检（多账号连点动画正常）；服务保持运行。

## 排期
M150（与 R-160 同批交付）
