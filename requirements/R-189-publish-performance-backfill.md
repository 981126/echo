# R-189 发布后表现定时自动回填

- **日期**: 2026-09-28
- **状态**: ✅ 已完成（M178）
- **关联**: `drafts.performance`、`services/draft_performance.py`、`scheduler.py`；R-184

## 原文（作者原话，未改动）
> （R-184 遗留「发布后 24h 定时自动回填」）继续做

## 目标
R-184 只做到「手动记录发布信息 + 按需查表现」。本需求让系统每日自动把已发布稿件的
表现刷到草稿上，卡片直接可见，不用逐条点。

## 做法
- `drafts` 加 `performance` TEXT（`_migrate_draft_publish` 幂等补列）。
- `services/draft_performance.refresh_published_performance`：遍历「status ∈ used/done 且绑定素材」的草稿，
  用 `metrics._platform_breakdown` 聚合各平台最新互动 → 写回 `drafts.performance`（含量化总量 + 刷新时间）。
- `scheduler._publish_backfill_job`：每日 05:00 执行；失败写告警。
- `DraftOut.performance` + 草稿卡片展示「播放/赞/藏/评」。

## 验收
- 回填任务注册；无平台数据时不报错、不伪造；卡片显示表现。
- `scripts/verify.sh` 全绿。

## 排期
M178
