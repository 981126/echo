# echo API 接口文档

> 由系统 OpenAPI（90 个接口）自动生成 + 人工补充约定。文档自动更新方法：导出 `/openapi.json` 后运行生成器。

## 通用约定
- Base URL：`http://localhost:8000`（生产为你的域名）
- 鉴权：除 `/health` 外全部需要请求头 `X-Access-Token: <ECHO_ACCESS_TOKEN>`；401 时前端自动跳登录
- 内容类型：JSON 接口 `Content-Type: application/json`；上传接口用 `multipart/form-data`（字段名 `file`）
- 列表返回：`{ "total": int, "items": [...] }`；分页参数通常 `limit` / `offset`
- 错误返回：HTTP 4xx/5xx + `{ "detail": "原因" }`
- 长任务接口：多数先建后台任务并立即返回，完成/失败会写右上角通知；进度查 `/api/tasks`
- 数据类型缩写：string / integer / number(float) / boolean / array<T> / object / datetime(string)

## 接口总览
| 分组 | 数量 | 作用 |
|---|---|---|
| videos | 9 | 素材库与转写 |
| platform | 17 | 平台数据/同步/预算/灵感池 |
| works | 8 | 作品合并/转本地 |
| creators | 11 | 博主与账号 |
| persona | 9 | 人设/金句/风格 |
| drafts | 11 | 脚本工作台/讨论/反馈 |
| chat | 7 | AI 对话(SSE) |
| prompts | 5 | 提示词版本 |
| topics | 4 | 热点/缺口 |
| pipeline | 2 | 每日流水线 |
| metrics | 5 | 指标 |
| review | 3 | 复盘 |
| notifications | 4 | 通知 |
| tasks | 2 | 后台任务 |
| requirements | 4 | 需求归档 |
| settings | 4 | 生成设置 |
| uploads | 1 | 富文本插图 |
| default | 1 | 健康检查 |


## videos

### GET /api/videos

List Videos

| 参数 | 位置 | 必填 | 类型 | 说明 |
|---|---|---|---|---|
| `platform` | query | 否 | string |  |
| `status` | query | 否 | string |  |
| `main_topic` | query | 否 | string |  |
| `limit` | query | 否 | integer |  |
| `offset` | query | 否 | integer |  |
| `x-access-token` | header | 否 | string |  |

**返回 200**：`VideoListOut`

| 字段 | 类型 | 说明 |
|---|---|---|
| `total` | integer |  |
| `items` | array<VideoOut> |  |

### POST /api/videos/upload

Upload Video

| 参数 | 位置 | 必填 | 类型 | 说明 |
|---|---|---|---|---|
| `x-access-token` | header | 否 | string |  |

**请求体 multipart**：`Body_upload_video_api_videos_upload_post`（字段名见下表）

| 字段 | 类型 | 说明 |
|---|---|---|
| `file` | string |  |

**返回 200**：`VideoOut`

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | integer |  |
| `filename` | string |  |
| `title` | string |  |
| `cover_url` | string | null |  |
| `platforms` | array<string> |  |
| `status` | string |  |
| `planned_publish_at` | string | null |  |
| `published_at` | string | null |  |
| `is_ad` | boolean |  |
| `ad_price` | integer | null |  |
| `main_topics` | array<string> |  |
| `tags` | array<string> |  |
| `tags_confirmed` | boolean |  |
| `created_at` | string |  |

### GET /api/videos/{video_id}

Get Video

| 参数 | 位置 | 必填 | 类型 | 说明 |
|---|---|---|---|---|
| `video_id` | path | 是 | integer |  |
| `x-access-token` | header | 否 | string |  |

**返回 200**：`VideoDetailOut`

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | integer |  |
| `filename` | string |  |
| `title` | string |  |
| `cover_url` | string | null |  |
| `platforms` | array<string> |  |
| `status` | string |  |
| `planned_publish_at` | string | null |  |
| `published_at` | string | null |  |
| `is_ad` | boolean |  |
| `ad_price` | integer | null |  |
| `main_topics` | array<string> |  |
| `tags` | array<string> |  |
| `tags_confirmed` | boolean |  |
| `created_at` | string |  |
| `transcript` | TranscriptOut | null |  |
| `platform_links` | array<PlatformLinkOut> |  |

### PATCH /api/videos/{video_id}

Update Video

| 参数 | 位置 | 必填 | 类型 | 说明 |
|---|---|---|---|---|
| `video_id` | path | 是 | integer |  |
| `x-access-token` | header | 否 | string |  |

**请求体 JSON**：`VideoUpdate`

| 字段 | 类型 | 说明 |
|---|---|---|
| `title` | string | null |  |
| `platforms` | array<string> | null |  |
| `status` | string | null |  |
| `planned_publish_at` | string | null |  |
| `published_at` | string | null |  |
| `is_ad` | boolean | null |  |
| `ad_price` | integer | null |  |
| `main_topics` | array<string> | null |  |
| `tags` | array<string> | null |  |
| `source_text` | string | null |  |
| `corrected_text` | string | null |  |

**返回 200**：`VideoOut`

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | integer |  |
| `filename` | string |  |
| `title` | string |  |
| `cover_url` | string | null |  |
| `platforms` | array<string> |  |
| `status` | string |  |
| `planned_publish_at` | string | null |  |
| `published_at` | string | null |  |
| `is_ad` | boolean |  |
| `ad_price` | integer | null |  |
| `main_topics` | array<string> |  |
| `tags` | array<string> |  |
| `tags_confirmed` | boolean |  |
| `created_at` | string |  |

### DELETE /api/videos/{video_id}

Delete Video

| 参数 | 位置 | 必填 | 类型 | 说明 |
|---|---|---|---|---|
| `video_id` | path | 是 | integer |  |
| `x-access-token` | header | 否 | string |  |

**返回 200**：`object`

