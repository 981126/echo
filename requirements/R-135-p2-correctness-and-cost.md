# R-135 P2 正确性与成本：重复入队判重 + 预算护栏 + 生成模型策略 + 选题池隔离 + 四维分回流

- **日期**: 2026-09-11
- **状态**: 实施中
- **排期**: M124
- **关联**: R-133/R-134；`api/videos.py`、`api/platform.py`、`services/platform_sync.py`、`services/media_ensure.py`、`services/platform/budget.py`、`services/generation.py`、`services/pipeline.py`、`services/feedback.py`

## 原文（作者原话，未改动）
> p0-p3的问题 按照顺序登记 并修复

## P2 范围
1. **重复入队判重**：转写（`api/videos.py`）与平台同步（`api/platform.py`）没有 in-flight 检查，连点会重复调用真实 ASR / TikHub（=重复计费）；
   媒体补齐也无去重。
2. **预算护栏**：`BudgetExceeded`（RuntimeError 子类）被通用 `except` 吞掉 → 任务仍以 done 收尾报「同步完成」；
   且 `_charge` 在请求**之后**调用，护栏并不真正拦截请求。
3. **生成模型策略**：`generate_draft` 固定 `DeepSeekClient`，设置的「生成模型策略」只对双模型讨论生效 →
   每日自动生成、灵感池一键生成、同步生成、回炉、AI 对话生成、提示词自测全部忽略该设置（PRD 写「默认 Kimi」）。
4. **选题池博主隔离**：`TopicIdea.creator_id` 只写不读，`pipeline._comment_candidates` 无 creator 过滤 →
   对标博主评论区的灵感会串进主博主每日生成。
5. **四维分回流**：`hook/pace/ending/style_score` 只在手动提示词优化语料里用到，生成与人设学习完全不读；
   前端却提示「会精确回传人设学习」。

## 验收标准
1. 转写/同步/媒体补齐在同类任务 pending/running 时拒绝重复入队（409 或复用 task_id）。
2. 预算耗尽时任务以 failed 收尾并给出「今日预算已用完」通知；预算预检发生在请求之前。
3. 「生成模型策略」对 `generate_draft` 生效（含每日流水线自动生成）。
4. 选题池（topic-pool 与每日评论候选）按当前主博主过滤，对标评论不再串味。
5. 四维分节分被注入生成上下文（如按维度挑选范例），前端提示语与事实一致。
6. `scripts/verify.sh` 全绿；服务保持运行。
