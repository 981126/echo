# API 接口文档（人工维护）

> 来源：FastAPI OpenAPI（`/openapi.json`），**人工维护**；`scripts/check_doc_consistency.py` 会在 `scripts/verify.sh` 中校验路由数量与每条路由是否收录。共 146 个路由。
> 鉴权：除 `/health`、`/openapi.json`、`/docs` 与静态资源外，所有接口需请求头 `X-Access-Token`（值 = `ECHO_ACCESS_TOKEN`）。
> 前端托管：`frontend_v2/dist`（R-164/R-208）挂**根路径 `/`**（非 API 路由，不计入下表）。

## videos

### GET /api/videos

List Videos

**参数**

- `platform`（query）string
- `status`（query）string
- `main_topic`（query）string
- `limit`（query）integer
- `offset`（query）integer
- `x-access-token`（header）string
**返回 200**：application/json → VideoListOut

### POST /api/videos/upload

Upload Video

**参数**

- `x-access-token`（header）string
**请求体**（multipart/form-data，`Body_upload_video_api_videos_upload_post`）

字段：
  - `file` string（必填）

**返回 200**：application/json → VideoOut

### GET /api/videos/{video_id}

Get Video

**参数**

- `video_id`（path）integer，必填
- `x-access-token`（header）string
**返回 200**：application/json → VideoDetailOut

### PATCH /api/videos/{video_id}

Update Video

**参数**

- `video_id`（path）integer，必填
- `x-access-token`（header）string
**请求体**（application/json，`VideoUpdate`）

字段：
  - `title` object
  - `platforms` object
  - `status` object
  - `planned_publish_at` object
  - `published_at` object
  - `is_ad` object
  - `ad_price` object
  - `main_topics` object
  - `tags` object
  - `source_text` object
  - `corrected_text` object

**返回 200**：application/json → VideoOut

### DELETE /api/videos/{video_id}

Delete Video

删除本地素材（逻辑清理：删除记录/转写/指标，解除云端作品绑定，本地视频文件一并删除）。

**参数**

- `video_id`（path）integer，必填
- `x-access-token`（header）string
**返回 200**：application/json → object

### POST /api/videos/{video_id}/confirm-tags

Confirm Tags

**参数**

- `video_id`（path）integer，必填
- `x-access-token`（header）string
**请求体**（application/json，`TagConfirmIn`）

字段：
  - `tags_confirmed` boolean

**返回 200**：application/json → VideoOut

### POST /api/videos/{video_id}/cover

Upload Cover

**参数**

- `video_id`（path）integer，必填
- `x-access-token`（header）string
**请求体**（multipart/form-data，`Body_upload_cover_api_videos__video_id__cover_post`）

字段：
  - `file` string（必填）

**返回 200**：application/json → VideoOut

### DELETE /api/videos/{video_id}/cover

Delete Cover

**参数**

- `video_id`（path）integer，必填
- `x-access-token`（header）string
**返回 200**：application/json → VideoOut

### POST /api/videos/{video_id}/transcribe

Transcribe Video

R-033：手动触发语音转文字（后台任务，完成后右上角提醒并可跳转）。

**参数**

- `video_id`（path）integer，必填
- `x-access-token`（header）string
**返回 200**：application/json → object

### POST /api/videos/{video_id}/video

Attach Video

给已有素材上传/替换本地视频文件（不自动转写）。落盘名：标题-视频。

**参数**

- `video_id`（path）integer，必填
- `x-access-token`（header）string
**请求体**（multipart/form-data，`Body_attach_video_api_videos__video_id__video_post`）

字段：
  - `file` string（必填）

**返回 200**：application/json → VideoOut

### DELETE /api/videos/{video_id}/video

Remove Video File

删除素材的本地视频文件（素材记录保留，回到“未上传视频”）。

**参数**

- `video_id`（path）integer，必填
- `x-access-token`（header）string
**返回 200**：application/json → VideoOut

## persona

### GET /api/persona

List Persona

**参数**

- `status`（query）string
- `x-access-token`（header）string
**返回 200**：application/json → array

### POST /api/persona/auto-confirm-backlog

Auto Confirm Backlog

R-208：按同规则批量处理历史积压的待确认建议（后台任务，非禁区+高置信自动进档）。

**参数**

- `x-access-token`（header）string
**返回 200**：application/json → object

### GET /api/persona/check/latest

Latest Persona Check

返回当前博主最近一次「增量 vs 全量」对齐校验结果（无则 null）。

**参数**

- `x-access-token`（header）string
**返回 200**：application/json → object

### POST /api/persona/confirm-all

Confirm All Suggested

一键把当前博主的全部「待确认建议」标记为已确认。

**参数**

- `x-access-token`（header）string
**返回 200**：application/json → object

### POST /api/persona/reject-all

Reject All Suggested

一键把当前博主的全部「待确认建议」标记为已拒绝（R-123）。

**参数**

- `x-access-token`（header）string
**返回 200**：application/json → object

### POST /api/persona/init

Init Persona

用全部历史转写稿初始化/刷新人设档案（后台任务，建议非广告视频转写完成后调用）。

**参数**

- `x-access-token`（header）string
**返回 200**：application/json → object

### POST /api/persona/rebuild

Rebuild Persona

R-182 方案B：推倒重建人设档案（清空旧档案 → 四层全量重建为待确认建议）。进行中拒绝重复入队。

**参数**

- `x-access-token`（header）string
**返回 200**：application/json → object

### GET /api/persona/phrases/suggest

Suggest Phrases

像我金句库（R-030③）：从高表现素材提取短句候选，供作者一键收为风格锚点。

**参数**

