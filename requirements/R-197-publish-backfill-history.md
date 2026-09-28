# R-197 历史已发布内容自动关联 + 表现回填

- **日期**: 2026-09-28
- **状态**: ✅ 已完成（M186）
- **关联**: `drafts.work_id`、`services/publish_backfill.py`、`services/draft_performance.py`、`api/drafts.py`；R-184/R-189

## 原文（作者原话，未改动）
> 给历史已发布内容做一次发布回填，否则“哪类选题表现好”的归因目前没有历史数据。
> 2.允许自动关联

## 做法
- `drafts` 加 `work_id`（关联 works，幂等迁移）。
- `services/publish_backfill`：
  - `preview`：把 status ∈ used/done 的草稿按**规范化标题相似度 ≥ 0.8**匹配当前主博主的 works，列出候选。
  - `apply_links`：写 `work_id`（有本地素材则一并写 `video_id`）与发布平台/链接/时间 → 刷新表现；把自动关联的草稿 id 记入 `app_kv:publish_backfill_applied`。
  - `revert`：只撤销上次自动写入的草稿，不动手工数据（可撤销）。
- `draft_performance.performance_for_draft`：有素材按素材、否则按作品聚合各平台互动；每日回填覆盖两类。
- API：`GET /drafts/publish-links/preview`、`POST /drafts/publish-links/apply`、`POST /drafts/publish-links/revert`。
- 主页「表现归因」在无数据时给「回填历史发布」按钮。

## 验收
- 定向测试：preview 命中、apply 写 work_id、revert 清空；`verify.sh` 全绿。

## 排期
M186
