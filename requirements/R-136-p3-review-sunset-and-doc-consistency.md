# R-136 P3 复盘正式下线 + 文档口径统一 + 死数据/孤儿接口清理

- **日期**: 2026-09-11
- **状态**: 实施中
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