- `limit`（query）integer
- `x-access-token`（header）string
**返回 200**：application/json → object

### POST /api/persona/recheck

Recheck Persona
手动重跑一次增量人设校验（增量 + 全量重算对照），进行中拒绝重复入队（R-128）。

**参数**

- `x-access-token`（header）string
**返回 200**：application/json → object

### GET /api/persona/style

Style Overview

返回自动统计的作者语言习惯 + 当前 AI 腔禁用词清单 + 表现最好的素材节选。

**参数**

- `x-access-token`（header）string
**返回 200**：application/json → object

### PUT /api/persona/style

Save Style Words

保存 AI 腔禁用/少用词（存 [] 表示关闭内置清单）。

**参数**

- `x-access-token`（header）string
**请求体**（application/json）

**返回 200**：application/json → object

### POST /api/persona/tags

Add Manual Tag

**参数**

- `x-access-token`（header）string
**请求体**（application/json，`PersonaTagCreate`）

字段：
  - `label` string（必填）
  - `description` string
  - `category` string
  - `source` string

**返回 200**：application/json → PersonaTagOut

### POST /api/persona/tags/batch-delete

Batch Delete Tags

批量删除人设标签（已确认档案多选删除，R-123）。只删当前博主的标签。

**参数**

- `x-access-token`（header）string
**请求体**（application/json，`BatchDeleteIn`）

字段：
  - `ids` array

**返回 200**：application/json → object

### PATCH /api/persona/tags/{tag_id}

Update Tag

编辑人设标签（标签/描述/类别）。

**参数**

- `tag_id`（path）integer，必填
- `x-access-token`（header）string
**请求体**（application/json，`PersonaTagUpdate`）

字段：
  - `label` string
  - `description` string
  - `category` string

**返回 200**：application/json → PersonaTagOut

### DELETE /api/persona/tags/{tag_id}

Delete Tag

删除人设标签。

**参数**

- `tag_id`（path）integer，必填
- `x-access-token`（header）string
**返回 200**：application/json → object

### POST /api/persona/tags/{tag_id}/decision

Decide Tag

**参数**

- `tag_id`（path）integer，必填
- `x-access-token`（header）string
**请求体**（application/json，`PersonaDecision`）

字段：
  - `status` string（必填）

**返回 200**：application/json → PersonaTagOut

## tasks

### GET /api/tasks

List Tasks

**参数**

- `limit`（query）integer
- `status`（query）string（可选：pending/running/done/failed）
- `kind`（query）string（可选：按任务类型过滤，如 platform_media）
- `x-access-token`（header）string
**返回 200**：application/json → array

### GET /api/tasks/{task_id}

Get Task

**参数**

- `task_id`（path）integer，必填
- `x-access-token`（header）string
**返回 200**：application/json → TaskOut

## drafts

### GET /api/drafts

List Drafts

R-173：每条草稿附带 `debate` 字段（无任务为 `null`）——`{"state","kind","note","actor","phase","round","rounds"}`，
卡片据此显示「讨论/洗稿/回炉/生成中」动画与「上次讨论中断」标记（单次批量查询，无 N+1）。
R-210/R-211：另附 `pure_manual`（纯手写=AI 从未参与，卡片「纯手写」标）与 `feedback_comment`（最新评价文本，记反馈预填）。

**参数**

- `status`（query）string
- `video_id`（query）
- `limit`（query）integer
- `x-access-token`（header）string
**返回 200**：application/json → array

### POST /api/drafts

Create Draft

**参数**

- `x-access-token`（header）string
**请求体**（application/json，`DraftCreate`）

字段：
  - `video_id` object
  - `title` string
  - `cover_text` string
  - `script` string
  - `platform_shells` object
  - `status` string

**返回 200**：application/json → DraftOut

### POST /api/drafts/angles

Suggest Angles

选题→角度→草稿 三级流水（R-030）：给 3 个切入角度，作者点选后直接生成。R-202 起改为**后台任务**（返回 `{task_id}`，角度在 `task.result`）。

**参数**

- `x-access-token`（header）string
**请求体**（application/json，`AnglesIn`）

字段：
  - `topic` string（必填）
  - `platform` string

**返回 200**：application/json → object

### POST /api/drafts/generate

Generate

根据选题生成三件套（标题/封面字/脚本）+ 平台外壳。

**参数**

- `x-access-token`（header）string
**请求体**（application/json，`GenerateIn`）

字段：
  - `topic` string（必填）

**返回 200**：application/json → DraftOut

### POST /api/drafts/generate-async

Generate Async

双模型讨论生成（R-023）：先建占位草稿，后台 初稿→5轮讨论→定稿；完成后通知跳转草稿。

**参数**

- `x-access-token`（header）string
**请求体**（application/json，`GenerateIn`）

字段：
  - `topic` string（必填）

**返回 200**：application/json → object

### GET /api/drafts/publish-links/preview

Publish Links Preview

R-197：列出「已发布草稿 ↔ 作品」的高置信度自动关联候选（标题相似度 ≥ 0.8）。

**参数**

- `x-access-token`（header）string
**返回 200**：application/json → object

### POST /api/drafts/publish-links/apply

Publish Links Apply

R-197：应用自动关联并回填历史表现（写 work_id/video_id/发布信息），可撤销。R-202 起改为**后台任务**（返回 `{task_id}`，结果在 `task.result`）。

**参数**

- `x-access-token`（header）string
**返回 200**：application/json → object

### POST /api/drafts/publish-links/revert

Publish Links Revert

R-197：撤销上一次自动关联（只清它写过的草稿）。

**参数**

- `x-access-token`（header）string
**返回 200**：application/json → object

