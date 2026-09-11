# R-133 P0 稳定性兜底：备份真实性 + 流水线终态与自愈 + 最小可观测性

- **日期**: 2026-09-11
- **状态**: ✅ 已完成
- **排期**: M122
- **关联**: 系统体检（2026-09-11）；`scripts/backup.sh`、`scheduler.py`、`services/pipeline.py`、`core/pipeline.py`、`tasks.py`、`main.py`

## 原文（作者原话，未改动）
> p0-p3的问题 按照顺序登记 并修复

（上下文：AI 对全系统做了闭环/一致性/bug 体检并给出 P0–P3 分批修复建议，作者要求按顺序登记并修复。）

## P0 范围
1. **备份真实性**：
   - `scripts/backup.sh` 硬编码 `data/echo.db`，而真实库由 `.env` 的 `ECHO_DB_PATH` 指向 `echo_resource/echo.db`；
     `sqlite3.connect` 对不存在的路径会**新建空库**，于是脚本「成功」备份了一个 4KB 空库（实测）。
   - 修复：脚本从 `.env`/配置解析库路径；源库不存在或校验失败要**明确失败**；备份后做完整性校验（表数量 > 0）。
   - `scheduler._backup_job` 用 `check=False` + `except Exception: pass`，完全不知道失败；修复为检查退出码并告警。
2. **流水线终态与自愈**：
   - `run_daily_pipeline` 内部吞掉全部异常只把 `PipelineRun.status` 置 failed，调用它的任务层却记 `done` 并发「每日流水线完成」→ 误导通知是用户唯一信号。
   - `PipelineRun` 卡在 `running` 会永久阻塞后续流水线（`can_run` 判定 running 不可重跑），启动清理只覆盖 `background_tasks`。
   - 修复：任务层感知失败并写 `failed`；启动/超时清理 stale `running`；失败时应用内通知（不能只靠可能没配的邮件）。
3. **最小可观测性**：全后端零日志设施（`grep logging|logger` = 0），53 处 `except` 只 `pass`/`rollback` → 所有失败不可观测。
   - 修复：建立统一 logger 并在关键失败路径（任务失败、定时任务、备份、watcher、流水线）记录；文档记录约定。

## 验收标准
1. 手动执行备份脚本能产出与真实库同量级、可通过完整性校验的备份；真实库缺失时脚本非零退出并给出原因。
2. 备份 job 失败时写站内失败通知（并尝试邮件）。
3. 每日流水线内部失败时后台任务状态为 `failed`（不再报「完成」），且站内有可读失败通知。
4. 服务启动时把遗留的非当日/超时 `running` `PipelineRun` 置 failed，后续流水线可正常重跑。
5. 关键失败路径有日志输出（可 grep 到）。
6. `scripts/verify.sh` 全绿；服务保持运行。

## 实施记录（2026-09-11）
- **备份**：`scripts/backup.sh` 改为从 `.env` 解析 `ECHO_DB_PATH`（回退 `ECHO_DATA_DIR/echo.db`），源库缺失或校验失败非零退出；
  备份后用 `PRAGMA integrity_check` + 表数量校验。实测：真实库 58,372,096 bytes / 28 张表（修复前是 4KB 空库）。
  `scheduler._backup_job` 改为 `capture_output` + 检查退出码，失败走统一告警。
- **流水线**：`run_daily_pipeline` 失败时置 `failed` + 邮件告警 + **抛出 `PipelineError`**（任务层因此写 failed 并站内通知，不再谎报「完成」）；
  `running` 超 2 小时视为卡死可重跑（`core.pipeline.is_stale`）；新增 `mark_stale_pipeline_runs_on_startup` 并在 lifespan 调用。
- **可观测性**：新增 `core/log.py`（`setup_logging`/`get_logger`），main lifespan 与 `setup_scheduler` 初始化；
  在任务失败、定时任务失败、备份失败、inbox 扫描失败、流水线失败等关键路径补日志；`_alert()` 统一「日志 + 站内通知 + 邮件告警」。
- **任务通知健壮性**：`_run_worker` 的失败通知单独 try 包裹（通知写入失败不再把已成功任务改判失败）。
- 测试：新增 `test_r133_stability.py` 6 用例（超时判定、启动自愈、失败传播、fresh running 跳过、stale 重跑、备份脚本真实集成）；
  `verify.sh` 全绿（pytest 166）。
