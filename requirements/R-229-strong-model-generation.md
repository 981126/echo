# R-229-STRONG-MODEL-GENERATION: 生成方换强模型（kimi-k2.6 写初稿）+ 提示词优化不再用弱模型

- **日期**: 2026-10-16
- **提出渠道**: 对话（生成质量诊断后的修复项 2/4）
- **原文摘要**: 当前生成方 = deepseek-flash（廉价快模型）、评审方 = kimi-k2.6（强模型）——强模型只挑刺、弱模型在写字，成稿质量上限被生成方锁死；更糟的是提示词自动优化（R-208 到量自动跑）也是 deepseek-flash 自己做的，v3~v10 候选全是它调的（v10 把"严禁编造/每条论点配事例/证据引用"等硬要求全丢了）。
- **状态**: ✅ 已完成（`feat(R-229)`：`llm_router.primary_llm` 加 `primary` 参数（主用非模型1 时自动换另一槽位兜底）；`prompt_service._optimize_llm` 主用生成方槽位；主库 `app_kv` 已交付对调 gen_role=model2 / referee_role=model1；`test_r229_strong_model_generation.py` 5 用例）
- **排期**: M230
- **关联**: `backend/app/services/model_settings.py`、`llm_router.py`、`prompt_service.py`、R-021/R-129/R-139/R-142/R-208

## 背景与根因

`app_kv` 当前配置：`gen_role=model1(deepseek-flash)`、`referee_role=model2(kimi-k2.6)`、`debate_rounds=3`。生成链路里真正"写字"的是生成方（初稿 + 每轮修订），评审只出文字意见；把弱模型放在生成方 = 质量天花板最低的那一环在产出最终文字。提示词优化 `_optimize_llm` 走 `llm_router.primary_llm(db, "prompt_optimize")`，该入口硬编码"模型1 主用 → 模型2 降级"，即优化器也是 deepseek-flash——弱优化器 + 弱自检，产出候选质量差（v10 证据）。

## 作者确认的边界

1. 生成方/评审方对调：**生成 = kimi-k2.6（model2），评审 = deepseek-flash（model1）**；kimi 失败时按现有降级机制自动换回 deepseek-flash，不新增容错逻辑。
2. 提示词优化（手动 + R-208 自动）改用**生成方槽位**的模型（即对调后的 model2/kimi），不再固定走 model1。
3. 不引入"模型强度评分/自动选强"这类猜测逻辑——就是明确对调 + 优化路由跟随生成方。

## 实施

- 数据：主库 `app_kv` 对调 `gen_role=model2`、`referee_role=model1`（界面「AI 设置」展示随之变化，无需前端改动）。
- 代码：`llm_router.primary_llm` 增加可选 `primary` 参数（透传 `RoutedLLM`，默认不变保持 model1 主用）；`prompt_service._optimize_llm` 改为 `primary_llm(db, "prompt_optimize", primary=<generation_roles 的生成方槽位>)`。
- 测试：断言对调后 `generation_pair()` 返回 (model2, model1)；`prompt_optimize` 路由 primary 为生成方槽位。

## 验收

- 「AI 设置」与新生成稿的 `quality.models` 显示生成方 = kimi-k2.6；真实选题生成一篇质量可感提升。
- `scripts/verify.sh` 全绿。

## 明确不做

- 不改两个槽位的厂家/模型 ID 本身（deepseek-flash 仍保留作评审/降级）；不动预算与轮次默认值。

## 原文（诊断原文，作者确认按此修）

> 2. 换生成方：让 kimi-k2.6 写初稿（或至少生成/评审都换成强模型），deepseek-flash 降去做便宜任务。