### GET /api/drafts/{draft_id}

Get Draft
**参数**

- `draft_id`（path）integer，必填
- `x-access-token`（header）string
**返回 200**：application/json → DraftOut

### PATCH /api/drafts/{draft_id}

Update Draft

R-211：`status` 进入 `done`（完成=认可）或 `archived`（不采用=否定，纯手写稿豁免）时，异步触发「反馈学习分析」
（`feedback_analysis` 后台任务：LLM 分析正文+版本链+评价文本为什么好/差，心得落 `feedback.insight` 注入生成上下文）；
卡片状态条显示「学习分析中」（`debate.kind="feedback"`），不阻塞返回。

**参数**

- `draft_id`（path）integer，必填
- `x-access-token`（header）string
**请求体**（application/json，`DraftUpdate`）

字段：
  - `video_id` object
  - `title` object
  - `cover_text` object
  - `script` object
  - `platform_shells` object
  - `status` object

**返回 200**：application/json → DraftOut

### GET /api/drafts/{draft_id}/check

Draft Check

脚本体检（R-030⑦）：红线/钩子/结尾引导/篇幅。

**参数**

- `draft_id`（path）integer，必填
- `x-access-token`（header）string
**返回 200**：application/json → object

### POST /api/drafts/{draft_id}/discuss

Draft Discuss

R-155：基于原文（洗稿稿＝洗稿素材 ASR 文案 `original_script` / 自建稿＝当前正文）跑双模型多轮讨论；完成后更新 正文+标题+封面字+标签（合并去重）并写回 `original_script` 供【原文对照】，留痕追加不清空。无可讨论原文 → 400；草稿不存在 → 404。

**参数**

- `draft_id`（path）integer，必填
- `x-access-token`（header）string
**返回 200**：application/json → object

### GET /api/drafts/{draft_id}/discussions

List Discussions

脚本讨论留痕（R-023）：按轮次返回聊天式消息。

R-178：每条附**实际出结果**的模型——`used_slot` / `vendor` / `model_id` 与展示用 `model_label`（如 `DeepSeek · deepseek-flash`）；
历史行（R-178 之前）这三项为空，前端显示「未记录模型（历史）」。`kind='run'` 是某次讨论的运行头（`content` 为 JSON：
`{gen:{slot,vendor,model,label}, critic:{...}, rounds, rounds_done, degraded}`）。

**参数**

- `draft_id`（path）integer，必填
- `x-access-token`（header）string
**返回 200**：application/json → array

### POST /api/drafts/{draft_id}/feedback

Feedback

R-211：活用法是「记反馈」文本评价（`comment`）；`liked/rating/四维分` 字段保留兼容但已弃用（不再参与学习）。学习由状态流转触发（PATCH 进 done/archived）。

**参数**

- `draft_id`（path）integer，必填
- `x-access-token`（header）string
**请求体**（application/json，`FeedbackIn`）

字段：
  - `liked` object
  - `rating` object
  - `comment` string
  - `hook_score` object
  - `pace_score` object
  - `ending_score` object
  - `style_score` object

**返回 200**：application/json → object

### POST /api/drafts/{draft_id}/finalize

Draft Finalize

R-156：定稿——先保存当前编辑，再记一条版本（正文+标题+封面字+标签），并异步按版本链分析改稿偏好。内容全空 → 400；草稿不存在 → 404。

**参数**

- `draft_id`（path）integer，必填
- `x-access-token`（header）string
**请求体**（application/json，`FinalizeIn`）：`title` / `cover_text` / `script` / `tags` / `video_id`
**返回 200**：application/json → object（含 `version`）

### POST /api/drafts/{draft_id}/rework

Draft Rework

一键回炉（R-030⑦）：按原选题重新异步生成一轮，完成后替换草稿。

**参数**

- `draft_id`（path）integer，必填
- `x-access-token`（header）string
**返回 200**：application/json → object

### GET /api/drafts/{draft_id}/performance

Draft Performance

R-184：已发布稿件的表现（绑定素材存在时返回各平台最新互动聚合）；未关联素材或未同步时 platforms=[]。

**参数**

- `draft_id`（path）integer，必填
- `x-access-token`（header）string
**返回 200**：application/json → object

### GET /api/drafts/{draft_id}/versions

Draft Versions

R-156：草稿的定稿版本留痕（时间正序，含正文，供前端本地做两版 diff）。

**参数**

- `draft_id`（path）integer，必填
- `x-access-token`（header）string
**返回 200**：application/json → array

### POST /api/drafts/{draft_id}/versions/{version_id}/rollback

Draft Version Rollback

R-209（推翻 R-157 不留痕）：回滚到此版本——把该版本快照（正文/标题/封面字/标签）覆盖写回当前草稿并保存，**留一版 `source="rollback"`**（note「回退到版本 #N」，版本链终点反映真实内容，供学习正确归因）；若回退跨过了 AI 侧版本（=否定 AI 产出），最近讨论运行头回填 `reverted: true`。草稿或版本不存在 → 404。

**参数**

- `draft_id`（path）integer，必填
- `version_id`（path）integer，必填
- `x-access-token`（header）string
**返回 200**：application/json → object

## chat

### POST /api/chat

Chat

非流式问答（兼容旧调用）。

**参数**

- `x-access-token`（header）string
**请求体**（application/json，`ChatIn`）

字段：
  - `message` string（必填）

**返回 200**：application/json → ChatOut

### GET /api/chat/conversations

List Conversations

**参数**

- `x-access-token`（header）string
**返回 200**：application/json → array

### POST /api/chat/conversations

Create Conversation

**参数**

- `x-access-token`（header）string
**请求体**（application/json，`ConversationCreate`）

