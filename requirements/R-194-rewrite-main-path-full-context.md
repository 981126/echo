# R-194 对标洗稿主链路接完整作者上下文

- **日期**: 2026-09-28
- **状态**: ✅ 已完成（M183）
- **关联**: `services/debate.py`、`services/benchmark.py`；R-118/R-181

## 原文（作者原话，未改动）
> 自动“对标洗稿”主链路仍没用完整作者上下文。…仍写着“保留核心信息与结构”，与“只借选题和信息线索”的新规则冲突。这个必须先补齐。

## 根因
R-181 只修了 `benchmark.rewrite_script/rewrite_text`（单步）与 `debate` R-155 原文讨论；
对标页「按人设洗稿存草稿」实际走的 `debate.run_rewrite_debate`（R-118 双模型多轮）仍用
`persona_lines`（仅标签+红线）+ 自带的「保留核心信息与结构」system，未注入
风格范本/改稿对照/禁用词/结构偏好/风格样本。

## 修复
- `run_rewrite_debate`：改用 `author_style_context(db, source_title)` 全量上下文；
  初稿 system/文案统一为 `benchmark.REWRITE_SYSTEM` + `_rewrite_user`（参考改写契约）；
  `critic_system`/`revise_system` 同步带上完整作者上下文与「不借结构/比喻/句群」规则。

## 验收
- 定向测试断言 `REWRITE_SYSTEM` 不再含「保留核心信息与结构」；`verify.sh` 全绿。

## 排期
M183
