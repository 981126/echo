# R-137 DeepSeek 模型切换到 DeepSeek-V4.1-Flash

- **日期**: 2026-09-11
- **状态**: ✅ 已完成
- **排期**: M126（已完成）
- **关联**: `backend/app/config.py`、`.env`、`.env.example`、`services/llm.py`、AGENTS/PRD/PRODUCT/DECISIONS

## 原文（作者原话，未改动）
> 将项目中的deepseek换成最新的4.1flash模型

## 澄清与依据（官方来源，2026-09-10 变更日志）
- DeepSeek 官方于 2026-09-10 发布 **DeepSeek-V4.1-Flash**，并明确：**「Change the model name to `deepseek-flash` to call the latest V4.1 Flash model」**。
- `deepseek-v4-flash` / `deepseek-v4-flash-vision-exp` 只是**临时兼容别名**（旧模型已下线，请求被路由到 V4.1 Flash）。
- 第三方名称（如 `deepseek-flash-4.1`）**不是**官方 ID，不能用。
- 顺带发现：项目原先使用的 `deepseek-chat` / `deepseek-reasoner` 属于**已停用的旧模型名**（官方 2026-04-24 公告"三个月后停用"，即 2026-07-24），本次切换同时修掉这个隐患。
- 实测：以 `deepseek-flash` 调用项目现有的 OpenAI 兼容客户端 + JSON 模式（`response_format=json_object`）正常返回 `{"ok": true}`。

## 范围
1. `.env`（运行时，gitignore）：`ECHO_DEEPSEEK_MODEL=deepseek-flash`。
2. `backend/app/config.py` 默认值：`deepseek_model = "deepseek-flash"`（无 .env 时也走新模型）。
3. `.env.example`：同步为 `deepseek-flash`（模板不留旧模型名）。
4. 文档同步：AGENTS.md 技术栈、PRD、PRODUCT、DECISIONS 注明 DeepSeek 模型为 V4.1 Flash（`deepseek-flash`）。
5. **不改**：Kimi 相关配置、`generation_model` 策略（仍默认 Kimi）、base_url、鉴权方式。

## 不包含
- 不更换供应商（仍是 DeepSeek 官方 API）；不引入 V4.1 Flash 的多模态能力（本项目只用文本 + JSON）；
- 不改生成模型策略的默认值（当前 `.env` 为 kimi）。

## 验收标准
1. `.env`/`config.py`/`.env.example` 三处模型名均为 `deepseek-flash`，仓库内不再出现 `deepseek-chat`。
2. 真实调用验证：`deepseek-flash` 在 JSON 模式下返回可解析结构，且较长输出不被截断（无空正文）。
3. 后端启动无配置报错；`scripts/verify.sh` 全绿；服务保持运行。

## 实施记录（2026-09-11）
- `.env`（运行时，gitignore）、`.env.example`、`backend/app/config.py` 默认值三处模型名统一为 **`deepseek-flash`**；仓库内已无 `deepseek-chat` 残留。
- 文档同步：AGENTS.md 技术栈、PRD 生成模型说明、PRODUCT、DECISIONS 均注明 DeepSeek 侧为 V4.1 Flash（`deepseek-flash`）。
- **真实调用验证**（共 3 次）：
  1. JSON 模式冒烟：`{"ok": true}` 正常解析；
  2. 长输出：334 字符 JSON、script 286 字，解析通过（确认 V4 的 thinking 模式未把 token 吃光、无空正文）；
  3. 应用层链路：`correct_transcript('我今年在找工作 面视了三家公司 都拿到offer了')` → 正确输出「面试」（证明 `DeepSeekClient` 已走新模型）。
- 未改动：Kimi 配置、`generation_model` 策略（仍为 kimi）、base_url 与鉴权方式。