字段：
  - `title` string

**返回 200**：application/json → ConversationOut

### PATCH /api/chat/conversations/{conv_id}

Rename Conversation

**参数**

- `conv_id`（path）integer，必填
- `x-access-token`（header）string
**请求体**（application/json，`ConversationUpdate`）

字段：
  - `title` string（必填）

**返回 200**：application/json → ConversationOut

### DELETE /api/chat/conversations/{conv_id}

Delete Conversation

**参数**

- `conv_id`（path）integer，必填
- `x-access-token`（header）string
**返回 200**：application/json → object

### GET /api/chat/history

Chat History

**参数**

- `conversation_id`（query）
- `limit`（query）integer
- `x-access-token`（header）string
**返回 200**：application/json → array

### GET /api/chat/actions

List Agent Actions

列出 AI 对话的写操作提案（R-147 P2）；前端刷新后据此渲染「待确认」卡片。

**参数**

- `conversation_id`（query）integer，可选
- `status`（query）string，可选（`pending` / `cancelled` / `done` / `failed`）
- `x-access-token`（header）string
**返回 200**：application/json → array

### POST /api/chat/actions/{action_id}/confirm

Confirm Agent Action

**作者确认后**才真正执行写操作（生成草稿 / 回炉 / 改草稿状态）；先前的写工具只登记提案，不会直接执行。

**参数**

- `action_id`（path）integer，必填
- `x-access-token`（header）string
**返回 200**：application/json → object

### POST /api/chat/actions/{action_id}/cancel

Cancel Agent Action

取消待确认的写操作：**不动任何数据**。

**参数**

- `action_id`（path）integer，必填
- `x-access-token`（header）string
**返回 200**：application/json → object

### POST /api/chat/stream

Chat Stream

SSE 流式问答：先按非流式求解（含工具调用），再逐段下发结果（打字机式流式）。

**参数**

- `x-access-token`（header）string
**请求体**（application/json，`ChatStreamIn`）

字段：
  - `conversation_id` object
  - `message` string（必填）

**返回 200**：application/json → object

## requirements

## topics

### GET /api/topics

List Candidates

**参数**

- `date`（query）string
- `x-access-token`（header）string
**返回 200**：application/json → object

### GET /api/topics/gaps

Topic Gaps

R-030⑥ 话题缺口：最近 N 天已发布内容的话题覆盖 + 评论区在问的相关问题数。

**参数**

- `days`（query）integer
- `x-access-token`（header）string
**返回 200**：application/json → object

### GET /api/topics/hot

List Hot

**参数**

- `date`（query）string
- `x-access-token`（header）string
**返回 200**：application/json → object

### POST /api/topics/refresh

Refresh Hot

立即抓取今日热点（真实模式需 NAS 有外网）。R-202 起改为**后台任务**（返回 `{task_id}`，结果在 `task.result`）。

**参数**

- `x-access-token`（header）string
**返回 200**：application/json → object

## pipeline

### POST /api/pipeline/run

Trigger Pipeline

**参数**

- `x-access-token`（header）string
**请求体**（application/json，`RunIn`）

字段：
  - `force` boolean

**返回 200**：application/json → object

### GET /api/pipeline/status

Pipeline Status

**参数**

- `x-access-token`（header）string
**返回 200**：application/json → object



## uploads

### POST /api/uploads/image

Upload Image

**参数**

- `x-access-token`（header）string
**请求体**（multipart/form-data，`Body_upload_image_api_uploads_image_post`）

字段：
  - `file` string（必填）

**返回 200**：application/json → object

## notifications

### GET /api/notifications

List Notifications

**参数**

- `limit`（query）integer
- `x-access-token`（header）string
**返回 200**：application/json → array

### POST /api/notifications/clear

Clear Notifications

**参数**

- `x-access-token`（header）string
**返回 200**：application/json → object

### POST /api/notifications/read

Mark Read

**参数**

- `x-access-token`（header）string
**请求体**（application/json，`NotificationReadIn`）

字段：
  - `ids` object

**返回 200**：application/json → object

### GET /api/notifications/unread-count

Unread Count

**参数**

- `x-access-token`（header）string
**返回 200**：application/json → object

## prompts

### GET /api/prompts/keys

List Keys

每个功能：当前启用版本 + 候选 + 最近一次评测 + 版本效果对比（R-129）。

**参数**

- `x-access-token`（header）string
**返回 200**：application/json → array

### POST /api/prompts/optimize-rules

Optimize Rule Keys

一键为规则型提示词（预打标/校对/改稿差异/复盘）产出候选（R-131；自动触发已取消）。

**参数**

- `x-access-token`（header）string
**返回 200**：application/json → object

### POST /api/prompts/{key}/candidates/{version}/reject

Reject Candidate

拒绝候选（R-129 M116）：留痕为 rejected，不再占用「待启用」入口。

**参数**

- `key`（path）string，必填
- `version`（path）integer，必填
- `x-access-token`（header）string
**返回 200**：application/json → object

### POST /api/prompts/{key}/enable

Enable Prompt

**参数**

- `key`（path）string，必填
- `x-access-token`（header）string
**请求体**（application/json，`PromptEnableIn`）

字段：
  - `version` integer（必填）

**返回 200**：application/json → object

### POST /api/prompts/{key}/eval/rerun

Rerun Eval

重跑某候选版的金样本回放评分（R-129 M115）。

**参数**

- `key`（path）string，必填
- `x-access-token`（header）string
**请求体**（application/json，`PromptEnableIn`）

字段：
  - `version` integer（必填）

**返回 200**：application/json → object

### POST /api/prompts/{key}/optimize

