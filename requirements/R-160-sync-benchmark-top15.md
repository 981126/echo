# R-160 博主管理：当前主博主卡片新增「同步对标博主前15条」

- **日期**: 2026-09-18
- **状态**: ✅ 已完成（2026-09-18，M149）
- **关联**: `backend/app/services/platform_sync.py`、`backend/app/api/platform.py`、
  `frontend/src/components/CreatorHeaderRow.vue`、`frontend/src/views/CreatorsView.vue`；R-085、R-086、R-109、R-152

## 原文（作者原话，未改动）
> 1.在博主管理的当前博主，全量同步后面加上【同步对标博主前15条】按钮，点击后同步当前主博主下的所有对标博主账号前15条视频

## 反问与确认结论（2026-09-18）
1. **同步深度**：与主博主「同步前15条」完全一致——每个对标账号最新 15 条 + 评论采集 +
   缺视频下载 + 缺转写自动 ASR；已下载/已转写自动跳过（沿用 R-085/R-086/R-093 口径）。
2. **完成后动作**：同步完成后**自动触发一次「重新对标」**（`refetch=False`，不重捞只重算「前2+最新」），
   与每日 06:00/17:00 自动同步（R-109）一致。
3. **实现方式**：后端**一个后台任务**统一编排（遍历当前主博主下全部对标博主依次 `run_sync`），
   一条汇总通知；避免前端发 N 个请求与重复入队判断。
4. **运行中处理**：若某个对标已有同步在跑（`platform_sync` pending/running 且 creator_id 命中）→ **跳过该对标**，
   其余照常，汇总里说明跳过项。
5. **显示范围**：按钮只在**当前主博主**卡片、且其下存在对标博主时显示（非当前主博主卡片不显示）。

## 范围
- **后端**
  - `services/platform_sync.py`：新增 `run_benchmark_top15_sync(db, owner, update=None)` 与后台任务体
    `benchmark_top15_worker(db, payload, update=None)`；单个对标失败不阻断其余（`BudgetExceeded` 记明并停止）；
    收尾 `maybe_start_benchmark_rerun(refetch=False)`。
  - `api/platform.py`：新增 `POST /api/platform/sync-benchmarks`；无当前主博主/无对标 400，
    同类任务已在跑 409；返回 `{task_id}`。完成通知沿用 `platform_sync` 类型（跳转 `/creators`）。
- **前端**
  - `CreatorHeaderRow.vue`：`全量同步` 后加【同步对标博主前15条】按钮（current owner 且有对标时显示）。
  - `CreatorsView.vue`：二次确认（说明含下载/转写成本）→ 调新接口 → 打开进度轮询 `startProgressPoll()`；
    按钮在 HTTP 进行中或该主博主对标有 job 运行时禁用（沿用 R-110 防重复）。

## 不包含
- 不改「全量同步」「同步前15条」主博主既有语义。
- 不改对标博主账号行内「同步」按钮。
- 不改展示规则（前2+最新 R-152）与洗稿链路。
- 不改接口的重复入队判定（`/api/platform/sync` 原样），新接口自带同类任务判重。
- 无表结构变更。

## 验收标准
- 当前主博主卡片在「全量同步」后出现【同步对标博主前15条】；无对标时不显示。
- 点击并对齐全部对标：每个对标账号最新 15 条 + 评论 + 缺视频/缺转写补齐；运行中的对标被跳过。
- 每个对标卡片显示同步进度条；完成后自动触发「重新对标」，通知中心有汇总通知。
- 单测覆盖：遍历全部对标、跳过运行中、无对标报错、完成后触发 rerun（不重捞）。
- `scripts/verify.sh` 全绿（含文档一致 129 路由）+ 接口冒烟 + 前端点检；服务保持运行。

## 排期
M149（前置：R-109 每日统一同步、R-152 对标口径已完成）
