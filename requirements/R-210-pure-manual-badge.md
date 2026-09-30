# R-210 纯手写稿标签（卡片标识 + AI 只学正文）

- **日期**: 2026-09-29
- **状态**: ✅ 已完成（M203）
- **关联**: `backend/app/api/drafts.py`、`schemas`、`frontend_v2/src/pages/drafts/`；R-209/R-211

## 原文（作者原话，未改动）
> 还有个小需求，如果我是纯人工手写，也就是这篇草稿没有讨论过，那就给个标签，在卡片右上角标出来，ai只学习正文就行了

## 反问与确认结论（2026-09-29）
1. **标签文案**：「**纯手写**」。
2. **边界**：手写稿讨论过、即使内容已全部回退成自己写的，也**不算**纯手写（AI 参与过；回退行为本身已是 R-209 的学习信号）。
3. **判定**：`draft.source="manual"` 且无 `draft_discussions` 记录 且无 AI 侧版本（`ai_generate/ai_discuss/ai_rewrite`）。列表接口批量判定（无 N+1），`DraftOut` 加 `pure_manual`。
4. **「AI 只学正文」**：黄金样本通道本来就只学当前正文（不变）；`diff_analysis` 对**无 AI 侧版本的版本链跳过**（作者自己改自己的手写稿，不属于「作者把 AI 稿改成什么」的学习范畴，符合 R-156 原始意图）。
5. **位置**：卡片标题行右侧 Badge（继承卡片入场动画，无额外动效）。

## 排期
M203

## 验收
- [x] 纯手写稿卡片显示「纯手写」标；讨论过/AI 生成过的不显示（真实接口冒烟：草稿 52 `pure_manual=true`，插入讨论留痕后 `false`）
- [x] 纯手写稿多次定稿不触发差异分析（`test_finalize_pure_manual_never_triggers_diff`）
- [x] 好评/完成后纯手写稿正文仍进黄金样本（status=done 即进 `feedback_context` 认可块，冒烟验证）