Optimize Prompt

R-202 起改为**后台任务**（返回 `{task_id}`；失败原因在 `task.error`，前端任务态提示）。

**参数**

- `key`（path）string，必填
- `x-access-token`（header）string
**请求体**（application/json，`PromptOptimizeIn`）

字段：
  - `material` string

**返回 200**：application/json → object

### POST /api/prompts/{key}/save

Save Prompt

**参数**

- `key`（path）string，必填
- `x-access-token`（header）string
**请求体**（application/json，`PromptSaveIn`）

字段：
  - `content` string（必填）

**返回 200**：application/json → object

### GET /api/prompts/{key}/versions

List Versions

**参数**

- `key`（path）string，必填
- `x-access-token`（header）string
**返回 200**：application/json → array

## settings

### GET /api/settings/debate-rounds

Get Rounds

**参数**

- `x-access-token`（header）string
**返回 200**：application/json → object

### PUT /api/settings/debate-rounds

Set Rounds

**参数**

- `x-access-token`（header）string
**请求体**（application/json，`RoundsIn`）

字段：
  - `rounds` integer

**返回 200**：application/json → object

### GET /api/settings/generation-model

Get Mode

**参数**

- `x-access-token`（header）string
**返回 200**：application/json → object

### PUT /api/settings/generation-model

Set Mode

**参数**

- `x-access-token`（header）string
**请求体**（application/json，`ModeIn`）

字段：
  - `mode` string（必填）

**返回 200**：application/json → object

## creators

### GET /api/creators

List Creators

**参数**

- `x-access-token`（header）string
**返回 200**：application/json → array

### POST /api/creators

Create Creator

**参数**

- `x-access-token`（header）string
**请求体**（application/json，`CreatorIn`）

字段：
  - `kind` string
  - `parent_id` object
  - `name` string
  - `note` string

**返回 200**：application/json → CreatorOut

### PATCH /api/creators/accounts/{account_id}

Update Account

**参数**

- `account_id`（path）integer，必填
- `x-access-token`（header）string
**请求体**（application/json，`AccountIn`）

字段：
  - `platform` string（必填）
  - `nickname` string
  - `home_link` string
  - `platform_user_id` string
  - `extra_config` object
  - `enabled` boolean
  - `sync_frequency` string

**返回 200**：application/json → AccountOut

### DELETE /api/creators/accounts/{account_id}

Remove Account

**参数**

- `account_id`（path）integer，必填
- `x-access-token`（header）string
**返回 200**：application/json → object

### POST /api/creators/accounts/{account_id}/enabled

Set Account Enabled

R-101：启用/禁用账号——禁用后不再自动同步，素材库/对标隐藏该账号数据。

**参数**

- `account_id`（path）integer，必填
- `x-access-token`（header）string
**请求体**（application/json，`AccountEnabledIn`）

字段：
  - `enabled` boolean（必填）

**返回 200**：application/json → AccountOut

### POST /api/creators/accounts/{account_id}/avatar

Upload Account Avatar

手动上传账号头像（jpg/png，存 covers/，之后自动同步不再覆盖）。

**参数**

- `account_id`（path）integer，必填
- `x-access-token`（header）string
**请求体**（multipart/form-data，`Body_upload_account_avatar_api_creators_accounts__account_id__avatar_post`）

字段：
  - `file` string（必填）

**返回 200**：application/json → object

### GET /api/creators/current

Get Current

**参数**

- `x-access-token`（header）string
**返回 200**：application/json → object

### PATCH /api/creators/{creator_id}

Update Creator

**参数**

- `creator_id`（path）integer，必填
- `x-access-token`（header）string
**请求体**（application/json，`CreatorIn`）

字段：
  - `kind` string
  - `parent_id` object
  - `name` string
  - `note` string

**返回 200**：application/json → CreatorOut

### DELETE /api/creators/{creator_id}

Remove Creator

**参数**

- `creator_id`（path）integer，必填
- `x-access-token`（header）string
**返回 200**：application/json → object

### GET /api/creators/{creator_id}/accounts

List Accounts

**参数**

- `creator_id`（path）integer，必填
- `x-access-token`（header）string
**返回 200**：application/json → array

### POST /api/creators/{creator_id}/accounts

Create Account

**参数**

- `creator_id`（path）integer，必填
- `x-access-token`（header）string
**请求体**（application/json，`AccountIn`）

字段：
  - `platform` string（必填）
  - `nickname` string
  - `home_link` string
  - `platform_user_id` string
  - `extra_config` object
  - `enabled` boolean
  - `sync_frequency` string

**返回 200**：application/json → AccountOut

### POST /api/creators/{creator_id}/activate

Activate Creator

切换当前主博主（前端弹框确认后调用）。

**参数**

- `creator_id`（path）integer，必填
- `x-access-token`（header）string
**返回 200**：application/json → CreatorOut

## platform

### GET /api/platform/accounts/{account_id}/snapshots

Account Snapshots

**参数**

- `account_id`（path）integer，必填
- `x-access-token`（header）string
**返回 200**：application/json → object

### GET /api/platform/budget

Budget

预算额度（本地 Kv，毫秒级）；余额查询第三方较慢，默认不阻塞页面，
需要时显式 ?refresh_balance=true 再拉取。

**参数**

- `refresh_balance`（query）boolean
- `x-access-token`（header）string
**返回 200**：application/json → object

### PUT /api/platform/budget

Update Budget

**参数**

- `x-access-token`（header）string
**请求体**（application/json）

**返回 200**：application/json → object

### GET /api/platform/creator-summary

Creator Summary

复盘/博主页"我 vs 对标"汇总（粉丝/作品数/互动中位数/爆款率，基于最新快照与统计）。

