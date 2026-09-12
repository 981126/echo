# R-138 「AI 提示词」菜单改名「AI 设置」+ 新增模型设置 tab（主/副/ASR，实时生效）

- **日期**: 2026-09-11
- **状态**: 已确认（待作者说「继续」后实施）
- **排期**: M127
- **关联**: R-023（生成模型策略）、R-108（ASR 服务商）、R-135（生成模型策略生效）、`api/settings.py`、`services/debate.py`、`services/transcription.py`、`PromptsView.vue`

## 原文（作者原话，未改动）
> 1.ai提示词 菜单 改为 ai设置，里面其他功能不改
> 2.ai设置第一个tab页可以让我配置项目中的主模型、副模型、asr模型
> 3.应用后实时生效

## 澄清与确认结论（2026-09-11，作者逐项选择）
1. **主/副模型语义**：**主模型 = 生成写稿**（`generate_draft` / 讨论的生成方）；**副模型 = 评审讨论**（讨论的评审方）。对应现有 `debate` 的生成方/评审方。
2. **旧策略**：**保留随机/轮流**，作为同一 tab 内的「策略」选项（固定主副 / 随机 / 轮流），默认「固定主副」。
3. **ASR 配置粒度**：**服务商 + 模型名**（阿里云 / 硅基流动 / 模拟；模型名仅硅基流动需要）；切换时**校验对应密钥是否存在**，缺失则拒绝保存并提示。
4. **原工具栏**：提示词页顶部原有「生成模型策略」下拉**迁入新 tab**，工具栏只保留「讨论轮次」。
5. **实时生效**：保存即生效，无需重启。

## 范围
- 菜单与页面标题「AI 提示词」→「**AI 设置**」（**路由保持 `/prompts`**，避免打断通知深链 `/prompts?key=xxx`；内部原有功能与布局不变）。
- `PromptsView` 新增**第一个 tab「模型设置」**：策略（固定主副/随机/轮流）、主模型、副模型、ASR 服务商、ASR 模型 + 保存。
- 存储走 `app_kv`（运行时配置，无需迁移）：`model_strategy` / `model_primary` / `model_secondary` / `asr_mode` / `asr_model`。
- 解析层新增 `services/model_settings.py`：`resolve_models(db)`（按策略产出生成方/评审方）、`asr_config(db)`（Kv 优先，回退 .env）；
  `debate.choose_models`、`generation._generation_llm`、`prompt_service._optimize_llm` 改为实时读取；`Transcriber` 接受解析后的 mode/model。
- 接口：`GET/PUT /api/settings/models`（含可选项与密钥是否已配）；旧 `generation-model` 接口保留并读写新键（兼容）。
- **兼容旧值**：已有 `generation_model` Kv（deepseek/kimi/random/alternate）自动映射到新键，作者无需重设。

## 不包含
- 不改动提示词各 key 的 tab 与既有功能；不改 ASR 的 mock/real 白名单校验（启动仍校验 .env，防 R-068 静默回退）；
- 不新增第三方模型供应商；不做模型连通性测试（只校验密钥是否配置）。

## 验收标准
1. 菜单与页面标题显示「AI 设置」，路由与原有提示词功能、通知深链均不受影响。
2. 「模型设置」是第一个 tab；可配置策略/主模型/副模型/ASR 服务商/ASR 模型并保存。
3. **实时生效**：保存主模型后，下一次生成/讨论使用新主模型；保存 ASR 后，下一次转写使用新服务商/模型（均无需重启）。
4. 缺密钥时保存被拒绝并给出可读原因；ASR 服务商不在白名单时拒绝。
5. 旧 `generation_model` 值能无感迁移；旧接口仍可用。
6. `scripts/verify.sh` 全绿；接口冒烟；前端点检；服务保持运行。
