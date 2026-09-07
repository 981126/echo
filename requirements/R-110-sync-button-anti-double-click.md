# R-110 博主页同步按钮防重复入队

- **日期**: 2026-09-07
- **状态**: ✅ 已完成
- **排期**: M93（已完成，前端交互缺陷修复）
- **原文摘要**: 博主页面「同步」等按钮重复点击时，即使已出现动画进度条（同步正在跑），再次点击仍会再次进入队列，产生重复任务。

## 根因
- 前端 `CreatorsView.vue` 的 `syncingOwner` / `syncingAcct` 只在「POST /api/platform/sync 返回 task_id」这段极短时间内保持非 0，随后在 `finally` 里立即清零。
- 而后台同步任务此时才真正开始跑（进度条来自轮询 `activeJobs`），按钮的 loading/disabled 状态早已解除，于是同步进行中仍可再次点击入队。

## 修复
- 新增 `runningCreators`（由 `activeJobs` 派生：正在运行同步任务的 creator id 集合）。
- 主博主/对标卡片的「全量同步 / 同步前15条」按钮：`syncingOwner === c.id || runningCreators.has(c.id)` 时进入 loading/disabled。
- 账号行「同步」按钮：`syncingAcct === a.id || runningCreators.has(c.id)` 时进入 loading。
- 触发同步成功后先 `await pollJobs()` 再释放本地点击锁，缩小「POST 已返回但进度条尚未接上」的竞态窗口。

## 验收
- 同步进行中（进度条动画出现后），重复点击同一博主的「同步/全量同步/同步前15条」不再产生新队列任务；同步完成后按钮恢复可点。
- `scripts/verify.sh` 全绿（lint + mypy + pytest + 前端 build）。
