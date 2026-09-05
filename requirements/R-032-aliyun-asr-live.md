# R-032-ALIYUN-ASR-LIVE: 阿里云 ASR 真实接入（录音文件识别联调）

- **日期**: 2026-09-05
- **提出渠道**: 对话
- **原文摘要**: 作者在「阿里云 ASR 与把语音文件直接给大模型解析哪个更便宜」之间比较后选择接入阿里云，提供 ISI AppKey 与阿里云 AccessKey/Secret，要求把视频语音转文字真实跑通（现有 `asr_mode=aliyun` 为占位实现，从未真实联调）。
- **状态**: 澄清中（待作者确认文件可访问方式：OSS / 公网 URL）
- **排期**: M14（待确认）
- **关联**: PRD §3.1/§3.2、M1、D-004；代码 `backend/app/services/aliyun_filetrans.py` + `core/signature.py`

## 反问与确认（2026-09-05）
1. **接口选型**：作者提供的是「智能语音交互(ISI)」AppKey，对应 **录音文件识别 FileTrans POP API（4.0 版）**；该接口鉴权需要阿里云 AccessKey 签名（HMAC-SHA1），AppKey 只是服务项目标识 —— 已向作者说明，作者已提供 AccessKey/Secret
2. **硬约束（已从官方文档确认）**：FileTrans **不支持提交本地文件**，`file_link` 必须是公网可访问 URL（官方推荐阿里云 OSS，同地域内网访问不计外网流量）
3. **待作者确认**：账号下是否有 OSS（bucket 名称/地域），或改用其他公网可达方式；无 OSS 则备选方案为百炼(Paraformer) 本地文件直传（需 DashScope API Key，另一类密钥）
4. **存量代码**：`aliyun_filetrans.py` 已实现签名与 submit/get 骨架，`transcribe_file` 是占位抛错，需补齐「上传→提交→轮询→拼接句子」全流程并真实冒烟

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
