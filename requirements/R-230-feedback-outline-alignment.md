# R-230-FEEDBACK-OUTLINE-ALIGNMENT: 删除稿计入负反馈 + 论点/引用与终稿对齐标注

- **日期**: 2026-10-16
- **提出渠道**: 对话（生成质量诊断后的修复项 3/4）
- **原文摘要**: ①作者处理不满意稿的习惯是**删除**，而反馈回流只把 `status='archived'` 当负例——deleted 的稿不进"避免这种腔调"学习，负例库实际是空的；②`Draft.quality` 里的论点（outlines）/引用来源取的是**初稿**的，双模型讨论 N 轮后正文已完全漂移（draft 128：初稿谈自由职业、终稿谈求职），前端"依据/引用来源"卡片展示与正文对不上的旧论点。
- **状态**: ✅ 已完成（`feat(R-230)`：feedback_context 负例扩为 archived+deleted（纯手写排除沿用，`pure_manual_map` 改为整批一次查询）；`detect_outline_drift` 纯文本检测（claim 4 字滑窗命中终稿）落 quality.outline_drift（普通+洗稿两链路）；EvidencePanel 加 outlineDrift 提示（论点区/来源区各一行），edit-drawer 与洗稿弹窗接入；`test_r230_feedback_outline_alignment.py` 8 用例 + panel vitest 2 用例）
- **排期**: M231
- **关联**: `backend/app/services/prompt_service.py`、`debate.py`、前端草稿抽屉/洗稿弹窗依据展示、R-129/R-209/R-210/R-211/R-227

## 背景与根因

- `feedback_context()`：负例 = `_drafts_by_status("archived")`。作者真实行为是 delete（最近 14 篇 AI 稿 13 篇 deleted/draft），archived 口径下负反馈几乎为零 → 提示词优化"避免腔调"没有锚。
- `run_debate`：`outlines`/`sources` 在初稿产出时落库，此后 N 轮修订可能整体改写论点与引用，但 quality 不再更新 → 前端依据卡片（R-227）失真。

## 作者确认的边界

1. **deleted 的 AI 稿计入负例**（排除纯手写稿——R-210 口径：手写稿被放弃不代表写得差）；archived 口径保留。deleted 的**手动**稿仍排除。
2. 论点漂移不做"终稿重新提炼论点"的额外 LLM 调用（多一次调用、多一次编造风险）；改为**纯文本检测**：初稿各条 claim 的关键词是否仍出现在终稿正文，命不中即标 `outline_drift=true`。
3. 前端在依据卡片上对该标记显示提示（如「论点为讨论前初稿口径，讨论后已调整，以正文为准」），来源列表同步标注为初稿引用。

## 实施

- `prompt_service.feedback_context`：负例查询扩为 `status in ('archived','deleted')`（沿用现有纯手写排除与条数上限）。
- `debate.py`（普通讨论 + 洗稿讨论两条链路）：定稿后做 drift 检测（claim 关键词命中终稿），`quality["outline_drift"]=true/false`；命中判定逻辑抽成纯函数放后端，便于单测。
- 前端：草稿抽屉与洗稿弹窗的依据区读取 `outline_drift`，为 true 时显示提示文案；来源列表标题加「初稿引用」标注。
- 测试：负例含 deleted AI 稿/排除 deleted 手写稿；drift 纯函数单测（命中/漂移/空 outlines）；`verify.sh` 全绿。

## 验收

- 作者删一篇 AI 稿后，下一轮生成的提示词优化语料里出现该稿（负例可见）。
- 讨论后论点漂移的稿，前端依据卡片显示"以正文为准"提示。
- `scripts/verify.sh` 全绿。

## 明确不做

- 不做终稿论点重提炼；不改 outlines/sources 的落库结构（只加 `outline_drift` 布尔字段）；不动 feedback 表结构。

## 原文（诊断原文，作者确认按此修）

> 3. 修反馈口径：deleted 的 AI 稿也进负例；终稿后重新提取 outlines/sources 或至少标注版本漂移。

（实施时与作者确认取"标注漂移"而非"重新提炼"：少一次 LLM 调用、少一次编造风险。）