### POST /api/videos/{video_id}/confirm-tags

Confirm Tags

| 参数 | 位置 | 必填 | 类型 | 说明 |
|---|---|---|---|---|
| `video_id` | path | 是 | integer |  |
| `x-access-token` | header | 否 | string |  |

**请求体 JSON**：`TagConfirmIn`

| 字段 | 类型 | 说明 |
|---|---|---|
| `tags_confirmed` | boolean |  |

**返回 200**：`VideoOut`

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | integer |  |
| `filename` | string |  |
| `title` | string |  |
| `cover_url` | string | null |  |
| `platforms` | array<string> |  |
| `status` | string |  |
| `planned_publish_at` | string | null |  |
| `published_at` | string | null |  |
| `is_ad` | boolean |  |
| `ad_price` | integer | null |  |
| `main_topics` | array<string> |  |
| `tags` | array<string> |  |
| `tags_confirmed` | boolean |  |
| `created_at` | string |  |

### POST /api/videos/{video_id}/cover

Upload Cover

| 参数 | 位置 | 必填 | 类型 | 说明 |
|---|---|---|---|---|
| `video_id` | path | 是 | integer |  |
| `x-access-token` | header | 否 | string |  |

**请求体 multipart**：`Body_upload_cover_api_videos__video_id__cover_post`（字段名见下表）

| 字段 | 类型 | 说明 |
|---|---|---|
| `file` | string |  |

**返回 200**：`VideoOut`

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | integer |  |
| `filename` | string |  |
| `title` | string |  |
| `cover_url` | string | null |  |
| `platforms` | array<string> |  |
| `status` | string |  |
| `planned_publish_at` | string | null |  |
| `published_at` | string | null |  |
| `is_ad` | boolean |  |
| `ad_price` | integer | null |  |
| `main_topics` | array<string> |  |
| `tags` | array<string> |  |
| `tags_confirmed` | boolean |  |
| `created_at` | string |  |

### DELETE /api/videos/{video_id}/cover

Delete Cover

| 参数 | 位置 | 必填 | 类型 | 说明 |
|---|---|---|---|---|
| `video_id` | path | 是 | integer |  |
| `x-access-token` | header | 否 | string |  |

**返回 200**：`VideoOut`

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | integer |  |
| `filename` | string |  |
| `title` | string |  |
| `cover_url` | string | null |  |
| `platforms` | array<string> |  |
| `status` | string |  |
| `planned_publish_at` | string | null |  |
| `published_at` | string | null |  |
| `is_ad` | boolean |  |
| `ad_price` | integer | null |  |
| `main_topics` | array<string> |  |
| `tags` | array<string> |  |
| `tags_confirmed` | boolean |  |
| `created_at` | string |  |

### POST /api/videos/{video_id}/transcribe

Transcribe Video

| 参数 | 位置 | 必填 | 类型 | 说明 |
|---|---|---|---|---|
| `video_id` | path | 是 | integer |  |
| `x-access-token` | header | 否 | string |  |

**返回 200**：`object`

## platform

### GET /api/platform/accounts/{account_id}/snapshots

Account Snapshots

| 参数 | 位置 | 必填 | 类型 | 说明 |
|---|---|---|---|---|
| `account_id` | path | 是 | integer |  |
| `x-access-token` | header | 否 | string |  |

### GET /api/platform/budget

Budget

| 参数 | 位置 | 必填 | 类型 | 说明 |
|---|---|---|---|---|
| `refresh_balance` | query | 否 | boolean |  |
| `x-access-token` | header | 否 | string |  |

**返回 200**：`object`

### PUT /api/platform/budget

Update Budget

| 参数 | 位置 | 必填 | 类型 | 说明 |
|---|---|---|---|---|
| `x-access-token` | header | 否 | string |  |

**返回 200**：`object`

### GET /api/platform/creator-summary

Creator Summary

| 参数 | 位置 | 必填 | 类型 | 说明 |
|---|---|---|---|---|
| `x-access-token` | header | 否 | string |  |

### GET /api/platform/jobs

List Jobs

| 参数 | 位置 | 必填 | 类型 | 说明 |
|---|---|---|---|---|
| `limit` | query | 否 | integer |  |
| `x-access-token` | header | 否 | string |  |

**返回 200**：`object`

### GET /api/platform/posts

List Posts

| 参数 | 位置 | 必填 | 类型 | 说明 |
|---|---|---|---|---|
| `creator_id` | query | 否 | integer |  |
| `account_id` | query | 否 | integer |  |
| `platform` | query | 否 | string |  |
| `kind` | query | 否 | string |  |
| `limit` | query | 否 | integer |  |
| `offset` | query | 否 | integer |  |
| `x-access-token` | header | 否 | string |  |

### GET /api/platform/posts/{post_id}/comments

Post Comments

| 参数 | 位置 | 必填 | 类型 | 说明 |
|---|---|---|---|---|
| `post_id` | path | 是 | integer |  |
| `limit` | query | 否 | integer |  |
| `refresh` | query | 否 | integer |  |
| `x-access-token` | header | 否 | string |  |

**返回 200**：`object`

### POST /api/platform/posts/{post_id}/comments/refresh

Refresh Post Comments

| 参数 | 位置 | 必填 | 类型 | 说明 |
|---|---|---|---|---|
| `post_id` | path | 是 | integer |  |
| `limit` | query | 否 | integer |  |
| `x-access-token` | header | 否 | string |  |

**返回 200**：`object`

### GET /api/platform/posts/{post_id}/stats

Post Stats Series

| 参数 | 位置 | 必填 | 类型 | 说明 |
|---|---|---|---|---|
| `post_id` | path | 是 | integer |  |
| `x-access-token` | header | 否 | string |  |

**返回 200**：`object`

### POST /api/platform/posts/{post_id}/sync

Sync Post

