# R-156 脚本工作台：定稿 + 版本留痕 + 任意两版差异 + 版本链反哺 AI 学习

- **日期**: 2026-09-14
- **状态**: ✅ 已完成（2026-09-14，M145）
- **关联**: `backend/app/models/draft_version.py`（新）、`services/draft_versions.py`（新）、`services/diff_analysis.py`、
  `services/generation.py`、`services/debate.py`、`api/drafts.py`、`frontend/src/views/DraftsView.vue`；R-030⑦、R-117、R-131、R-155

## 原文（作者原话，未改动）
> 1.脚本工作台【洗稿后】这几个字改成【修改后】
> 2.编辑、新增页面添加【定稿】按钮，并且添加tab页【版本】，每次定稿都会保存一条当前正文到版本纪律里面
> 3.ai轮次讨论完后，会将最新讨论的一版定稿留痕
> 4.我可以选择任意两个版本进行差异比较
> 5.ai分析我的稿子时候可以明显看出来从第一稿到最后一稿中间进行了哪些变更，更方便ai深度学习，以后ai生成脚本也会更加准确

## 反问与确认结论（2026-09-14）
1. **定稿语义**：只做「版本快照 + 标记已定稿」，**不锁定**、不改草稿状态，之后可继续改再定稿（版本累加）。
2. **版本内容**：正文 + 标题 + 封面字 + 标签（便于版本 tab 展示与比较）。
3. **定稿动作**：先保存当前编辑再记版本；新建稿有内容则先建稿再记（与「保存」同逻辑，内容全空不落库）。
4. **两版比较**：版本列表里选两个版本（默认最新两版）→ 下方左右红绿 diff。
5. **AI 学习落点**：版本链 → 改稿差异分析（人设建议）+ 生成 few-shot（`_rewrite_examples`）。

## 范围
- **文案**：`DraftsView` 原文对照里「洗稿后」→「修改后」（仅文案）。
- **数据**：新增表 `draft_versions`（`id/draft_id/title/cover_text/script/tags/source/note/created_at`，`source=manual|ai_discuss`）；
  新表由 `create_all` 自动建（无字段迁移），`DATABASE.md` 表数 29→30 并补章节。
- **接口**：
  - `GET /api/drafts/{draft_id}/versions`：按时间倒序返回版本（含正文，供前端本地算 diff）。
  - `POST /api/drafts/{draft_id}/finalize`：入参同保存（title/cover_text/script/tags/video_id）→ 先更新草稿再记一条 `source=manual` 版本；返回版本 + 草稿。
- **AI 讨论自动定稿**：`run_debate` 的「基于原文」分支（R-155 的【讨论/重新讨论】）跑完最后一版后自动记一条 `source=ai_discuss` 版本。
- **前端 `DraftsView` 编辑弹窗**：加【定稿】按钮（编辑 pane 的保存/取消旁）；加第 4 个 tab【版本】——
  版本列表（时间/来源/标题）、选中两个版本（默认最新两版、上限两个）、下方左右 diff（复用 `lib/diff.js`）、
  <2 条版本时提示先定稿；【版本】tab 显示「最新版本与当前正文一致/有未定稿改动」。
- **AI 学习（第 5 条）**：
  - `analyze_diff` 升级为接收**多阶段稿子**（第1稿…第N稿），提示词改为「看作者从初稿到定稿的逐版修改」；
  - `apply_diff_suggestions` 优先用版本链（≥2 版），无版本时退回原 `original_script → script`（行为不变）；
  - 定稿后触发 `diff_analysis` 任务（沿用现有后台任务 + 人设建议确认流程）；
  - `_rewrite_examples`（生成 few-shot）优先用「首版 → 终版」，无版本时退回原 `original_script → script`。
- **文档/测试**：PRD / DESIGN / DATABASE.md / API.md / CHANGELOG / milestones / requirements 索引；新增 pytest。

## 不包含
- 不做**版本回滚/恢复**（本轮只留痕 + 比较；作者要回滚另立需求）。
- 不锁定草稿、不改 `drafts.status` 语义、不动 `drafts` 表字段。
- 不改【原文对照】语义（仍是 `original_script` ↔ 当前正文）。
- 不改对标洗稿页、每日自动生成链路。
- 不清理/改写历史 `draft_discussions` 留痕。

## 验收标准
- 原文对照标题显示「修改后」。
- 编辑/新建弹窗有【定稿】按钮；点定稿后【版本】tab 多一条记录（含标题/封面字/标签/正文/时间/来源）；
  新建稿定稿会先建稿；内容全空时提示未保存、不建稿。
- AI 讨论跑完后自动出现一条「AI 讨论定稿」版本。
- 【版本】tab 能选任意两个版本并看到左右差异。
- 改稿差异分析能看到版本链（多阶段），生成 few-shot 使用首版→终版；无版本时行为与原来一致。
- `scripts/verify.sh` 全绿 + 后端接口冒烟 + 前端点检（headless）；服务保持运行。

## 排期
M145（前置：M144 / R-155 已完成）
