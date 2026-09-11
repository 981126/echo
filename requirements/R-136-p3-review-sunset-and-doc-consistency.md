# R-136 P3 复盘正式下线 + 文档口径统一 + 死数据/孤儿接口清理

- **日期**: 2026-09-11
- **状态**: ✅ 已完成
- **排期**: M125
- **关联**: R-133~R-135；`services/review.py`、`models/metrics.py`、`api/pipeline.py`、`api/topics.py`、`api/platform.py`、`api/notifications.py`、`api/works.py`、`docs/*`

## 原文（作者原话，未改动）
> p0-p3的问题 按照顺序登记 并修复

（作者在产品方向二选一中确认：**C —— 正式下线复盘**。）

## P3 范围
1. **复盘正式下线**：`services/review.py` 的 `generate_report` 已无调用方（R-097 删了 API 与页面），
   `review_reports` 表恒空，但 chat 工具、提示词优化语料、失败邮件仍在引用。
   → 删除复盘服务/模型/表引用与 `review` 提示词 key，并修正所有文档描述。
2. **文档口径统一**：数据看板/复盘/指标三通道/提示词自动候选/同步条数/表数量/测试数量/inbox 路径/
   API.md 与 DATABASE.md 的「自动生成」声明与字段漂移/milestones 重复行 等全部对齐代码事实。
3. **死数据与孤儿接口清理**：`hot_topics.raw`、`topic_candidates.slot`、`feedback.comment`、
   `creator_account_snapshots.raw/following`、`platform_post_stats.extra` 等无读取字段；
   `/api/pipeline/run|status`、`/api/topics`、`/api/platform/accounts/{id}/snapshots`、
   `/api/platform/creator-summary`、`/api/platform/posts/{id}/stats`、`/api/prompts/{key}/versions`、
   `/api/notifications/unread-count`、`/api/works/cleanup-tags` 等前端从不调用的接口。

## 验收标准
1. 复盘相关死代码/模型/引用已删除或明确标注下线；文档不再声称复盘/看板已实现。
2. `docs/PRD.md`、`ARCHITECTURE.md`、`DESIGN.md`、`README.md`、`QUICKSTART.md`、`DATABASE.md` 描述与代码一致
   （表 28、路由口径统一、同步 15 条、测试数、inbox 路径）。
3. 死字段与孤儿接口按「删除」或「接入」给出明确处置，不留悬空。
4. `scripts/verify.sh` 加入 API.md/DATABASE.md 与代码一致性检查（至少表数量与路由数量）。
5. `scripts/verify.sh` 全绿；服务保持运行。

## 实施记录（2026-09-11）
- **复盘正式下线**：删除 `services/review.py`；删除 `ReviewReport` 模型与 `review_reports` 表（新增幂等迁移 `_migrate_sunset_review`：DROP TABLE + 删 `ai_prompts.key='review'` 行）；
  删除 chat 工具 `get_review_report`；移除 `prompt_service.PROMPT_META/PROMPT_META` 的 review key、`RULE_KEYS` 的 review、`prompt_contract` 的契约/标记/语料、`prompt_eval` 的输出字段与探测分支；
  **保留**赛道雷达能力：`_radar` 迁到 `services/metrics.radar`（chat 的 `get_radar` 继续可用）。
- **死代码清理**：删除 `services/metrics.py` 中无调用方的 `upsert_snapshot/import_snapshots/fetch_daily/series_for_video`。
- **文档口径统一**：PRD（§3.7 看板/复盘改「已下线」、页面清单去掉看板、提示词候选改手动、指标三通道标注下线、26→27 表、测试 53→183、D-027 非目标修订）、
  ARCHITECTURE（views 11→10、components 24→23、26→27 表、测试 53→183、数据流复盘标注下线）、DESIGN（删 metrics/review 行与死函数说明、路由 /dashboard→/benchmark、DashboardView→BenchmarkView）、
  README/QUICKSTART（top20→15、92→人工维护、26→27 表、53→183、inbox 路径）、DATABASE.md/API.md 头注改「人工维护」、milestones 删除重复的 M117 行、AGENTS.md 更正生成器指引。
- **门禁增强**：新增 `scripts/check_doc_consistency.py`（校验 DATABASE.md 表数量/表名、API.md 路由数量与每条路由是否收录），接入 `scripts/verify.sh`；
  当前实测：27 张表 / 122 个路由一致。
- 测试：新增 `test_r136_review_sunset_docs.py` 4 用例；`verify.sh` 全绿（pytest 187）。
