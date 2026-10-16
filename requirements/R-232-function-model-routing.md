# R-232-FUNCTION-MODEL-ROUTING: AI 设置里按功能选模型（功能级模型路由下拉）

- **日期**: 2026-10-16
- **提出渠道**: 对话
- **原文摘要**: 在 AI 设置里分不清楚「AI 对话」「生成脚本」「视频预打标」「人设」等等各功能用的什么模型，需要在旁边放一个下拉框让自己可以选模型。
- **状态**: ✅ 已完成（`feat(R-232)`：`model_settings.FEATURE_GROUPS/feature_route/save_feature_routes`（app_kv `feature_route_<组>`，默认全 model1、prompt_opt 默认 gen=跟随生成方）；`llm_router.primary_llm` 缺省按功能路由解析；`persona.llm_for` 接入（4 引擎同组）；`prompt_service._optimize_llm` 改走路由（R-229 语义保持）；GET/PUT /api/settings/models 带 feature_routes（选项标签内嵌槽位实际模型名）；设置页「模型槽位」卡内新增「功能路由」区 10 组下拉；`test_r232_function_model_routing.py` 10 用例；API.md 同步）
- **排期**: M233
- **关联**: `backend/app/services/llm_router.py`、`model_settings.py`、`api/settings.py`、前端 AI 设置页、R-023/R-138/R-139/R-178/R-229

## 背景与根因

除「脚本生成」（生成方/评审方两个下拉，R-138）外，**所有其他功能**——AI 对话、人设引擎（提取/合并/增量/对齐）、视频预打标、转写校对、差异分析、提示词优化、金样本评测、对标分析、反馈学习、标题封面标签、灵感——全部走 `llm_router.primary_llm(db, feature)`，硬编码「模型1 主用 → 模型2 兜底」。界面上看不到各功能实际用哪个模型，也改不了；R-229 把提示词优化改成跟随生成方，但界面同样无表达。

## 作者确认的边界（反问已确认）

1. **下拉选项 = 模型1 / 模型2 槽位**（复用已配置的两个槽位；厂家/型号/Key 仍在原槽位配置区改）。
2. **选中槽位失败时自动兜底另一槽位**（复用现有 RoutedLLM 降级机制 + 降级通知，不让功能挂掉）。
3. **覆盖全部非生成功能**，人设 4 个引擎合并成一个选项：
   - AI 对话（chat）
   - 人设引擎（persona_init / persona_merge / persona_updates / persona_compare，4 合 1）
   - 视频预打标（video_tags）
   - 转写校对（correct）
   - 差异分析（diff）
   - 提示词优化与金样本评测（prompt_optimize / prompt_eval，2 合 1）
   - 对标分析（benchmark）
   - 反馈学习（feedback_analysis）
   - 标题封面标签（draft_meta）
   - 灵感与其他（ideas / misc）
4. **默认值**：全部默认模型1（=现状不变）；唯一例外「提示词优化与评测」默认「跟随生成方」（保 R-229 语义），其下拉多一个「跟随生成方」选项。
5. 「脚本生成」的生成方/评审方下拉不动。

## 实施

- `model_settings`：新增 `feature_route(db, feature) -> str`（读 `app_kv` 的 `feature_route_<feature>`，默认 model1；prompt_optimize/prompt_eval 支持 `gen` = 跟随生成方）；`save_feature_routes(db, routes)` 校验槽位名非法 400。
- `llm_router.primary_llm`：`primary` 缺省时按 `feature_route` 解析（传 db 时）；保底 model1。
- `persona.py` 的 `llm_for`（4 个引擎）走同一解析；`debate.py` 的 `_side_llm` 不动（生成方/评审方逻辑独立）。
- API：`GET/PUT /api/settings/models` 增 `feature_routes` 字段（GET 返回各功能当前主用槽位 + 实际模型名展示串；PUT 接收并校验）。
- 前端：AI 设置 → 模型设置 增加「功能路由」区——每行：功能名 + 当前模型展示（厂家 · 型号，R-178 口径）+ 下拉（模型1/模型2，提示词优化组多「跟随生成方」）；保存随现有「保存模型设置」一起走。
- 测试：路由解析默认值/覆盖值/gen 跟随；save 校验非法槽位 400；persona 4 引擎同路由；API GET/PUT 往返；`verify.sh` 全绿。
- 文档：改 `docs/API.md`（/models 结构）。

## 验收

- AI 设置里每个功能旁能看到当前实际模型名，下拉切换保存后立即生效（下一个调用即用新槽位，失败自动兜底并通知）。
- 默认值下所有行为与现状完全一致（全默认模型1、提示词优化跟随生成方）。
- `scripts/verify.sh` 全绿；服务保持运行。

## 明确不做

- 不做按功能自由填厂家/型号/Key（只选槽位）；不改脚本生成的生成方/评审方交互；不做「严格模式」（失败不兜底）；ASR 不在本次（走独立 ASR 配置）。

## 原文（作者原话，未改动）

> 有个问题 在ai设置里面，我现在分不清楚【ai对话】【生成脚本】【视频预打标】【人设】等等用的什么模型生成的需要在旁边放一个下拉框让我可以自己选模型
