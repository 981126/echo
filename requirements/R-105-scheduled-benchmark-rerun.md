# R-105-SCHEDULED-BENCHMARK-RERUN: 定时任务每天自动调用「重新对标」（每日生成脚本前1小时）

- **日期**: 2026-09-06
- **提出渠道**: 对话
- **原文摘要**: 添加定时任务调用重新对标功能，在每日生成脚本文案前 1 小时。
- **状态**: ✅ 已完成
- **排期**: M88（已完成）
- **关联**: scheduler.py、benchmark.service（rerun_benchmarks/rerun_worker）、tasks、R-102~R-104

## 作者确认（2026-09-06，需求反问清单）
- Q1 时间：B —— 固定 06:00 触发（每日生成 07:00 前 1 小时；以后改生成时间不跟着变）。
- Q2 运行条件：A —— 没有对标博主时自动跳过；若已有 benchmark_rerun 任务 pending/running 也跳过（防叠任务），不产生失败通知。

## 实施结论（M88，2026-09-06）
1. scheduler.py 注册 06:00 每日任务 id=benchmark_rerun_daily；守卫与启动收敛为 services.benchmark.maybe_start_benchmark_rerun（no_owner/no_benchmark/already_running 静默跳过）。
2. worker 提为 services.benchmark.rerun_worker（api 路由与 scheduler 共用），api/benchmark.py 已复用。
3. 文档同步（CHANGELOG/milestones）+ verify.sh 全绿 + 守卫单测 4 项（新增）。

## 原文（作者原话，未改动）
> 添加定时任务调用【重新对标】功能，在每日生成脚本文案前1小时