| 参数 | 位置 | 必填 | 类型 | 说明 |
|---|---|---|---|---|
| `post_id` | path | 是 | integer |  |
| `x-access-token` | header | 否 | string |  |

**返回 200**：`object`

### POST /api/platform/posts/{post_id}/to-material

Post To Material

| 参数 | 位置 | 必填 | 类型 | 说明 |
|---|---|---|---|---|
| `post_id` | path | 是 | integer |  |
| `x-access-token` | header | 否 | string |  |

**返回 200**：`object`

### POST /api/platform/sync

Trigger Sync

| 参数 | 位置 | 必填 | 类型 | 说明 |
|---|---|---|---|---|
| `x-access-token` | header | 否 | string |  |

**请求体 JSON**：`SyncRequest`

| 字段 | 类型 | 说明 |
|---|---|---|
| `scope` | string |  |
| `account_id` | integer | null |  |
| `creator_id` | integer | null |  |
| `top_n` | integer | null |  |

**返回 200**：`object`

### GET /api/platform/topic-pool

Topic Pool

| 参数 | 位置 | 必填 | 类型 | 说明 |
|---|---|---|---|---|
| `date` | query | 否 | string |  |
| `x-access-token` | header | 否 | string |  |

### DELETE /api/platform/topic-pool/{idea_id}

Dismiss Idea

| 参数 | 位置 | 必填 | 类型 | 说明 |
|---|---|---|---|---|
| `idea_id` | path | 是 | integer |  |
| `x-access-token` | header | 否 | string |  |

**返回 200**：`object`

### POST /api/platform/topic-pool/{idea_id}/generate

Generate From Idea

| 参数 | 位置 | 必填 | 类型 | 说明 |
|---|---|---|---|---|
| `idea_id` | path | 是 | integer |  |
| `x-access-token` | header | 否 | string |  |

**返回 200**：`object`

### POST /api/platform/videos/{video_id}/bind-links

Bind Video Links

| 参数 | 位置 | 必填 | 类型 | 说明 |
|---|---|---|---|---|
| `video_id` | path | 是 | integer |  |
| `x-access-token` | header | 否 | string |  |

**返回 200**：`object`

### POST /api/platform/videos/{video_id}/sync

Sync Video Data

| 参数 | 位置 | 必填 | 类型 | 说明 |
|---|---|---|---|---|
| `video_id` | path | 是 | integer |  |
| `x-access-token` | header | 否 | string |  |

**返回 200**：`object`

## works

### GET /api/works

Get Works

| 参数 | 位置 | 必填 | 类型 | 说明 |
|---|---|---|---|---|
| `creator_id` | query | 否 | integer |  |
| `x-access-token` | header | 否 | string |  |

**返回 200**：`object`

### POST /api/works/auto-merge

Auto Merge All

| 参数 | 位置 | 必填 | 类型 | 说明 |
|---|---|---|---|---|
| `creator_id` | query | 否 | integer |  |
| `x-access-token` | header | 否 | string |  |

**返回 200**：`object`

### POST /api/works/cleanup-tags

Cleanup Tags

| 参数 | 位置 | 必填 | 类型 | 说明 |
|---|---|---|---|---|
| `x-access-token` | header | 否 | string |  |

**返回 200**：`object`

### POST /api/works/merge

Merge Items

| 参数 | 位置 | 必填 | 类型 | 说明 |
|---|---|---|---|---|
| `x-access-token` | header | 否 | string |  |

**请求体 JSON**：`MergeIn`

| 字段 | 类型 | 说明 |
|---|---|---|
| `platform_post_ids` | array<integer> |  |

**返回 200**：`object`

### POST /api/works/meta

Set Meta

| 参数 | 位置 | 必填 | 类型 | 说明 |
|---|---|---|---|---|
| `x-access-token` | header | 否 | string |  |

**请求体 JSON**：`MetaIn`

| 字段 | 类型 | 说明 |
|---|---|---|
| `work_id` | integer | null |  |
| `post_id` | integer | null |  |
| `is_ad` | boolean |  |
| `ad_price` | integer | null |  |

**返回 200**：`object`

### POST /api/works/to-local

Cloud To Local

| 参数 | 位置 | 必填 | 类型 | 说明 |
|---|---|---|---|---|
| `x-access-token` | header | 否 | string |  |

**请求体 multipart**：`Body_cloud_to_local_api_works_to_local_post`（字段名见下表）

| 字段 | 类型 | 说明 |
|---|---|---|
| `file` | string | null |  |
| `text` | string |  |
| `work_id` | integer | null |  |
| `post_id` | integer | null |  |

**返回 200**：`object`

### DELETE /api/works/{item_id}

Delete Item

| 参数 | 位置 | 必填 | 类型 | 说明 |
|---|---|---|---|---|
| `item_id` | path | 是 | integer |  |
| `kind` | query | 否 | string |  |
| `x-access-token` | header | 否 | string |  |

**返回 200**：`object`

### POST /api/works/{work_id}/split

Split Items

| 参数 | 位置 | 必填 | 类型 | 说明 |
|---|---|---|---|---|
| `work_id` | path | 是 | integer |  |
| `x-access-token` | header | 否 | string |  |

**请求体 JSON**：`MergeIn`

| 字段 | 类型 | 说明 |
|---|---|---|
| `platform_post_ids` | array<integer> |  |

**返回 200**：`object`

## creators

### GET /api/creators

List Creators

| 参数 | 位置 | 必填 | 类型 | 说明 |
|---|---|---|---|---|
| `x-access-token` | header | 否 | string |  |

**返回 200**：`array<object>`

### POST /api/creators

Create Creator

| 参数 | 位置 | 必填 | 类型 | 说明 |
|---|---|---|---|---|
| `x-access-token` | header | 否 | string |  |

**请求体 JSON**：`CreatorIn`

| 字段 | 类型 | 说明 |
|---|---|---|
| `kind` | string |  |
| `parent_id` | integer | null |  |
| `name` | string |  |
| `note` | string |  |

