# API 接口文档（自动生成）

> 来源：FastAPI OpenAPI（`/openapi.json`），随代码自动一致。共 99 个路由。
> 鉴权：除 `/health`、`/openapi.json`、`/docs` 与静态资源外，所有接口需请求头 `X-Access-Token`（值 = `ECHO_ACCESS_TOKEN`）。

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

选题→角度→草稿 三级流水（R-030）：给 3 个切入角度，作者点选后直接生成。

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

### GET /api/drafts/{draft_id}

Get Draft

**参数**

- `draft_id`（path）integer，必填
- `x-access-token`（header）string
**返回 200**：application/json → DraftOut

### PATCH /api/drafts/{draft_id}

Update Draft

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

### GET /api/drafts/{draft_id}/discussions

List Discussions

脚本讨论留痕（R-023）：按轮次返回聊天式消息。

**参数**

- `draft_id`（path）integer，必填
- `x-access-token`（header）string
**返回 200**：application/json → array

### POST /api/drafts/{draft_id}/feedback

Feedback

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

### POST /api/drafts/{draft_id}/rework

Draft Rework

一键回炉（R-030⑦）：按原选题重新异步生成一轮，完成后替换草稿。

**参数**

- `draft_id`（path）integer，必填
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

### GET /api/requirements

List Reqs

**参数**

- `x-access-token`（header）string
**返回 200**：application/json → array

### POST /api/requirements

Create Req

**参数**

- `x-access-token`（header）string
**请求体**（application/json，`RequirementCreate`）

字段：
  - `title` string（必填）
  - `summary` string

**返回 200**：application/json → RequirementOut

### GET /api/requirements/{rid}

Get Req

**参数**

- `rid`（path）string，必填
- `x-access-token`（header）string
**返回 200**：application/json → object

### PATCH /api/requirements/{rid}

Update Req

**参数**

- `rid`（path）string，必填
- `x-access-token`（header）string
**请求体**（application/json，`RequirementUpdate`）

字段：
  - `status` string（必填）

**返回 200**：application/json → RequirementOut

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

立即抓取今日热点（真实模式需 NAS 有外网）。

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

手动同步：initial=首次全量；daily=top20（R-070）；weekly=对标每周；可限定 account/creator。

**参数**

- `x-access-token`（header）string
**请求体**（application/json，`SyncRequest`）

字段：
  - `scope` string
  - `account_id` object
  - `creator_id` object
  - `top_n` object

**返回 200**：application/json → object

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

## 其他

### GET /health

Health

**返回 200**：application/json → object

## benchmark

### GET /api/benchmark/top

对标博主最新10条互动分 Top3。

### POST /api/benchmark/prepare

转写补齐文案并返回有文案 Top3（无文案顺延）。

### POST /api/benchmark/analyze

AI 判断“我能不能讲”。

### POST /api/benchmark/rewrite

按人设洗稿并存脚本草稿。
### POST /api/benchmark/rerun

R-102：页顶「重新对标」一键重跑——重捞所有对标最新10条 + 自动补 Top3 文案（长任务后台执行，返回 task_id）。
