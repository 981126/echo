# R-209 回退留痕与版本链归因修复（采用/好评不再被误认为「AI 讨论结果好」）

- **日期**: 2026-09-29
- **状态**: ✅ 已完成（M203）
- **关联**: `backend/app/api/drafts.py`、`services/draft_versions.py`、`services/diff_analysis.py`、`services/generation.py`、`services/debate.py`；R-155/R-156/R-157/R-178

## 原文（作者原话，未改动）
> 我手动创建了1篇草稿 点击了定稿，我使用讨论功能讨论了这篇草稿，讨论出来的结果不如我原稿，于是我回退到了原稿，这个时候我在外面点击采用、或者快速反馈好，他会认为是ai讨论出来的结果是好的吗，但实际我只是采用了原稿，如何让ai识别呢

## 根因（排查结论）
1. **改稿差异分析**（`diff_analysis`，R-156/157）：版本链不区分「这一版是谁改的」，讨论跑完记 `讨论后` 版本时立即触发分析，把 AI 讨论的改动当成「作者的修改」学成人设建议——污染在讨论完成那一刻就发生。
2. **改稿样本 few-shot**（`generation._rewrite_examples`，R-131）：版本链首版→终版当「AI 原稿→作者改后」；回退按 R-157「只覆盖保存、不留痕」，链终点永远停在 `讨论后`，好评后这条错误样本以最高分排最前。
3. 已正确的通道（读草稿当前正文，回退后=原稿）：黄金样本、feedback_context、结构模板、prompt_eval、version_effect（只统计 source=ai）。
4. 「回退=否掉这次讨论」这一强负向信号被完全丢弃。

## 反问与确认结论（2026-09-29）
1. **回退是否留痕**：**留痕**（推翻 R-157「只覆盖保存、不留痕」的决定）——回退记一条 `source="rollback"` 版本，note 写「回退到版本 #N」。
2. **「回退讨论结果」是否记隐式负反馈**：**本期一起做**——回填讨论运行头 `reverted: true` + 生成上下文注入反面信号。
3. **历史污染数据**：作者自己去人设页检查 suggested 标签（不写工具）。
4. **验收**：手写稿→定稿→讨论→回退→好评全链路，版本链终点、人设建议、生成上下文三处归因正确。
5. **成本**：无新增 API 成本；差异分析触发时机不变。

## 做法
- 版本 source 约定：**作者侧** = `{manual, rollback}`；**AI 侧** = `{ai_generate, ai_discuss, ai_rewrite}`。
- `draft_versions.chains_with_sources()` 返回 `[(source, script)]`；`chains_for_drafts()` 派生保持旧签名。
- `diff_analysis`：终版非作者侧 → 跳过；prompt 按 source 标注每版身份（AI 版间改动 ≠ 作者偏好；回退 AI 版 = 否定该方向）；链中无 AI 侧版本也跳过（R-210）。
- `_rewrite_examples`：配对 = 「最后一个作者侧版本 ← 其前一版」。
- 回退跨过 AI 侧版本时：回填该稿最近讨论运行头（`draft_discussions kind='run'`）content JSON `reverted: true`；版本链检测「AI 版 → 之后作者版与更早版同文」（=回退）注入「作者讨论后又改回了自己的原稿——避开这种改法」（≤3 条）。

## 排期
M203

## 验收
- [x] verify.sh 全绿（后端 470+ 例、前端 vitest 59 例、文档一致 31 表/145 路由）
- [x] 回退留一版（source=rollback，版本列表可见）——真实接口冒烟：草稿 52 回退后版本链 `manual → manual → rollback(回退到版本 #21)`
- [x] 终版为 AI 侧时差异分析不跑；回退后差异分析/改稿样本学到的是「讨论稿→原稿」而非反过来（`test_analyzable_rules` / `test_rewrite_examples_pair_is_discussed_to_reverted`）
- [x] 跨 AI 版回退时运行头 `reverted: true`，生成上下文有反面信号（`_reverted_lessons`）
