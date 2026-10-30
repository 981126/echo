# R-200 接入腾讯云 ASR（录音文件识别）

- **日期**: 2026-09-29
- **状态**: ✅ 已完成（M189；真实腾讯接口联调已通过）
- **关联**: `backend/app/config.py`、`backend/app/services/tencent_asr.py`、`services/media_tools.py`、`services/transcription.py`、`services/model_settings.py`、`services/ingest.py`、`frontend_v2/src/pages/prompts/index.tsx`、`frontend_v2/src/pages/videos/edit-drawer.tsx`；R-032/R-108/R-113/R-138

## 原文（作者原话，未改动）
> https://cloud.tencent.com/document/product/1093/52554
> 接入腾讯ASR

## 反问与确认结论（2026-09-29）
1. **范围与边界**：新增 `asr_mode=tencent`（录音文件识别），保留原有 `mock|aliyun|siliconflow` 三家；不删不改其它服务商，不换默认。
2. **场景与影响**：编辑页/卡片的「语音转文字」与素材补齐走统一 `Transcriber` 入口，选腾讯后即用腾讯；对现有功能无破坏。
3. **数据**：`transcripts.asr_provider="tencent"`、`asr_model=引擎类型`（如 `16k_zh_en_2.0`）；不新增表/列。
4. **边界与异常**：本地音频 base64 直传上限 5MB；超限明确报错走既有失败通知，**不自动切换其它服务商**（同 R-108 口径）。
5. **验收标准**：`scripts/verify.sh` 全绿 + 腾讯链路离线 mock 单测 + 设置页可选腾讯并保存生效 + 真实联调（需作者密钥）。
6. **成本与性能**：按腾讯计费；只传音频（ffmpeg 抽轨并压缩到 ≤5MB，自适应 16–32kbps），不传视频。
7. **依赖与风险**：新增官方模块化 SDK `tencentcloud-sdk-python-asr`（仅依赖 `tencentcloud-sdk-python-common`，其 `requests` 项目已有）；腾讯挂/欠费 → 失败通知。
8. **优先级**：现在做。
9. **动效（R-175）**：设置页切到腾讯/硅基流动时，引擎下拉以统一动效入场（非 `opacity:0` 起步）。

### 作者拍板
- 音频提交方式：**本地音频 base64 直传**（`SourceType=1`）。
- 识别引擎：**界面可选多个，默认 `16k_zh_en_2.0`（大模型2.0）**。
- SDK：**官方模块化 `tencentcloud-sdk-python-asr`**。
- 密钥：`.env` 存；界面只选服务商；**保留四家、不换默认**。
- 附带：修复「模型 API Key 在设置页保存不进 DB」的既有 bug（前端发 `api_key`，后端只认 `key`）。

## 做法
- 后端：`config.py` 加腾讯配置与白名单；`media_tools.extract_audio_compact`（16k 单声道 mp3，按目标大小自适应比特率）；新增 `tencent_asr.py`（CreateRecTask + DescribeTaskStatus 轮询，结果去时间戳）；`transcription.py` 增 `tencent` 路由；`model_settings` 增引擎列表与校验、mode 感知默认模型；`ingest.py` 为腾讯落 `asr_model`。
- 前端：AI 设置服务商加「腾讯云」，腾讯/硅基流动显示各自引擎下拉，切换时重置默认并带入场动效；编辑页来源显示「腾讯云」；修复 Key 保存字段。
- 文档：ARCHITECTURE/DECISIONS(D-040)/API/CHANGELOG/AGENTS/QUICKSTART/FAQ。

## 排期
M189

## 验收
- [x] `scripts/verify.sh` 全绿（后端 441 例 + 前端 lint/vitest/build + 文档一致性 31 表/145 路由）
- [x] 腾讯链路离线单测（缺密钥/提交参数/抽轨清理/轮询/失败/超时/超限/路由，15 例）
- [x] 设置页选腾讯→引擎下拉→保存（接口冒烟：GET 带 `tencent_models`；PUT 无密钥 400 且不改库；headless 点检：切换后模型默认 `16k_zh_en_2.0`、三引擎可选）
- [x] 真实 ffmpeg 抽/压路径（自适应码率、超限报错、临时文件清理）
- [x] 真实腾讯接口联调出稿：本地合成的 18s 中文口播 mp4 → `TencentAsr(model="16k_zh_en_2.0").transcribe_file` → **16.1s 返回、78 字准确转写**（未改动作者 app_kv 默认，服务商在界面自行切换）
