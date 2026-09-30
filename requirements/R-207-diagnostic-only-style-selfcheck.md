# R-207 硬自检只留红线；口癖/高频词覆盖率仅诊断

- **日期**: 2026-09-29
- **状态**: ✅ 已完成（M197）
- **关联**: `backend/app/services/generation.py`、`services/debate.py`、`frontend_v2/src/pages/drafts/`；R-131/R-139/R-183

## 原文（作者原话，未改动）
> 高频词、口癖覆盖率这类硬自检：可做诊断，但不该强制重写。否则会逼模型机械塞口头禅，变成模仿腔。

## 反问与确认结论（2026-09-29）
1. **范围**：仅调整脚本生成链路的「生成后自检 / 自动收口重写」；手动「脚本体检」（`core/draft_check.py`）与提示词候选离线评测（`prompt_eval`）不动。
2. **触发重写的硬问题**：**仅红线**（作者定）。AI 腔词、口癖/高频词覆盖率一律只做诊断。
3. **诊断可见**：前端展示（草稿讨论 tab + 草稿卡微标）。
4. **提示词**：`author_style_context` 的「必须模仿」软化为「自然贴近、不要硬塞口头禅」。
5. **验收**：无红线时**不再发生**收口重写；`Draft.quality.diagnostics` 正确落库并在前端可见；有红线时仍重写并标红。

## 根因
正向模仿型指标（口癖/高频词覆盖率）作为硬门禁，会让模型为了让自检通过而机械塞口头禅 → 产出「模仿腔」，反而更不像真人。正向「像作者」应靠提示词软引导（画像/样本/锚点/范本/结构），不靠事后强制重写。

## 做法
- `generation._self_check`：`hard_issues` 只含**红线**；删掉「没有用上口癖」issue。
- 新增 `generation.style_diagnostics`：`{style_coverage, style_matched, style_missing, ai_cliche}`（纯诊断）。
- `debate.run_debate`：`if hard_issues:` 才收口重写；重写提示只带红线、去掉「必须模仿」块；`passed = not hard_issues`；`quality` 增 `diagnostics`。
- 前端：`Draft.quality.diagnostics` 类型 + 讨论 tab「生成自检」区块 + 草稿卡「像作者 NN%」微标 / 红线告警点。
- 提示词措辞软化。

## 排期
M197

## 验收
- [x] verify.sh 全绿（后端 449 例 + 前端 16 文件 58 例 + build + 文档一致 31 表/145 路由）
- [x] 无红线时不发生收口重写（计数 0）；红线时重写 1 次
- [x] AI 腔词/覆盖率 0 只进 `quality.diagnostics`（不再进 `issues`）
- [x] 前端可见诊断：草稿卡「像作者 NN%」微标 + 讨论 tab「生成自检」（红线/覆盖率/命中绿标/未命中灰标/AI 腔词）
- [x] 服务运行中（8000/3000）
