# R-134 P1 任务终态与体验闭环：脏 running 清理 + 讨论进度 + inbox 安全 + 通知深链 + 重启补跑

- **日期**: 2026-09-11
- **状态**: ✅ 已完成
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

## 实施记录（2026-09-11）
- **脏 running 清理**：新增 `tasks._cleanup_stale_sync_state`（启动时把 `sync_jobs` 与 `CreatorAccount.sync_status` 的 running/pending 复位为 failed），
  随 `mark_interrupted_tasks_on_startup` 一起执行；`media_ensure._fail_remaining` 在队列中断（预算耗尽）时把剩余排队行统一置 failed 并发 `task.update`，
  素材卡不再永久「排队中… 4%」。（`card_sync` 的 BackgroundTask 行本身已由 R-089 启动清理覆盖。）
- **讨论进度**：`api/drafts.py` 的 `debate_status` 补上 `@router.get("/{draft_id}/debate-status")`（此前漏装饰器 → 路由未注册 → 前端 404 静默）；
  新增 `debate.clear_debate_state`（清进度状态 + 把占位稿改成「（生成失败，请重试或删除本稿）」）；`generate_async` 改用 `_debate_task` 包装，失败时清理后重新抛出。
- **inbox 安全**：`watcher._scan_once` 改为「先入库 commit 成功 → 再移动文件」；移动失败回滚入库记录并留日志，文件保留在 inbox 待重试。
- **通知深链**：`PromptsView` 新增 `applyDeepLink()`（解析 `#/prompts?key=xxx` 并 `hashchange` 监听）。
  **更正**：`DraftsView` 实际已支持 `?id=`（用 `location.hash` 解析，见 `DraftsView.vue:485`），审计中"两处深链都失效"的结论不准确——只有提示词页失效。
- **重启补跑**：`mark_interrupted_tasks_on_startup` 改为逐条标记 + 写一条汇总站内通知（`task_interrupted`），
  并新增 `_resume_persona_incremental_if_pending` 消费 `persona_incremental_pending`（重新入队增量校验，逐篇提取有缓存、成本可控）；
  `ingest._rerun_if_pending` 修正为「先入队成功再清标记」（原来先清后入队，start_task 失败即永久丢失补跑）。
- 测试：新增 `test_r134_task_loops.py` 9 用例；`verify.sh` 全绿（pytest 175）。
