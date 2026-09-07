# R-108-SILICONFLOW-ASR-SWITCH: ASR 接入硅基流动，.env 可切换阿里云/硅基流动

- **日期**: 2026-09-07
- **提出渠道**: 对话
- **原文摘要**: ASR 接入硅基流动 API；添加开关可切换使用阿里云或硅基流动。
- **状态**: 已确认（方案已定，待作者回复「继续」后实施 M91）
- **排期**: M91（待实施）
- **关联**: config.py（asr_mode 白名单）、services/transcription.py、services/aliyun_filetrans.py、services/ingest.import_video_task（统一转写入口）、.env / .env.example；与 R-068（模式护栏：非法配置启动报错）、R-094（转写失败可读原因+通知）、R-032/R-033（阿里云 ASR 真实接入）相关。

## 反问与确认结论（2026-09-07，作者逐项回复）
1. **提供商选择方式**：在 `.env` 配置使用哪家（`ECHO_ASR_MODE` 扩为 `mock|aliyun|siliconflow`），**不做页面开关**。
2. **模型**：使用 `Qwen/Qwen3-ASR-1.7B`。已用作者真实视频前 12 秒实测该模型在 `POST /v1/audio/transcriptions` 可用，返回 JSON `{text, usage:{type:duration,seconds}, language}`，转写质量正常。
3. **不加「来源服务」记录列**：不改表结构。
4. **超限处理**：超过单文件限制（50MB / ≤1 小时）时给出明确提示并通过现有失败通知推给作者，**不自动切换到其它服务商**。
5. **接口范围**：只接 `POST /v1/audio/transcriptions`（音视频直接上传转写）。作者给的第二个链接 `POST /uploads/audio/voice` 经查是 **CosyVoice 音色克隆上传（语音合成/TTS 用）**，与「视频转文字」无关，本次不接。

## 原文（作者原话，未改动；API Key 打码）
> 新需求
> 1.ASR接入硅基流动api，添加开关可以切换使用阿里云或者硅基流动
>
> 接口文档：
> https://api-docs.siliconflow.cn/docs/api/audio-transcriptions-post
> https://api-docs.siliconflow.cn/docs/api/uploads-audio-voice-post
>
> apikey：sk-gno……（打码：明文已收到，仅写入本地 .env（gitignored）。项目硬性规则：密钥不落代码/文档/commit；如该 key 曾外泄建议在硅基流动后台轮换）