**参数**

- `x-access-token`（header）string
**返回 200**：application/json → object

### GET /api/platform/jobs

List Jobs

**参数**

- `limit`（query）integer
- `status`（query）string
- `x-access-token`（header）string
**返回 200**：application/json → object

### GET /api/platform/posts

List Posts

**参数**

- `creator_id`（query）integer
- `account_id`（query）integer
- `platform`（query）string
- `kind`（query）string
- `limit`（query）integer
- `offset`（query）integer
- `x-access-token`（header）string
**返回 200**：application/json → object

### GET /api/platform/posts/{post_id}/comments

Post Comments

评论：默认读本地库（按点赞降序）；refresh=1 时实时调第三方（点赞 Top50）落库后再返回。

**参数**

- `post_id`（path）integer，必填
- `limit`（query）integer
- `refresh`（query）integer
- `x-access-token`（header）string
**返回 200**：application/json → object

### POST /api/platform/posts/{post_id}/comments/refresh

Refresh Post Comments

点“加载评论”：实时调第三方拉取（点赞 Top50）→ 去重落库 → 返回（下次直接读本地）。

**参数**

- `post_id`（path）integer，必填
- `limit`（query）integer
- `x-access-token`（header）string
**返回 200**：application/json → object

### GET /api/platform/posts/{post_id}/stats

Post Stats Series

**参数**

- `post_id`（path）integer，必填
- `x-access-token`（header）string
**返回 200**：application/json → object

### POST /api/platform/posts/{post_id}/sync

Sync Post

**参数**

- `post_id`（path）integer，必填
- `x-access-token`（header）string
**返回 200**：application/json → object

### POST /api/platform/posts/{post_id}/to-material

Post To Material

把云端作品转为本地素材（归属当前主博主；mock 阶段无视频文件，可后补上传）。

**参数**

- `post_id`（path）integer，必填
- `x-access-token`（header）string
**返回 200**：application/json → object

### POST /api/platform/sync

Trigger Sync

手动同步：initial=首次全量；daily=top15（R-070/R-109）；weekly=对标每周；可限定 account/creator。

**参数**

- `x-access-token`（header）string
**请求体**（application/json，`SyncRequest`）

字段：
  - `scope` string
  - `account_id` object
  - `creator_id` object
  - `top_n` object

**返回 200**：application/json → object

### POST /api/platform/sync-all

Trigger Sync All

R-162：一键同步当前主博主 + 其全部对标博主最新15条（daily 同口径）。为每个博主入队并预置同步记录（所有卡片立即可见动画），由一个后台消费者按队列逐个消费；运行中的博主跳过并汇总；完成后自动重新对标。
R-219：`skipped` 为结构化数组 `[{creator_id: int, name: str, reason: str}]`（reason：`已在运行` / `无启用账号`），前端按博主展示跳过提示条。

**参数**

- `x-access-token`（header）string
**返回 200**：application/json → object

**返回示例（200）**

```json
{ "task_id": 12, "creator_count": 3, "skipped": [{ "creator_id": 7, "name": "对标A", "reason": "已在运行" }] }
```

### GET /api/platform/topic-pool

Topic Pool

**参数**

- `date`（query）string
- `x-access-token`（header）string
**返回 200**：application/json → object

### DELETE /api/platform/topic-pool/{idea_id}

Dismiss Idea

**参数**

- `idea_id`（path）integer，必填
- `x-access-token`（header）string
**返回 200**：application/json → object

### POST /api/platform/topic-pool/{idea_id}/generate

Generate From Idea

从选题池灵感生成草稿（人工挑选后触发；不自动推送）。

**参数**

- `idea_id`（path）integer，必填
- `x-access-token`（header）string
**返回 200**：application/json → object

### POST /api/platform/videos/{video_id}/bind-links

Bind Video Links

R-036：编辑页按平台填写链接 → 解析并绑定各平台作品（支持三平台）。

每个非空链接解析后：若平台作品表已有该作品则直接绑定（local_video_id），
否则在当前主博主的该平台账号下创建占位作品再绑定。

**参数**

- `video_id`（path）integer，必填
- `x-access-token`（header）string
**请求体**（application/json）

**返回 200**：application/json → object

### POST /api/platform/videos/{video_id}/sync

Sync Video Data

素材库单条"同步数据"（本地素材需已绑定发布链接）。

**参数**

- `video_id`（path）integer，必填
- `x-access-token`（header）string
**返回 200**：application/json → object

### POST /api/platform/works/{work_id}/sync

Sync Work

云端合并作品卡「同步数据」（R-067）：同步该作品全部平台帖指标 + 评论点赞 Top50。

**参数**

- `work_id`（path）integer，必填
- `x-access-token`（header）string
**返回 200**：application/json → object

## works

### GET /api/works

Get Works

**参数**

- `creator_id`（query）integer
- `x-access-token`（header）string
**返回 200**：application/json → object

### GET /api/works/by-post/{post_id}

Get Work By Post

按平台作品 id 返回其所属云端条目（可跨博主，素材库深链/来源素材跳转用，R-122）。

**参数**

- `post_id`（path）integer
- `x-access-token`（header）string
**返回 200**：application/json → object

### POST /api/works/auto-merge

Auto Merge All

自动合并：把所有博主（或指定博主）下“同创作者+规范化标题相同”的跨平台作品合并为一。

**参数**

- `creator_id`（query）integer
- `x-access-token`（header）string
**返回 200**：application/json → object

### POST /api/works/cleanup-tags

Cleanup Tags

清理标签里的平台词与 [话题] 话题后缀（维护用）。

**参数**

