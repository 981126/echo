# R-181 参考改写（洗稿）学习链路补齐

- **日期**: 2026-09-28
- **状态**: ✅ 已完成（2026-09-28，M170）
- **关联**: `backend/app/services/benchmark.py`、`backend/app/services/debate.py`、`backend/app/services/generation.py`；R-117/R-118/R-155

## 原文（作者原话，未改动）
> （讨论「洗稿会深度学习人设吗」时确认）洗稿链路只有简化人设、没有样本/范本/画像，补成与生成同源。

## 根因
「按选题生成」走 `generation_user_message`（人设+红线+统计画像+禁词+金句锚点+TF-IDF 样本+结构模板+四维范例+改写范例+对标参考），
而「对标洗稿」`rewrite_script/rewrite_text` 与「草稿基于原文讨论」R-155 只注入 `persona_lines`（标签+红线文字），
缺样本级约束 → 洗稿稿不如生成稿像作者。

## 修复
1. `generation.py` 抽出共享函数 `author_style_context(db, topic="")`，`generation_user_message` 改为复用它（行为不变）。
2. `benchmark.py` 新增 `REWRITE_SYSTEM`（「参考改写」契约：只借选题与信息线索，不复用原文结构/核心比喻/句群，
   必须补作者自己的经历与判断）与 `_rewrite_user(db,title,text)`（作者完整上下文 + 素材）；
   `rewrite_script` / `rewrite_text` 改用它们。
3. `debate.py` 的 R-155 原文改写：`SOURCE_REWRITE_SYSTEM` 同步为「参考改写」契约，
   user 注入 `author_style_context`。

## 验收
- `pytest -k "persona or benchmark or rewrite or debate or generation"` 全绿。
- `scripts/verify.sh` 全绿。

## 排期
M170