**返回 200**：`CreatorOut`

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | integer |  |
| `kind` | string |  |
| `parent_id` | integer | null |  |
| `name` | string |  |
| `note` | string |  |
| `is_current` | boolean |  |
| `created_at` | string |  |

### PATCH /api/creators/accounts/{account_id}

Update Account

| 参数 | 位置 | 必填 | 类型 | 说明 |
|---|---|---|---|---|
| `account_id` | path | 是 | integer |  |
| `x-access-token` | header | 否 | string |  |

**请求体 JSON**：`AccountIn`

| 字段 | 类型 | 说明 |
|---|---|---|
| `platform` | string |  |
| `nickname` | string |  |
| `home_link` | string |  |
| `platform_user_id` | string |  |
| `extra_config` | object |  |
| `enabled` | boolean |  |
| `sync_frequency` | string |  |

**返回 200**：`AccountOut`

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | integer |  |
| `extra_config` | object |  |
| `creator_id` | integer |  |
| `platform` | string |  |
| `nickname` | string |  |
| `home_link` | string |  |
| `platform_user_id` | string |  |
| `avatar_path` | string |  |
| `avatar_url` | string |  |
| `avatar` | string | null |  |
| `enabled` | boolean |  |
| `sync_frequency` | string |  |
| `last_sync_at` | string | null |  |
| `sync_status` | string |  |
| `sync_message` | string |  |
| `created_at` | string |  |

### DELETE /api/creators/accounts/{account_id}

Remove Account

| 参数 | 位置 | 必填 | 类型 | 说明 |
|---|---|---|---|---|
| `account_id` | path | 是 | integer |  |
| `x-access-token` | header | 否 | string |  |

**返回 200**：`object`

### POST /api/creators/accounts/{account_id}/avatar

Upload Account Avatar

| 参数 | 位置 | 必填 | 类型 | 说明 |
|---|---|---|---|---|
| `account_id` | path | 是 | integer |  |
| `x-access-token` | header | 否 | string |  |

**请求体 multipart**：`Body_upload_account_avatar_api_creators_accounts__account_id__avatar_post`（字段名见下表）

| 字段 | 类型 | 说明 |
|---|---|---|
| `file` | string |  |

**返回 200**：`object`

### GET /api/creators/current

Get Current

| 参数 | 位置 | 必填 | 类型 | 说明 |
|---|---|---|---|---|
| `x-access-token` | header | 否 | string |  |

**返回 200**：`object`

### PATCH /api/creators/{creator_id}

Update Creator

| 参数 | 位置 | 必填 | 类型 | 说明 |
|---|---|---|---|---|
| `creator_id` | path | 是 | integer |  |
| `x-access-token` | header | 否 | string |  |

**请求体 JSON**：`CreatorIn`

| 字段 | 类型 | 说明 |
|---|---|---|
| `kind` | string |  |
| `parent_id` | integer | null |  |
| `name` | string |  |
| `note` | string |  |

**返回 200**：`CreatorOut`

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | integer |  |
| `kind` | string |  |
| `parent_id` | integer | null |  |
| `name` | string |  |
| `note` | string |  |
| `is_current` | boolean |  |
| `created_at` | string |  |

### DELETE /api/creators/{creator_id}

Remove Creator

| 参数 | 位置 | 必填 | 类型 | 说明 |
|---|---|---|---|---|
| `creator_id` | path | 是 | integer |  |
| `x-access-token` | header | 否 | string |  |

**返回 200**：`object`

### GET /api/creators/{creator_id}/accounts

List Accounts

| 参数 | 位置 | 必填 | 类型 | 说明 |
|---|---|---|---|---|
| `creator_id` | path | 是 | integer |  |
| `x-access-token` | header | 否 | string |  |

**返回 200**：`array<object>`

### POST /api/creators/{creator_id}/accounts

Create Account

| 参数 | 位置 | 必填 | 类型 | 说明 |
|---|---|---|---|---|
| `creator_id` | path | 是 | integer |  |
| `x-access-token` | header | 否 | string |  |

**请求体 JSON**：`AccountIn`

| 字段 | 类型 | 说明 |
|---|---|---|
| `platform` | string |  |
| `nickname` | string |  |
| `home_link` | string |  |
| `platform_user_id` | string |  |
| `extra_config` | object |  |
| `enabled` | boolean |  |
| `sync_frequency` | string |  |

**返回 200**：`AccountOut`

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | integer |  |
| `extra_config` | object |  |
| `creator_id` | integer |  |
| `platform` | string |  |
| `nickname` | string |  |
| `home_link` | string |  |
| `platform_user_id` | string |  |
| `avatar_path` | string |  |
| `avatar_url` | string |  |
| `avatar` | string | null |  |
| `enabled` | boolean |  |
| `sync_frequency` | string |  |
| `last_sync_at` | string | null |  |
| `sync_status` | string |  |
| `sync_message` | string |  |
| `created_at` | string |  |

### POST /api/creators/{creator_id}/activate

Activate Creator

| 参数 | 位置 | 必填 | 类型 | 说明 |
|---|---|---|---|---|
| `creator_id` | path | 是 | integer |  |
| `x-access-token` | header | 否 | string |  |

**返回 200**：`CreatorOut`

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | integer |  |
| `kind` | string |  |
| `parent_id` | integer | null |  |
| `name` | string |  |
| `note` | string |  |
| `is_current` | boolean |  |
| `created_at` | string |  |

## persona

### GET /api/persona

List Persona

| 参数 | 位置 | 必填 | 类型 | 说明 |
|---|---|---|---|---|
| `status` | query | 否 | string |  |
| `x-access-token` | header | 否 | string |  |

**返回 200**：`PersonaTagOut`

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | integer |  |
| `label` | string |  |
| `description` | string |  |
| `category` | string |  |
| `source` | string |  |
| `status` | string |  |
| `version` | integer |  |
| `created_at` | string |  |

