# R-113 转写来源入库：per-transcript asr_provider

- **日期**: 2026-09-07
- **状态**: ✅ 已完成
- **排期**: M96（已完成）
- **原文**: 除了《聊过很多老板，都说挣钱的核心不在于干什么》之前的视频全部用的阿里云 ASR，这个应该是有字段存在卡片里面数据

## 根因
编辑页「语音转文字」的来源此前按当前全局 `asr_mode` 展示，无法区分每条素材当时实际用哪家 ASR 转写；旧素材（阿里云）在切到硅基流动后会被误标成硅基流动。

## 实施
- `transcripts` 表新增 `asr_provider`（mock|aliyun|siliconflow）；转写任务 `import_video_task` 在成功/失败落库时写入当前 `settings.asr_mode`。
- 幂等迁移回填历史：`created_at < 2026-09-07` → aliyun（阿里云 FileTrans）；`>= 2026-09-07` → siliconflow（09-07 起切硅基流动，阿里云当日已停用）。回填结果：aliyun 233 条 / siliconflow 23 条（含 09-07 当日 Qwen 重转的视频 79 与 256 等）。
- `TranscriptOut` 暴露 `asr_provider`；前端编辑页按每条素材的实际来源显示（有转写稿则用其 asr_provider，无转写稿则显示即将使用的当前模式）。
- 顺带修复 `test_parse_link` 的网络不稳定性：monkeypatch 掉重定向解析，保证离线确定性（有网时 xiaohongshu 跳转导致误判）。

## 验收
- 老素材编辑页显示「阿里云 ASR」，硅基流动转写的（79/256 等）显示「硅基流动 ASR · Qwen/Qwen3-ASR-1.7B」。
- `GET /api/videos/{id}` 返回 transcript.asr_provider。
- `scripts/verify.sh` 全绿。

## 补充（同日）：模型也入库
- `transcripts` 再增 `asr_model`：硅基流动转写时存 `settings.siliconflow_asr_model`；阿里云/模拟未知 → 空。
- 回填：23 条硅基流动历史转写 model=Qwen/Qwen3-ASR-1.7B；阿里云 233 条 model 为空。
- 前端编辑页显示该条素材实际模型（阿里云为空时不显示模型）。
