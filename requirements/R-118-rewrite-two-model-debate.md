# R-118 洗稿双模型多轮讨论

- **日期**: 2026-09-07
- **状态**: ✅ 已完成
- **排期**: M101（已完成）
- **原文**: 洗稿需要两个 ai 进行多轮次讨论

## 实施
- 新增 `debate.run_rewrite_debate`：洗稿初稿先由生成方按原文改写，再由 评审方/生成方 交替多轮打磨（轮数走 debate_rounds，默认 5，最多 10）。
- 每轮写入 `draft_discussions` 留痕，最终稿落 `drafts`（含 original_script / source_ref）。
- `benchmark_rewrite` 后台任务改走该双模型流程；任一方失败按现有降级策略处理。

## 验收
- 对标页点「洗稿」触发双模型多轮讨论；脚本工作台该草稿的「讨论」tab 能看到每轮评审/修订留痕。
- `scripts/verify.sh` 全绿。