- `x-access-token`（header）string
**返回 200**：application/json → object

### POST /api/works/merge

Merge Items

**参数**

- `x-access-token`（header）string
**请求体**（application/json，`MergeIn`）

字段：
  - `platform_post_ids` array

**返回 200**：application/json → object

### POST /api/works/meta

Set Meta

设置云端作品广告/价格（作用于整个合并作品，并同步已转的本地素材）。

**参数**

- `x-access-token`（header）string
**请求体**（application/json，`MetaIn`）

字段：
  - `work_id` object
  - `post_id` object
  - `is_ad` boolean
  - `ad_price` object

**返回 200**：application/json → object

### POST /api/works/to-local

Cloud To Local

**参数**

- `x-access-token`（header）string
**请求体**（multipart/form-data，`Body_cloud_to_local_api_works_to_local_post`）

字段：
  - `file` object
  - `text` string
  - `work_id` object
  - `post_id` object
  - `is_ad` string
  - `ad_price` string

**返回 200**：application/json → object

### DELETE /api/works/{item_id}

Delete Item

删除云端素材：kind=work 删整个合并作品及其平台记录；kind=post 只删单条。

**参数**

- `item_id`（path）integer，必填
- `kind`（query）string
- `x-access-token`（header）string
**返回 200**：application/json → object

### POST /api/works/{work_id}/split

Split Items

**参数**

- `work_id`（path）integer，必填
- `x-access-token`（header）string
**请求体**（application/json，`MergeIn`）

字段：
  - `platform_post_ids` array

**返回 200**：application/json → object

## library

### GET /api/library

Library Cards

素材库统一列表（R-179）：本地素材 + 云端作品合并去重后按日期倒序，游标分页（默认每批 20）。
筛选/搜索/计数一并下推服务端（前端不再全量拉取 + 内存过滤）。

**参数**

- `creator_id`（query）integer，0/不传=当前主博主
- `cursor`（query）string，上一页返回的 `next_cursor`；不传=第一页
- `limit`（query）integer，默认 20，上限 100
- `platforms`（query）string，可重复，命中任一平台
- `status`（query）string，planned / published
- `video`（query）string，yes / no（有无视频文件）
- `ad`（query）string，ad / no
- `kw`（query）string，标题关键词
- `tags`（query）string，可重复，需全部命中（AND）
- `likes_min` / `likes_max`（query）integer，点赞区间（任一平台命中即可）
- `x-access-token`（header）string
**返回 200**：application/json → object
`{total, filtered_total, facets:{tags}, items:[卡片], next_cursor, has_more}`

## opportunities

### POST /api/opportunities/comments

Comment Clusters

R-185/R-192：观众提问榜——未使用评论聚类，按需求分排序；默认用**模型1 语义聚类**（use_llm=true），失败回退本地聚类。R-202 起改为**后台任务**（点完返回 `{task_id}`，结果在 `task.result`）。

**参数**

- `limit`（query）integer，默认 15
- `use_llm`（query）boolean，默认 true
- `x-access-token`（header）string
**返回 200**：application/json → object（`{task_id}`）

### POST /api/opportunities/weekly

Weekly Pack

R-185：每周灵感补给包——需求 × 人设 × 热度 × 缺口 综合打分，去重并剔除已讲过的话题。R-202 起改为**后台任务**（返回 `{task_id}`，结果在 `task.result`）。

**参数**

- `limit`（query）integer，默认 20
- `x-access-token`（header）string
**返回 200**：application/json → object（`{task_id}`）

### GET /api/opportunities/ledger

Topic Ledger

R-185：选题账本——已讲过的话题 + 池中被判为「可能已讲」的灵感。

**参数**

- `limit`（query）integer，默认 50
- `x-access-token`（header）string
**返回 200**：application/json → object

### POST /api/opportunities/gap

Gap Suggestions

R-187：缺口选题——AI 基于「已讲话题 + 人设」给出该讲但没讲过的选题（避开重复）；AI 不可用返回空 + note。R-202 起改为**后台任务**（返回 `{task_id}`，结果在 `task.result`）。

**参数**

- `limit`（query）integer，默认 6
- `x-access-token`（header）string
**返回 200**：application/json → object（`{task_id}`）

### GET /api/opportunities/covered

Covered Titles

R-191：已讲过的话题标题（轻量）——供前端给灵感列表标「可能已讲」。

**参数**

- `limit`（query）integer，默认 300
- `x-access-token`（header）string
**返回 200**：application/json → object

### GET /api/opportunities/attribution

Topic Attribution

R-192：选题归因——按标签聚合已发布稿件的表现（来自 R-184/R-189 回填），看出哪类选题数据好；并用于给每周灵感包加权。

**参数**

- `limit`（query）integer，默认 15
- `x-access-token`（header）string
**返回 200**：application/json → object

## inspiration

### GET /api/inspiration

List Notes

R-186：灵感随手记列表（status 可选 new/used）。

**参数**

- `status`（query）string
- `limit`（query）integer，默认 100
- `x-access-token`（header）string
**返回 200**：application/json → array

### POST /api/inspiration

Create Note

R-186：新建一条随手记（text/image_url）。

**参数**

- `x-access-token`（header）string
**返回 200**：application/json → object

### POST /api/inspiration/{note_id}/develop

Develop Note

R-186：把随手记提炼成选题标题并直接入队生成草稿；标记该条为已用。

**参数**

- `note_id`（path）integer，必填
- `x-access-token`（header）string
**返回 200**：application/json → object

### DELETE /api/inspiration/{note_id}

Delete Note

R-186：删除随手记。

**参数**

- `note_id`（path）integer，必填
- `x-access-token`（header）string
**返回 200**：application/json → object