### POST /api/persona/init

Init Persona

| 参数 | 位置 | 必填 | 类型 | 说明 |
|---|---|---|---|---|
| `x-access-token` | header | 否 | string |  |

### GET /api/persona/phrases/suggest

Suggest Phrases

| 参数 | 位置 | 必填 | 类型 | 说明 |
|---|---|---|---|---|
| `limit` | query | 否 | integer |  |
| `x-access-token` | header | 否 | string |  |

**返回 200**：`object`

### GET /api/persona/style

Style Overview

| 参数 | 位置 | 必填 | 类型 | 说明 |
|---|---|---|---|---|
| `x-access-token` | header | 否 | string |  |

**返回 200**：`object`

### PUT /api/persona/style

Save Style Words

| 参数 | 位置 | 必填 | 类型 | 说明 |
|---|---|---|---|---|
| `x-access-token` | header | 否 | string |  |

**返回 200**：`object`

### POST /api/persona/tags

Add Manual Tag

| 参数 | 位置 | 必填 | 类型 | 说明 |
|---|---|---|---|---|
| `x-access-token` | header | 否 | string |  |

**请求体 JSON**：`PersonaTagCreate`

| 字段 | 类型 | 说明 |
|---|---|---|
| `label` | string |  |
| `description` | string |  |
| `category` | string |  |
| `source` | string |  |

**返回 200**：`PersonaTagOut`

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | integer |  |
| `label` | string |  |
| `description` | string |  |
| `category` | string |  |
| `source` | string |  |
| `status` | string |  |
| `version` | integer |  |
| `created_at` | string |  |

### PATCH /api/persona/tags/{tag_id}

Update Tag

| 参数 | 位置 | 必填 | 类型 | 说明 |
|---|---|---|---|---|
| `tag_id` | path | 是 | integer |  |
| `x-access-token` | header | 否 | string |  |

**请求体 JSON**：`PersonaTagUpdate`

| 字段 | 类型 | 说明 |
|---|---|---|
| `label` | string |  |
| `description` | string |  |
| `category` | string |  |

**返回 200**：`PersonaTagOut`

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | integer |  |
| `label` | string |  |
| `description` | string |  |
| `category` | string |  |
| `source` | string |  |
| `status` | string |  |
| `version` | integer |  |
| `created_at` | string |  |

### DELETE /api/persona/tags/{tag_id}

Delete Tag

| 参数 | 位置 | 必填 | 类型 | 说明 |
|---|---|---|---|---|
| `tag_id` | path | 是 | integer |  |
| `x-access-token` | header | 否 | string |  |

**返回 200**：`object`

### POST /api/persona/tags/{tag_id}/decision

Decide Tag

| 参数 | 位置 | 必填 | 类型 | 说明 |
|---|---|---|---|---|
| `tag_id` | path | 是 | integer |  |
| `x-access-token` | header | 否 | string |  |

**请求体 JSON**：`PersonaDecision`

| 字段 | 类型 | 说明 |
|---|---|---|
| `status` | string |  |

**返回 200**：`PersonaTagOut`

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | integer |  |
| `label` | string |  |
| `description` | string |  |
| `category` | string |  |
| `source` | string |  |
| `status` | string |  |
| `version` | integer |  |
| `created_at` | string |  |

## drafts

### GET /api/drafts

List Drafts

| 参数 | 位置 | 必填 | 类型 | 说明 |
|---|---|---|---|---|
| `status` | query | 否 | string |  |
| `video_id` | query | 否 | integer | null |  |
| `limit` | query | 否 | integer |  |
| `x-access-token` | header | 否 | string |  |

**返回 200**：`DraftOut`

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | integer |  |
| `video_id` | integer | null |  |
| `title` | string |  |
| `cover_text` | string |  |
| `script` | string |  |
| `platform_shells` | object |  |
| `source` | string |  |
| `status` | string |  |
| `version` | integer |  |
| `created_at` | string |  |
| `updated_at` | string |  |

### POST /api/drafts

Create Draft

| 参数 | 位置 | 必填 | 类型 | 说明 |
|---|---|---|---|---|
| `x-access-token` | header | 否 | string |  |

**请求体 JSON**：`DraftCreate`

| 字段 | 类型 | 说明 |
|---|---|---|
| `video_id` | integer | null |  |
| `title` | string |  |
| `cover_text` | string |  |
| `script` | string |  |
| `platform_shells` | object |  |
| `status` | string |  |

**返回 200**：`DraftOut`

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | integer |  |
| `video_id` | integer | null |  |
| `title` | string |  |
| `cover_text` | string |  |
| `script` | string |  |
| `platform_shells` | object |  |
| `source` | string |  |
| `status` | string |  |
| `version` | integer |  |
| `created_at` | string |  |
| `updated_at` | string |  |

### POST /api/drafts/angles

Suggest Angles

| 参数 | 位置 | 必填 | 类型 | 说明 |
|---|---|---|---|---|
| `x-access-token` | header | 否 | string |  |

**请求体 JSON**：`AnglesIn`

| 字段 | 类型 | 说明 |
|---|---|---|
| `topic` | string |  |
| `platform` | string |  |

**返回 200**：`object`

### POST /api/drafts/generate

Generate

| 参数 | 位置 | 必填 | 类型 | 说明 |
|---|---|---|---|---|
| `x-access-token` | header | 否 | string |  |

**请求体 JSON**：`GenerateIn`

| 字段 | 类型 | 说明 |
|---|---|---|
| `topic` | string |  |

**返回 200**：`DraftOut`

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | integer |  |
| `video_id` | integer | null |  |
| `title` | string |  |
| `cover_text` | string |  |
| `script` | string |  |
| `platform_shells` | object |  |
| `source` | string |  |
| `status` | string |  |
| `version` | integer |  |
| `created_at` | string |  |
| `updated_at` | string |  |

