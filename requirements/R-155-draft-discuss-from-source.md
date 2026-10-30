# R-155 脚本工作台：讨论 tab 的「讨论 / 重新讨论」入口（基于原文跑双模型多轮讨论）

- **日期**: 2026-09-14
- **状态**: ✅ 已完成（2026-09-14，M144）
- **关联**: `backend/app/services/debate.py`、`backend/app/services/draft_flow.py`、`backend/app/api/drafts.py`、
  `frontend/src/views/DraftsView.vue`；R-023/R-118/R-131、R-154

## 原文（作者原话，未改动）
> 如果【讨论（双模型留痕）】tab页里面没有讨论过，那么【暂无讨论记录】变为【讨论】按钮，点击后ai拿到原文进行多轮次讨论，并生成标题、封面字、标签，如果讨论过，那么翻到底部有个【重新讨论】按钮，点击后拿到原文重新进行讨论

## 反问与确认结论（2026-09-14）
1. **「原文」口径**：作者答——「如果是洗稿来的草稿，那么使用洗稿素材的 ASR 转译后的文案；如果是自己新建的草稿，直接用草稿中的正文」。
   → 实现映射：`draft.original_script`（对标洗稿时会写入=该素材 ASR 文案）优先；为空则用当前正文 `script`。
2. **结果落回范围**：作者答——「正文 + 标题 + 封面字 + 标签都更新，【原文对照】功能也需要记录并展示原文和讨论后的稿子」。
   → 实现：更新 `script/title/cover_text`，`tags` 与现有合并去重，并把本次使用的原文写入 `original_script`（使新建稿也能用【原文对照】）。
3. **标签**：与现有标签合并去重（不覆盖作者已填的）。
4. **重新讨论留痕**：保留旧记录、追加新一轮（不清空）。
5. **未保存的新建草稿**：提示「先保存草稿再讨论」，不自动建稿（与 R-154 一致）。

## 范围
- **后端**：
  - `run_debate(db, draft, topic, settings=None, source_text="", source_title="")` 增加「基于原文」分支：
    初稿用「按人设把原文改写成原创口播稿」提示词，输出 `title / cover_text / script / tags`；
    写回 `draft.title/cover_text/script`，`tags` 合并去重，`original_script = source_text`（供原文对照）；
    随后沿用现有 N 轮评审/修订 + 自检收口 + `quality` 留痕（轮次取「AI 设置」）。旧调用（`source_text` 为空）行为不变。
  - 新增 `resolve_discussion_source`（`original_script` → `script`，都空则报错）与 `start_discussion`（入队 `draft_discuss` 后台任务）。
  - 新增 `POST /api/drafts/{draft_id}/discuss`：返回 `{task_id}`；草稿不存在 / 无可讨论原文 / 无当前主博主 → 400/404。
- **前端 `DraftsView` 讨论 tab**：
  - 未保存的新建稿（无 id）→ 提示先保存，不给讨论入口。
  - 无留痕 → 「暂无讨论记录」处改为 **【讨论】按钮**。
  - 有留痕 → 列表底部 **【重新讨论】按钮**。
  - 运行中按钮禁用 + 沿用 `debate-status` 轮询显示「⏳ …」；完成后自动刷新弹窗内的标题/封面字/正文/标签/原文案与列表，【原文对照】展示「原文 vs 讨论后」。
- **文档**：API.md(+1 路由) / CHANGELOG / milestones / requirements 索引。

## 不包含
- 不改对标洗稿页的洗稿（仍走 `run_rewrite_debate` 新建草稿）。
- 不改「一键回炉重写」（仍按选题重生成）。
- 不改讨论轮次配置（沿用「AI 设置 → 模型设置」里的轮次）。
- 不改 `draft_discussions` / `drafts` 表结构（无迁移）。
- 不改每日自动生成链路。

## 验收标准
- 无留痕草稿：讨论 tab 显示【讨论】按钮，点击后后台开始多轮讨论并持续留痕；完成后标题/封面字/正文/标签被更新（标签合并），【原文对照】能看到原文与讨论后。
- 有留痕草稿：底部【重新讨论】按钮可再次基于原文讨论，旧留痕保留、追加新一轮。
- 洗稿稿用 `original_script`（洗稿素材 ASR 文案）；新建稿用当前正文。
- 未保存新建稿提示先保存，不产生空稿。
- `scripts/verify.sh` 全绿 + 前端点检（headless）；服务保持运行。

## 排期
M144（前置：M143 / R-154 已完成）
