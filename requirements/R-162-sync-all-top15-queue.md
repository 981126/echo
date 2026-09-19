# R-162 博主管理：「同步对标博主前15条」改为「同步所有博主前15条」（队列化、所有博主显示动画）

- **日期**: 2026-09-19
- **状态**: ✅ 已完成（2026-09-19，M151）
- **关联**: `backend/app/services/platform_sync.py`、`backend/app/api/platform.py`、`backend/app/tasks.py`、
  `frontend/src/components/CreatorHeaderRow.vue`、`frontend/src/views/CreatorsView.vue`；
  R-070、R-085/R-086、R-093、R-109、R-152、R-160、R-161

## 原文（作者原话，未改动）
> 同步对标博主前15条，改为同步所有博主账号前15条，点击后将所有博主的任务提交到队列中，然后后台一步消费，前端需要展示所有博主的同步动画

## 反问与确认结论（2026-09-19）
1. **范围**：「所有博主」= **当前主博主 + 其全部对标博主**（主博主账号一并同步，同 daily 口径：最新 15 条 +
   评论采集 + 缺视频下载 + 缺转写补齐；已下载/已转写自动跳过）。
2. **队列与消费**：点击后为**每个博主**各入队一个任务并**预置一条 running 的同步记录**（阶段「排队中…」），
   **一个后台消费者按队列顺序逐个消费**（仍串行执行，避免 TikHub 预算与 SQLite 并发写问题）。
3. **前端动画**：所有参与博主卡片**立即显示同步动画**——排队中的显示不确定进度（「排队中…」），
   轮到该博主后进度条显示真实 done/total；沿用 `GET /api/platform/jobs?status=running` 轮询，切页恢复。
4. **运行中博主**：某博主已有 `platform_sync` pending/running 任务时**跳过该博主**（不重复拉 TikHub/下载），
   汇总通知里说明跳过项；其自身旧任务仍在其卡片上显示动画。
5. **完成后动作**：只要有博主实际同步成功，收尾自动触发一次「重新对标」（`refetch=False`，不重捞）。

## 范围
- **后端**
  - `services/platform_sync.py`：`run_sync` 支持复用**预置 SyncJob**（新增 `job` 参数，缺省行为不变）；
    新增 `run_all_top15_sync(db, owner, update=None)`（供队列消费者使用）与 `all_top15_worker(db, payload, update=None)`；
    新增「入队」函数：为当前主博主+全部对标创建队列任务与预置 SyncJob（跳过运行中博主）。
  - `api/platform.py`：`POST /api/platform/sync-benchmarks` 改为 `POST /api/platform/sync-all`
    （语义：所有博主；无主博主/无任何账号 400；同类批量任务在跑 409），返回 `{task_id, creator_count, skipped}`。
  - `tasks.py`：沿用 `start_task` 起**一个**批量任务线程；队列内每个博主任务使用 `platform_sync` kind 留痕。
- **前端**
  - `CreatorHeaderRow.vue`：按钮文案改为「同步所有博主前15条」。
  - `CreatorsView.vue`：调 `/api/platform/sync-all`；确认弹窗说明含范围与成本；开启进度轮询。
    `pollJobs`/`jobFor` 沿用现有机制即可让所有博主卡片（含主博主）显示动画；排队中显示 `SyncProgressBar` 不确定态。
- **测试**：新增 `tests/test_r162_sync_all_queue.py`（全部博主入队顺序、跳过运行中、预置 SyncJob、完成后 rerun）；
  原 `tests/test_r160_benchmark_top15.py` 随功能被替换而删除。

## 不包含
- 不改「全量同步」「同步前15条」单博主既有语义。
- 不改对标账号行内「同步」按钮与单账号同步。
- 不做博主间并行（刻意保持串行消费，避免预算/锁风险）。
- 无表结构变更（复用 `background_tasks` + `sync_jobs`）。

## 验收标准
- 当前主博主卡片显示【同步所有博主前15条】；点击后所有博主（主+对标）卡片**同时**出现同步动画。
- 队列按顺序逐个消费：任意时刻只有当前博主卡片显示真实 done/total，其余排队中显示不确定动画。
- 运行中的博主被跳过并在汇总通知说明；每个博主完成后 `sync_jobs` 终态正确。
- 全部结束若有过同步，自动触发「重新对标」；通知中心有汇总通知。
- 单测覆盖（队列顺序、跳过、预置 job 复用、rerun）；`scripts/verify.sh` 全绿 + 接口冒烟 + 前端点检；服务保持运行。

## 排期
M151（前置：R-160、R-161 已完成）