### POST /api/drafts/generate-async

Generate Async

| 参数 | 位置 | 必填 | 类型 | 说明 |
|---|---|---|---|---|
| `x-access-token` | header | 否 | string |  |

**请求体 JSON**：`GenerateIn`

| 字段 | 类型 | 说明 |
|---|---|---|
| `topic` | string |  |

**返回 200**：`object`

### GET /api/drafts/{draft_id}

Get Draft

| 参数 | 位置 | 必填 | 类型 | 说明 |
|---|---|---|---|---|
| `draft_id` | path | 是 | integer |  |
| `x-access-token` | header | 否 | string |  |

**返回 200**：`DraftOut`

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | integer |  |
| `video_id` | integer | null |  |
| `title` | string |  |
| `cover_text` | string |  |
| `script` | string |  |
| `platform_shells` | object |  |
| `source` | string |  |
| `status` | string |  |
| `version` | integer |  |
| `created_at` | string |  |
| `updated_at` | string |  |

### PATCH /api/drafts/{draft_id}

Update Draft

| 参数 | 位置 | 必填 | 类型 | 说明 |
|---|---|---|---|---|
| `draft_id` | path | 是 | integer |  |
| `x-access-token` | header | 否 | string |  |

**请求体 JSON**：`DraftUpdate`

| 字段 | 类型 | 说明 |
|---|---|---|
| `video_id` | integer | null |  |
| `title` | string | null |  |
| `cover_text` | string | null |  |
| `script` | string | null |  |
| `platform_shells` | object | null |  |
| `status` | string | null |  |

**返回 200**：`DraftOut`

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | integer |  |
| `video_id` | integer | null |  |
| `title` | string |  |
| `cover_text` | string |  |
| `script` | string |  |
| `platform_shells` | object |  |
| `source` | string |  |
| `status` | string |  |
| `version` | integer |  |
| `created_at` | string |  |
| `updated_at` | string |  |

### GET /api/drafts/{draft_id}/check

Draft Check

| 参数 | 位置 | 必填 | 类型 | 说明 |
|---|---|---|---|---|
| `draft_id` | path | 是 | integer |  |
| `x-access-token` | header | 否 | string |  |

**返回 200**：`object`

### GET /api/drafts/{draft_id}/discussions

List Discussions

| 参数 | 位置 | 必填 | 类型 | 说明 |
|---|---|---|---|---|
| `draft_id` | path | 是 | integer |  |
| `x-access-token` | header | 否 | string |  |

**返回 200**：`array<object>`

### POST /api/drafts/{draft_id}/feedback

Feedback

| 参数 | 位置 | 必填 | 类型 | 说明 |
|---|---|---|---|---|
| `draft_id` | path | 是 | integer |  |
| `x-access-token` | header | 否 | string |  |

**请求体 JSON**：`FeedbackIn`

| 字段 | 类型 | 说明 |
|---|---|---|
| `liked` | boolean | null |  |
| `rating` | integer | null |  |
| `comment` | string |  |
| `hook_score` | integer | null |  |
| `pace_score` | integer | null |  |
| `ending_score` | integer | null |  |
| `style_score` | integer | null |  |

**返回 200**：`object`

### POST /api/drafts/{draft_id}/rework

Draft Rework

| 参数 | 位置 | 必填 | 类型 | 说明 |
|---|---|---|---|---|
| `draft_id` | path | 是 | integer |  |
| `x-access-token` | header | 否 | string |  |

**返回 200**：`object`

## chat

### POST /api/chat

Chat

| 参数 | 位置 | 必填 | 类型 | 说明 |
|---|---|---|---|---|
| `x-access-token` | header | 否 | string |  |

**请求体 JSON**：`ChatIn`

| 字段 | 类型 | 说明 |
|---|---|---|
| `message` | string |  |

**返回 200**：`ChatOut`

| 字段 | 类型 | 说明 |
|---|---|---|
| `reply` | string |  |
| `message_id` | integer |  |

### GET /api/chat/conversations

List Conversations

| 参数 | 位置 | 必填 | 类型 | 说明 |
|---|---|---|---|---|
| `x-access-token` | header | 否 | string |  |

**返回 200**：`ConversationOut`

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | integer |  |
| `title` | string |  |
| `created_at` | string |  |
| `updated_at` | string |  |

### POST /api/chat/conversations

Create Conversation

| 参数 | 位置 | 必填 | 类型 | 说明 |
|---|---|---|---|---|
| `x-access-token` | header | 否 | string |  |

**请求体 JSON**：`ConversationCreate`

| 字段 | 类型 | 说明 |
|---|---|---|
| `title` | string |  |

**返回 200**：`ConversationOut`

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | integer |  |
| `title` | string |  |
| `created_at` | string |  |
| `updated_at` | string |  |

### PATCH /api/chat/conversations/{conv_id}

Rename Conversation

| 参数 | 位置 | 必填 | 类型 | 说明 |
|---|---|---|---|---|
| `conv_id` | path | 是 | integer |  |
| `x-access-token` | header | 否 | string |  |

**请求体 JSON**：`ConversationUpdate`

| 字段 | 类型 | 说明 |
|---|---|---|
| `title` | string |  |

**返回 200**：`ConversationOut`

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | integer |  |
| `title` | string |  |
| `created_at` | string |  |
| `updated_at` | string |  |

### DELETE /api/chat/conversations/{conv_id}

Delete Conversation

| 参数 | 位置 | 必填 | 类型 | 说明 |
|---|---|---|---|---|
| `conv_id` | path | 是 | integer |  |
| `x-access-token` | header | 否 | string |  |

**返回 200**：`object`

### GET /api/chat/history

Chat History

