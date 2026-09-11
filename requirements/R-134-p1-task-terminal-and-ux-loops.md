# R-134 P1 任务终态与体验闭环：脏 running 清理 + 讨论进度 + inbox 安全 + 通知深链 + 重启补跑

- **日期**: 2026-09-11
- **状态**: 实施中
- **排期**: M123
- **关联**: R-133；`platform_sync.py`、`media_ensure.py`、`models/platform.py`、`api/drafts.py`、`services/debate.py`、`watcher.py`、`DraftsView.vue`、`PromptsView.vue`、`ingest.py`

## 原文（作者原话，未改动）
> p0-p3的问题 按照顺序登记 并修复

## P1 范围
1. **脏 running 清理**：`card_sync` 队列中断（预算耗尽 `break`/异常）后剩余行永久 `running`，素材卡永久转圈；
   `sync_jobs`/`CreatorAccount.sync_status` 无启动清理，同步中途重启后博主页进度条永久「同步中」（最长 60 天）。
2. **双模型讨论进度**：后端 `debate_status` 漏了 `@router.get` 装饰器 → 路由未注册，前端 404 被 catch 吞掉；
   失败时占位稿「（双模型讨论生成中…）」与「思考中」状态永久残留。
3. **inbox 安全**：`watcher._scan_once` 先 `path.replace(dest)` 再入库，入库失败 → 文件移出 inbox 但库里没记录 = **素材永久丢失**（异常还被 `except: pass` 吞）。
4. **通知深链**：通知 target 里的 `/drafts?id=N` 与 `/prompts?key=xxx` 目标页不读 query → 点了到不了目标。
5. **重启补跑**：`mark_interrupted_tasks_on_startup` 静默改判 failed 且不通知；`persona_incremental_pending` 补跑标记不消费。

## 验收标准
1. 启动时清理 stale `running` 的 `card_sync` 任务行与 `sync_jobs`/`sync_status`，前端不再永久转圈。
2. `GET /api/drafts/{id}/debate-status` 可用；讨论失败后清状态与占位稿，不再残留「思考中」。
3. inbox 监听改为「先入库成功再移动文件」，失败有日志与通知，不丢素材。
4. `DraftsView` 支持 `?id=`、`PromptsView` 支持 `?key=`，通知点击能定位到目标。
5. 重启中断任务写站内通知；`persona_incremental_pending` 标记被消费（重新入队）。
6. `scripts/verify.sh` 全绿；服务保持运行。
