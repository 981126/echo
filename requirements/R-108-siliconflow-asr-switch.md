# R-108-SILICONFLOW-ASR-SWITCH: ASR 接入硅基流动，.env 可切换阿里云/硅基流动

- **日期**: 2026-09-07
- **提出渠道**: 对话
- **原文摘要**: ASR 接入硅基流动 API；添加开关可切换使用阿里云或硅基流动。
- **状态**: ✅ 已完成（2026-09-07 二次切换为免费模型 SenseVoiceSmall，真实出稿验证通过）
- **排期**: M91（已完成）
- **关联**: config.py（asr_mode 白名单）、services/transcription.py、services/aliyun_filetrans.py、services/ingest.import_video_task（统一转写入口）、.env / .env.example；与 R-068（模式护栏：非法配置启动报错）、R-094（转写失败可读原因+通知）、R-032/R-033（阿里云 ASR 真实接入）相关。

## 反问与确认结论（2026-09-07，作者逐项回复）
1. **提供商选择方式**：在 `.env` 配置使用哪家（`ECHO_ASR_MODE` 扩为 `mock|aliyun|siliconflow`），**不做页面开关**。
2. **模型**：使用 `Qwen/Qwen3-ASR-1.7B`。已用作者真实视频前 12 秒实测该模型在 `POST /v1/audio/transcriptions` 可用，返回 JSON `{text, usage:{type:duration,seconds}, language}`，转写质量正常。
3. **不加「来源服务」记录列**：不改表结构。
4. **超限处理**：超过单文件限制（50MB / ≤1 小时）时给出明确提示并通过现有失败通知推给作者，**不自动切换到其它服务商**。
5. **接口范围**：只接 `POST /v1/audio/transcriptions`（音视频直接上传转写）。作者给的第二个链接 `POST /uploads/audio/voice` 经查是 **CosyVoice 音色克隆上传（语音合成/TTS 用）**，与「视频转文字」无关，本次不接。

## 实施与自测（2026-09-07）
1. config：`ECHO_ASR_MODE` 合法值扩为 `mock|aliyun|siliconflow`（R-068 白名单护栏不变）；新增 `ECHO_SILICONFLOW_API_KEY/BASE_URL/ASR_MODEL`（默认 `Qwen/Qwen3-ASR-1.7B`）。
2. 新增 `services/siliconflow_asr.py`：`POST {base}/audio/transcriptions` 直传转写（multipart file+model，无需 OSS 中转）；视频先抽 16k 单声道 wav（复用 media_tools）、纯音频直传；平台限制单文件 ≤50MB / ≤1 小时（新增 `media_tools.probe_duration_seconds`），超限明确报错走现有失败通知、**不自动切换其它服务商**。
3. `transcription.py` 路由增加 siliconflow；所有转写入口（手动/每日同步/对标补齐均经 `import_video_task`）随 `.env` 切换生效（改后重启）。Key 只写本地 `.env`（gitignored），`.env.example` 仅占位模板。
4. 质量门禁：ruff + mypy + pytest（97 项，新增 `test_siliconflow_asr.py` 8 项）+ 前端 lint/build 全绿。
5. 真实冒烟：视频 79 走 `/api/videos/79/transcribe` → 后台任务 → 硅基流动 `POST /v1/audio/transcriptions`，请求**真实到达平台**并返回明确错误 `HTTP 402 account balance insufficient`（路由/请求/失败通知链路真实打通）。此前同日用同 key 对作者视频前 12 秒实测该模型可正常出稿。冒烟失败产物已清理，视频 79 恢复原始状态。
6. **待作者处理（两个外部账户问题）**：
   - 硅基流动账户当前**余额不足**（HTTP 402），充值前真实转写会失败并走通知；当前 `.env` 已设 `ECHO_ASR_MODE=siliconflow`，充值后即可直接出稿。
   - 排查中发现阿里云 OSS 返回 `UserDisable`（RAM 用户被禁用/欠费）——阿里云真实转写当前同样不可用，这可能是本次转硅基流动的动因，需在阿里云侧确认账号状态。

## 原文（作者原话，未改动；API Key 打码）
> 新需求
> 1.ASR接入硅基流动api，添加开关可以切换使用阿里云或者硅基流动
>
> 接口文档：
> https://api-docs.siliconflow.cn/docs/api/audio-transcriptions-post
> https://api-docs.siliconflow.cn/docs/api/uploads-audio-voice-post
>
> apikey：sk-gno……（打码：明文已收到，仅写入本地 .env（gitignored）。项目硬性规则：密钥不落代码/文档/commit；如该 key 曾外泄建议在硅基流动后台轮换）

## 变更（2026-09-07 二次）：模型换免费 SenseVoiceSmall
- 作者要求「硅基流动切换到免费的 ASR 模型」：默认模型由 `Qwen/Qwen3-ASR-1.7B` 改为 **`FunAudioLLM/SenseVoiceSmall`**（硅基流动免费，实测真实出稿，不再报 402 余额不足）；config 默认 + `.env`/`.env.example` 同步。
- 顺带清理 SenseVoice 输出的事件标记（🎼、情绪表情、`<|...|>` 标签）后再入库，转写稿更干净。