| 参数 | 位置 | 必填 | 类型 | 说明 |
|---|---|---|---|---|
| `conversation_id` | query | 否 | integer | null |  |
| `limit` | query | 否 | integer |  |
| `x-access-token` | header | 否 | string |  |

**返回 200**：`ChatMessageOut`

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | integer |  |
| `conversation_id` | integer | null |  |
| `role` | string |  |
| `content` | string |  |
| `created_at` | string |  |

### POST /api/chat/stream

Chat Stream

| 参数 | 位置 | 必填 | 类型 | 说明 |
|---|---|---|---|---|
| `x-access-token` | header | 否 | string |  |

**请求体 JSON**：`ChatStreamIn`

| 字段 | 类型 | 说明 |
|---|---|---|
| `conversation_id` | integer | null |  |
| `message` | string |  |

## prompts

### GET /api/prompts/keys

List Keys

| 参数 | 位置 | 必填 | 类型 | 说明 |
|---|---|---|---|---|
| `x-access-token` | header | 否 | string |  |

**返回 200**：`array<object>`

### POST /api/prompts/{key}/enable

Enable Prompt

| 参数 | 位置 | 必填 | 类型 | 说明 |
|---|---|---|---|---|
| `key` | path | 是 | string |  |
| `x-access-token` | header | 否 | string |  |

**请求体 JSON**：`PromptEnableIn`

| 字段 | 类型 | 说明 |
|---|---|---|
| `version` | integer |  |

**返回 200**：`object`

### POST /api/prompts/{key}/optimize

Optimize Prompt

| 参数 | 位置 | 必填 | 类型 | 说明 |
|---|---|---|---|---|
| `key` | path | 是 | string |  |
| `x-access-token` | header | 否 | string |  |

**请求体 JSON**：`PromptOptimizeIn`

| 字段 | 类型 | 说明 |
|---|---|---|
| `material` | string |  |

**返回 200**：`object`

### POST /api/prompts/{key}/save

Save Prompt

| 参数 | 位置 | 必填 | 类型 | 说明 |
|---|---|---|---|---|
| `key` | path | 是 | string |  |
| `x-access-token` | header | 否 | string |  |

**请求体 JSON**：`PromptSaveIn`

| 字段 | 类型 | 说明 |
|---|---|---|
| `content` | string |  |

**返回 200**：`object`

### GET /api/prompts/{key}/versions

List Versions

| 参数 | 位置 | 必填 | 类型 | 说明 |
|---|---|---|---|---|
| `key` | path | 是 | string |  |
| `x-access-token` | header | 否 | string |  |

**返回 200**：`array<object>`

## topics

### GET /api/topics

List Candidates

| 参数 | 位置 | 必填 | 类型 | 说明 |
|---|---|---|---|---|
| `date` | query | 否 | string |  |
| `x-access-token` | header | 否 | string |  |

### GET /api/topics/gaps

Topic Gaps

| 参数 | 位置 | 必填 | 类型 | 说明 |
|---|---|---|---|---|
| `days` | query | 否 | integer |  |
| `x-access-token` | header | 否 | string |  |

### GET /api/topics/hot

List Hot

| 参数 | 位置 | 必填 | 类型 | 说明 |
|---|---|---|---|---|
| `date` | query | 否 | string |  |
| `x-access-token` | header | 否 | string |  |

### POST /api/topics/refresh

Refresh Hot

| 参数 | 位置 | 必填 | 类型 | 说明 |
|---|---|---|---|---|
| `x-access-token` | header | 否 | string |  |

## pipeline

### POST /api/pipeline/run

Trigger Pipeline

| 参数 | 位置 | 必填 | 类型 | 说明 |
|---|---|---|---|---|
| `x-access-token` | header | 否 | string |  |

**请求体 JSON**：`RunIn`

| 字段 | 类型 | 说明 |
|---|---|---|
| `force` | boolean |  |

### GET /api/pipeline/status

Pipeline Status

| 参数 | 位置 | 必填 | 类型 | 说明 |
|---|---|---|---|---|
| `x-access-token` | header | 否 | string |  |

## metrics

### POST /api/metrics

Add Metric

| 参数 | 位置 | 必填 | 类型 | 说明 |
|---|---|---|---|---|
| `x-access-token` | header | 否 | string |  |

**请求体 JSON**：`MetricIn`

| 字段 | 类型 | 说明 |
|---|---|---|
| `video_id` | integer |  |
| `snapshot_date` | string |  |
| `plays` | integer |  |
| `likes` | integer |  |
| `favorites` | integer |  |
| `comments` | integer |  |
| `followers_gained` | integer |  |

### POST /api/metrics/fetch

Trigger Fetch

| 参数 | 位置 | 必填 | 类型 | 说明 |
|---|---|---|---|---|
| `x-access-token` | header | 否 | string |  |

### POST /api/metrics/import

Import Metrics

| 参数 | 位置 | 必填 | 类型 | 说明 |
|---|---|---|---|---|
| `x-access-token` | header | 否 | string |  |

**请求体 JSON**：`ImportIn`

| 字段 | 类型 | 说明 |
|---|---|---|
| `rows` | array<MetricIn> |  |

### GET /api/metrics/summary

Get Summary

| 参数 | 位置 | 必填 | 类型 | 说明 |
|---|---|---|---|---|
| `x-access-token` | header | 否 | string |  |

### GET /api/metrics/video/{video_id}

Get Series

| 参数 | 位置 | 必填 | 类型 | 说明 |
|---|---|---|---|---|
| `video_id` | path | 是 | integer |  |
| `x-access-token` | header | 否 | string |  |

## review

### POST /api/review/generate

Generate

| 参数 | 位置 | 必填 | 类型 | 说明 |
|---|---|---|---|---|
| `run_date` | query | 否 | string |  |
| `x-access-token` | header | 否 | string |  |

### GET /api/review/radar

Radar

| 参数 | 位置 | 必填 | 类型 | 说明 |
|---|---|---|---|---|
| `x-access-token` | header | 否 | string |  |

