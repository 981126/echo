# R-231-PROMPT-VERSION-GUARD: 提示词无启用版兜底 + 生成提示词现状落位

- **日期**: 2026-10-16
- **提出渠道**: 对话（生成质量诊断后的修复项 4/4）
- **原文摘要**: `ai_prompts` 里 generation 提示词 10 个版本（v1~v10）**全部 archived、当前无 enabled 版**——实际跑的是代码默认（`prompt_version=0`）；今天 00:37~00:38 作者在提示词页操作过（v9 手动编辑 → v10 候选，随后都被归档），状态是被操作/自动链路搅乱还是有意清空无法区分。需要：启动兜底（无启用版时自动启用代码默认）+ 把当前生成提示词落到一个明确状态。
- **状态**: ✅ 已完成（`feat(R-231)`：`prompt_service.ensure_enabled_fallback`（无 enabled 的 key 另存启用代码默认，note 留痕，幂等）挂入 `db.py` ensure 链；主库 generation 的兜底在下次后端启动时生效；`test_r231_prompt_version_guard.py` 4 用例）
- **排期**: M232
- **关联**: `backend/app/services/prompt_service.py`、`db.py`（ensure 链）、R-021/R-129/R-183/R-208

## 背景与根因

`get_prompt()` 无 enabled 记录时回退代码默认——功能上能跑，但：①界面显示"无启用版本"，作者无法判断当前生效的是哪一版；②历史 v10 显示 archived 且无候选在评，自动优化链路（R-208 到量自动优化 + 金样本评测自动启用）与手动操作叠加后状态不可解释；③v10 这类丢硬要求的候选若再被自动启用，代码层无任何护栏（`ensure_generation_steering_prompt` 只识别 R-183 之前的旧版特征）。

## 作者确认的边界

1. 启动兜底：任一提示词 key 无 enabled 版时，自动另存一版并启用**代码默认内容**（note 留痕"无启用版本，兜底启用代码默认"），旧状态不删、可回溯。
2. 生成提示词当前落位：兜底启用代码默认（即 R-183 方向盘版 + R-228 禁编造规则）；不恢复任何历史版本（v3~v10 均为 deepseek-flash 自动/手动产物，作者已全部归档 = 不再信任）。
3. 本次不做"候选自动启用"策略调整（金样本评测启用逻辑不动）；R-229 已把优化模型换强，观察后再说。

## 实施

- `prompt_service`：新增 `ensure_enabled_fallback(db)`——遍历 `PROMPT_META`，无 enabled 的 key 走 `save_new_version(key, default_content(key), note="无启用版本，兜底启用代码默认")`。
- `db.py` ensure 链（`ensure_defaults` 同一处）追加调用；启动幂等（已有 enabled 则不动）。
- 主库数据：本次交付时对 generation 执行一次兜底（重启即生效，无需手工 SQL）。
- 测试：构造全 archived 状态的 key → ensure 后存在 enabled 且内容=代码默认；已有 enabled 时不新增版本。

## 验收

- 提示词界面 generation 显示有启用版本（=代码默认）；重启两次版本号不翻倍。
- `scripts/verify.sh` 全绿。

## 明确不做

- 不删除/合并历史版本；不改金样本评测与自动启用逻辑；不动 `ensure_generation_steering_prompt`/`ensure_persona_layer_prompts` 现有升级链。

## 原文（作者原话/诊断原文，未改动）

> 4. 定提示词现状：确认 generation 无 enabled 版是否有意；优化链路（自动优化+自动启用）建议暂停或换强模型执行。

（作者回复"按顺序修"= 确认修复；自动优化模型换强由 R-229 承担，本条只做兜底与落位。）
