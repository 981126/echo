# R-032-ALIYUN-ASR-LIVE: 阿里云 ASR 真实接入（录音文件识别联调）

- **日期**: 2026-09-05
- **提出渠道**: 对话
- **原文摘要**: 作者在「阿里云 ASR 与把语音文件直接给大模型解析哪个更便宜」之间比较后选择接入阿里云，提供 ISI AppKey 与阿里云 AccessKey/Secret，要求把视频语音转文字真实跑通（现有 `asr_mode=aliyun` 为占位实现，从未真实联调）。
- **状态**: ✅ 已完成（2026-09-05 E2E 实调通过）
- **排期**: M14（已完成）
- **关联**: PRD §3.1/§3.2、M1、D-004；代码 `backend/app/services/aliyun_filetrans.py` + `core/signature.py`

## 反问与确认（2026-09-05）
1. **接口选型**：作者提供的是「智能语音交互(ISI)」AppKey，对应 **录音文件识别 FileTrans POP API（4.0 版）**；该接口鉴权需要阿里云 AccessKey 签名（HMAC-SHA1），AppKey 只是服务项目标识 —— 已向作者说明，作者已提供 AccessKey/Secret
2. **硬约束（已从官方文档确认）**：FileTrans **不支持提交本地文件**，`file_link` 必须是公网可访问 URL（官方推荐阿里云 OSS，同地域内网访问不计外网流量）
3. **已确认（方案 A）**：作者提供 OSS bucket `981126981126`（oss-cn-shanghai）；实现为「OSS 上传→预签名 URL→SubmitTask→轮询 GetTaskResult→解析 Sentences→删除临时对象」（官方 SDK oss2 + aliyun-python-sdk-core CommonRequest）
4. **实调结论（2026-09-05）**：FileTrans SubmitTask/GetTaskResult 用作者 AK+AppKey（cn-shanghai）对官方示例音频调用成功，返回「北京的天气。」；作者授权 OSS（AliyunOSSFullAccess）后，**端到端全流程实调通过**：OSS 上传（bucket 981126981126/oss-cn-shanghai）→ 预签名 URL → SubmitTask → 轮询 GetTaskResult → 解析回填「北京的天气。」→ 自动删除临时对象（复查无残留）
4. **存量代码**：原手写 HMAC REST 占位弃用，改为官方推荐 CommonRequest RPC POP 方式（对齐阿里云 Python Demo）；`transcribe_file` 全流程已实现并单测覆盖

## 配置（写入 .env，gitignore 不提交）
- `ECHO_ALIYUN_ASR_ACCESS_KEY_ID` / `ECHO_ALIYUN_ASR_ACCESS_KEY_SECRET` / `ECHO_ALIYUN_ASR_APP_KEY`（作者 2026-09-05 提供）
- `ECHO_ASR_MODE=aliyun`（联调通过后切换；开发/测试仍用 mock）
- OSS 相关（待确认后补）：bucket / region / 签名 URL

## 原文（作者原话，未改动）
> 现在将视频的语音转文字，是通过阿里的api便宜，还是直接将语音文件给大模型解析方便，哪个更便宜
>
> 有没有更便宜的
>
> 接入阿里云，这个是我的appkey
> o5g9****9UF
>
> 我看帮助文档中不需要其他的密钥了
> https://help.aliyun.com/zh/isi/developer-reference/api-reference-2
>
> AccessKey：LTAI5t7****ZHimP
> AccessKey Secret：O91W2s94****ald0W