### GET /api/review/report

Get Report

| 参数 | 位置 | 必填 | 类型 | 说明 |
|---|---|---|---|---|
| `x-access-token` | header | 否 | string |  |

## notifications

### GET /api/notifications

List Notifications

| 参数 | 位置 | 必填 | 类型 | 说明 |
|---|---|---|---|---|
| `limit` | query | 否 | integer |  |
| `x-access-token` | header | 否 | string |  |

**返回 200**：`NotificationOut`

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | integer |  |
| `kind` | string |  |
| `status` | string |  |
| `title` | string |  |
| `message` | string |  |
| `target` | string |  |
| `read` | boolean |  |
| `created_at` | string |  |

### POST /api/notifications/clear

Clear Notifications

| 参数 | 位置 | 必填 | 类型 | 说明 |
|---|---|---|---|---|
| `x-access-token` | header | 否 | string |  |

**返回 200**：`object`

### POST /api/notifications/read

Mark Read

| 参数 | 位置 | 必填 | 类型 | 说明 |
|---|---|---|---|---|
| `x-access-token` | header | 否 | string |  |

**请求体 JSON**：`NotificationReadIn`

| 字段 | 类型 | 说明 |
|---|---|---|
| `ids` | array<integer> | null |  |

**返回 200**：`object`

### GET /api/notifications/unread-count

Unread Count

| 参数 | 位置 | 必填 | 类型 | 说明 |
|---|---|---|---|---|
| `x-access-token` | header | 否 | string |  |

**返回 200**：`object`

## tasks

### GET /api/tasks

List Tasks

| 参数 | 位置 | 必填 | 类型 | 说明 |
|---|---|---|---|---|
| `limit` | query | 否 | integer |  |
| `x-access-token` | header | 否 | string |  |

**返回 200**：`TaskOut`

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | integer |  |
| `kind` | string |  |
| `status` | string |  |
| `progress` | integer |  |
| `error` | string |  |
| `created_at` | string |  |
| `updated_at` | string |  |

### GET /api/tasks/{task_id}

Get Task

| 参数 | 位置 | 必填 | 类型 | 说明 |
|---|---|---|---|---|
| `task_id` | path | 是 | integer |  |
| `x-access-token` | header | 否 | string |  |

**返回 200**：`TaskOut`

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | integer |  |
| `kind` | string |  |
| `status` | string |  |
| `progress` | integer |  |
| `error` | string |  |
| `created_at` | string |  |
| `updated_at` | string |  |

## requirements

### GET /api/requirements

List Reqs

| 参数 | 位置 | 必填 | 类型 | 说明 |
|---|---|---|---|---|
| `x-access-token` | header | 否 | string |  |

**返回 200**：`RequirementOut`

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | string |  |
| `title` | string |  |
| `status` | string |  |
| `summary` | string |  |
| `path` | string |  |

### POST /api/requirements

Create Req

| 参数 | 位置 | 必填 | 类型 | 说明 |
|---|---|---|---|---|
| `x-access-token` | header | 否 | string |  |

**请求体 JSON**：`RequirementCreate`

| 字段 | 类型 | 说明 |
|---|---|---|
| `title` | string |  |
| `summary` | string |  |

**返回 200**：`RequirementOut`

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | string |  |
| `title` | string |  |
| `status` | string |  |
| `summary` | string |  |
| `path` | string |  |

### GET /api/requirements/{rid}

Get Req

| 参数 | 位置 | 必填 | 类型 | 说明 |
|---|---|---|---|---|
| `rid` | path | 是 | string |  |
| `x-access-token` | header | 否 | string |  |

**返回 200**：`object`

### PATCH /api/requirements/{rid}

Update Req

| 参数 | 位置 | 必填 | 类型 | 说明 |
|---|---|---|---|---|
| `rid` | path | 是 | string |  |
| `x-access-token` | header | 否 | string |  |

**请求体 JSON**：`RequirementUpdate`

| 字段 | 类型 | 说明 |
|---|---|---|
| `status` | string |  |

**返回 200**：`RequirementOut`

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | string |  |
| `title` | string |  |
| `status` | string |  |
| `summary` | string |  |
| `path` | string |  |

## settings

### GET /api/settings/debate-rounds

Get Rounds

| 参数 | 位置 | 必填 | 类型 | 说明 |
|---|---|---|---|---|
| `x-access-token` | header | 否 | string |  |

**返回 200**：`object`

### PUT /api/settings/debate-rounds

Set Rounds

| 参数 | 位置 | 必填 | 类型 | 说明 |
|---|---|---|---|---|
| `x-access-token` | header | 否 | string |  |

**请求体 JSON**：`RoundsIn`

| 字段 | 类型 | 说明 |
|---|---|---|
| `rounds` | integer |  |

**返回 200**：`object`

### GET /api/settings/generation-model

Get Mode

| 参数 | 位置 | 必填 | 类型 | 说明 |
|---|---|---|---|---|
| `x-access-token` | header | 否 | string |  |

**返回 200**：`object`

### PUT /api/settings/generation-model

Set Mode

| 参数 | 位置 | 必填 | 类型 | 说明 |
|---|---|---|---|---|
| `x-access-token` | header | 否 | string |  |

**请求体 JSON**：`ModeIn`

| 字段 | 类型 | 说明 |
|---|---|---|
| `mode` | string |  |

**返回 200**：`object`

## uploads

### POST /api/uploads/image

Upload Image

| 参数 | 位置 | 必填 | 类型 | 说明 |
|---|---|---|---|---|
| `x-access-token` | header | 否 | string |  |

**请求体 multipart**：`Body_upload_image_api_uploads_image_post`（字段名见下表）

| 字段 | 类型 | 说明 |
|---|---|---|
| `file` | string |  |

**返回 200**：`object`

## default

### GET /health

Health