## 其他

### GET /health
Health

**返回 200**：application/json → object

## benchmark

### GET /api/benchmark/top

每个对标博主展示 4 条 = 最新15条里按互动分取前3 + 第四篇=该对标最新一篇（R-174，原 R-152 前2+最新；重叠按互动分顺延保底4条，展示时「有文案优先」R-106）。

### POST /api/benchmark/prepare

转写补齐「前3+最新」文案并返回有文案的 4 条（无文案顺延，R-174）。R-202 起改为**后台任务**（返回 `{task_id}`；完成后刷新 `/top` 即可，结果已落库）。

### POST /api/benchmark/analyze

AI 判断“我能不能讲”。

### POST /api/benchmark/rewrite

按人设洗稿并存脚本草稿。

### POST /api/benchmark/rewrite-source

R-152：素材库非主博主素材一键洗稿——入参 `video_id` / `post_id` / `work_id` 三选一，服务端取该素材 ASR 文案后走同一洗稿链路（双模型讨论），返回 task_id。

### POST /api/benchmark/rerun

R-102/R-152/R-174：页顶「重新对标」一键重跑——重捞所有对标最新15条 + 自动补「前3+最新」文案（长任务后台执行，返回 task_id）。

### GET /api/videos/{video_id}/media-meta

Video Media Meta

探测本地素材媒体信息（时长/是否纯音频），供前端播放器展示。

**参数**

- `video_id`（path）integer，必填
- `x-access-token`（header）string
**返回 200**：application/json → object

### GET /api/events

Sse Events

SSE 事件流（通知/任务进度实时推送）。

**参数**

- `x-access-token`（header）string
**返回 200**：application/json → object

### GET /api/drafts/{draft_id}/debate-status

Debate Status

当前双模型讨论进行到哪一步（思考中提示，R-134 补注册）。

R-173：除原有的 `status`（人类可读文案，老前端只读它做展示，语义保持不变）外，新增结构化字段
`state`（`running`/`failed`/`null`）+ `kind/note/actor/phase/round/rounds`；新前端据此画
「模型名 + 三点跳动 + 第 x/y 轮」，并在 `state != running` 时收尾（null=正常结束并刷新正文，
failed=「上次讨论中断」）。状态存 `app_kv['draft_ai:{id}']`（不新增表）。

**参数**

- `draft_id`（path）integer，必填
- `x-access-token`（header）string
**返回 200**：application/json → object

示例：`{"status": "MODEL1 正在按评审修订第 3/3 轮…", "state": "running", "kind": "rewrite", "note": "…", "actor": "model1", "phase": "revise", "round": 3, "rounds": 3}`

### GET /api/settings/asr

Get Asr Config

查看当前 ASR 服务商与模型配置（R-138 起读运行时配置 `app_kv`，设置页保存后立即生效）。服务商可选 `mock | aliyun | siliconflow | tencent`（R-200）。

**参数**

- `x-access-token`（header）string
**返回 200**：application/json → object

### POST /api/creators/{creator_id}/benchmark

Toggle Benchmark

把某博主设为/取消「对标博主」。

**参数**

- `creator_id`（path）integer，必填
- `x-access-token`（header）string
**返回 200**：application/json → object

### GET /api/settings/models

Get Models

AI 设置 → 模型设置：当前模型1/2（厂家/模型/Key）、生成方/评审方、ASR 服务商与模型、讨论轮次、每日篇数（R-138）。

返回还包含：`vendors`（厂家目录：可选模型 / 默认模型 / 是否已有 .env Key）、`asr`（`mode/model/options/siliconflow_models/tencent_models`，R-200 增腾讯引擎列表 `16k_zh_en_2.0|16k_zh_en|16k_zh`）、`warnings`（含双模型兼容性自检告警）、`selfcheck`（最近一次自检结果，R-139）、`budgets`（各功能推理预算，R-143：每项含 `label/desc/default/requested/value/floor/ceiling/custom`，`value` 是实际生效值）、`migrated_from_legacy`。

**参数**

- `x-access-token`（header）string
**返回 200**：application/json → object

### PUT /api/settings/models

Put Models

保存模型设置（厂家非法 / 缺少 Key / 生成方评审方非法 / ASR 配置非法 → 400 且带可读原因）；保存即生效、无需重启（R-138）。
ASR：`siliconflow` 需模型非空且 `.env` 有 `ECHO_SILICONFLOW_API_KEY`；`aliyun` 需 `.env` 有 `ECHO_ALIYUN_ASR_ACCESS_KEY_ID/APP_KEY`；`tencent`（R-200）需模型命中 `16k_zh_en_2.0|16k_zh_en|16k_zh` 且 `.env` 有 `ECHO_TENCENT_ASR_SECRET_ID/SECRET_KEY`。
保存后会异步入队一次「双模型兼容性自检」（线程任务 kind=`model_selfcheck`），结果由 `GET /api/settings/models` 的 `selfcheck` 带回（R-139）。

**参数**

- `x-access-token`（header）string
**请求体**（application/json，`ModelsIn`）

字段：
  - `model1` object（必填）
  - `model2` object（必填）
  - `gen_role` string（必填）
  - `referee_role` string（必填）
  - `asr_mode` string（必填）
  - `asr_model` string
  - `debate_rounds` integer
  - `topics_count` integer
  - `budgets` object（可选，R-143：`{预算项: 整数}`，键见 GET 返回的 `budgets`；未知键 / 非整数 / 越界 → 400）
  - `reset_budgets` boolean（可选，R-143：`true` 表示把全部预算恢复为代码默认）

**返回 200**：application/json → object
