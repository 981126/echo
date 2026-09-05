# echo 数据库表结构设计

> 由 SQLAlchemy 模型自动生成（表/字段/索引/外键）；SQLite。
> 字段口径备注在**说明**列；如需补注释可回写模型 docstring 或本文件下方附录。

## 约定
- 主键：自增 `id`；系统时间（created_at 等）为 UTC；**平台发布时间（platform_posts.publish_time 及由平台转本地的 published_at）按北京时间 +8 存储**（R-061 时区修复，存量已 +8h 迁移）
- 列表/多选字段（platforms/main_topics/tags 等）以 JSON 字符串存储，接口层自动解析为数组
- 软删除：脚本草稿用 `status`（used/discarded/…）逻辑删除；素材删除为物理删除（连同文件）

## 表总览
| 表 | 说明 |
|---|---|
| `ai_prompts` | 提示词版本 |
| `app_kv` | KV 配置 |
| `background_tasks` | 后台任务 |
| `chat_conversations` | AI 会话 |
| `chat_messages` | AI 消息 |
| `creator_account_snapshots` | 账号每日快照 |
| `creator_accounts` | 平台账号 |
| `creators` | 博主(主/对标) |
| `draft_discussions` | 双模型讨论留痕 |
| `drafts` | 脚本草稿 |
| `feedback` | 草稿打分/采用 |
| `hot_topics` | 热点 |
| `metrics_snapshots` | 本地素材每日指标 |
| `notifications` | 通知 |
| `persona_tags` | 人设标签(风格/赛道/红线/金句) |
| `pipeline_runs` | 流水线运行 |
| `platform_post_comments` | 平台评论 |
| `platform_post_stats` | 平台作品每日统计 |
| `platform_posts` | 平台作品 |
| `review_reports` | 复盘报告 |
| `sync_jobs` | 同步任务记录 |
| `topic_candidates` | 选题候选 |
| `topic_ideas` | 灵感池 |
| `transcripts` | ASR 转写/校对/原始文案 |
| `videos` | 本地素材 |
| `works` | 跨平台同作品 |


## `ai_prompts`

提示词版本

| 字段 | 类型 | 主键 | 可空 | 默认 | 说明 |
|---|---|---|---|---|---|
| `id` | INTEGER | ✔ | 否 |  |  |
| `key` | VARCHAR(40) |  | 否 |  |  |
| `version` | INTEGER |  | 否 | 1 |  |
| `content` | TEXT |  | 否 |  |  |
| `status` | VARCHAR(20) |  | 否 | enabled |  |
| `note` | TEXT |  | 否 |  |  |
| `created_at` | DATETIME |  | 否 | CallableColumnDefault(<function datetime.utcnow at 0x107d75900>) |  |

**索引**：`ix_ai_prompts_key`


## `app_kv`

KV 配置

| 字段 | 类型 | 主键 | 可空 | 默认 | 说明 |
|---|---|---|---|---|---|
| `key` | VARCHAR(60) | ✔ | 否 |  |  |
| `value` | TEXT |  | 否 |  |  |


## `background_tasks`

后台任务

| 字段 | 类型 | 主键 | 可空 | 默认 | 说明 |
|---|---|---|---|---|---|
| `id` | INTEGER | ✔ | 否 |  |  |
| `kind` | VARCHAR(50) |  | 否 |  |  |
| `status` | VARCHAR(20) |  | 否 | pending |  |
| `progress` | INTEGER |  | 否 | 0 |  |
| `payload` | TEXT |  | 否 | {} |  |
| `error` | TEXT |  | 否 |  |  |
| `created_at` | DATETIME |  | 否 | CallableColumnDefault(<function datetime.utcnow at 0x107e052d0>) |  |
| `updated_at` | DATETIME |  | 否 | CallableColumnDefault(<function datetime.utcnow at 0x107e05430>) |  |

**索引**：`ix_background_tasks_kind`


## `chat_conversations`

AI 会话

| 字段 | 类型 | 主键 | 可空 | 默认 | 说明 |
|---|---|---|---|---|---|
| `id` | INTEGER | ✔ | 否 |  |  |
| `title` | VARCHAR(200) |  | 否 | 新对话 |  |
| `created_at` | DATETIME |  | 否 | CallableColumnDefault(<function datetime.utcnow at 0x107cd8250>) |  |
| `updated_at` | DATETIME |  | 否 | CallableColumnDefault(<function datetime.utcnow at 0x107cd8300>) |  |


## `chat_messages`

AI 消息

| 字段 | 类型 | 主键 | 可空 | 默认 | 说明 |
|---|---|---|---|---|---|
| `id` | INTEGER | ✔ | 否 |  |  |
| `conversation_id` | INTEGER |  | 是 |  |  |
| `role` | VARCHAR(20) |  | 否 |  |  |
| `content` | TEXT |  | 否 |  |  |
| `created_at` | DATETIME |  | 否 | CallableColumnDefault(<function datetime.utcnow at 0x107cd87d0>) |  |

**索引**：`ix_chat_messages_conversation_id`

**外键**：`conversation_id` → `chat_conversations.id`


## `creator_account_snapshots`

账号每日快照

| 字段 | 类型 | 主键 | 可空 | 默认 | 说明 |
|---|---|---|---|---|---|
| `id` | INTEGER | ✔ | 否 |  |  |
| `account_id` | INTEGER |  | 否 |  |  |
| `snapshot_date` | VARCHAR(10) |  | 否 |  |  |
| `nickname` | VARCHAR(100) |  | 否 |  |  |
| `followers` | INTEGER |  | 否 | 0 |  |
| `likes_total` | INTEGER |  | 否 | 0 |  |
| `posts_total` | INTEGER |  | 否 | 0 |  |
| `following` | INTEGER |  | 否 | 0 |  |
| `raw` | TEXT |  | 否 | {} |  |
| `created_at` | DATETIME |  | 否 | CallableColumnDefault(<function datetime.utcnow at 0x107d76ae0>) |  |

**索引**：`ix_creator_account_snapshots_account_id`；`ix_creator_account_snapshots_snapshot_date`

**外键**：`account_id` → `creator_accounts.id`


## `creator_accounts`

平台账号

| 字段 | 类型 | 主键 | 可空 | 默认 | 说明 |
|---|---|---|---|---|---|
| `id` | INTEGER | ✔ | 否 |  |  |
| `creator_id` | INTEGER |  | 否 |  |  |
| `platform` | VARCHAR(20) |  | 否 |  |  |
| `nickname` | VARCHAR(100) |  | 否 |  |  |
| `home_link` | VARCHAR(500) |  | 否 |  |  |
| `platform_user_id` | VARCHAR(200) |  | 否 |  |  |
| `avatar_path` | VARCHAR(255) |  | 否 |  |  |
| `avatar_url` | VARCHAR(1000) |  | 否 |  |  |
| `extra_config` | TEXT |  | 否 | {} |  |
| `enabled` | BOOLEAN |  | 否 | True |  |
| `sync_frequency` | VARCHAR(10) |  | 否 | daily |  |
| `last_sync_at` | DATETIME |  | 是 |  |  |
| `sync_status` | VARCHAR(20) |  | 否 | idle |  |
| `sync_message` | TEXT |  | 否 |  |  |
| `created_at` | DATETIME |  | 否 | CallableColumnDefault(<function datetime.utcnow at 0x107d76090>) |  |

**索引**：`ix_creator_accounts_creator_id`；`ix_creator_accounts_platform`

**外键**：`creator_id` → `creators.id`


## `creators`

博主(主/对标)

| 字段 | 类型 | 主键 | 可空 | 默认 | 说明 |
|---|---|---|---|---|---|
| `id` | INTEGER | ✔ | 否 |  |  |
| `kind` | VARCHAR(10) |  | 否 | owner |  |
| `parent_id` | INTEGER |  | 是 |  |  |
| `name` | VARCHAR(100) |  | 否 |  |  |
| `note` | TEXT |  | 否 |  |  |
| `is_current` | BOOLEAN |  | 否 | False |  |
| `created_at` | DATETIME |  | 否 | CallableColumnDefault(<function datetime.utcnow at 0x107d75b10>) |  |

**索引**：`ix_creators_is_current`；`ix_creators_parent_id`

**外键**：`parent_id` → `creators.id`


## `draft_discussions`

双模型讨论留痕

| 字段 | 类型 | 主键 | 可空 | 默认 | 说明 |
|---|---|---|---|---|---|
| `id` | INTEGER | ✔ | 否 |  |  |
| `draft_id` | INTEGER |  | 否 |  |  |
| `round` | INTEGER |  | 否 | 0 |  |
| `actor` | VARCHAR(20) |  | 否 |  |  |
| `kind` | VARCHAR(20) |  | 否 |  |  |
| `content` | TEXT |  | 否 |  |  |
| `created_at` | DATETIME |  | 否 | CallableColumnDefault(<function datetime.utcnow at 0x107cd8ca0>) |  |

**索引**：`ix_draft_discussions_draft_id`

**外键**：`draft_id` → `drafts.id`


## `drafts`

脚本草稿

| 字段 | 类型 | 主键 | 可空 | 默认 | 说明 |
|---|---|---|---|---|---|
| `id` | INTEGER | ✔ | 否 |  |  |
| `creator_id` | INTEGER |  | 是 |  |  |
| `video_id` | INTEGER |  | 是 |  |  |
| `title` | VARCHAR(255) |  | 否 |  |  |
| `cover_text` | VARCHAR(100) |  | 否 |  |  |
| `script` | TEXT |  | 否 |  |  |
| `platform_shells` | TEXT |  | 否 | {} |  |
| `source` | VARCHAR(20) |  | 否 | manual |  |
| `original_script` | TEXT |  | 否 |  |  |
| `status` | VARCHAR(20) |  | 否 | draft |  |
| `version` | INTEGER |  | 否 | 1 |  |
| `created_at` | DATETIME |  | 否 | CallableColumnDefault(<function datetime.utcnow at 0x107cd9590>) |  |
| `updated_at` | DATETIME |  | 否 | CallableColumnDefault(<function datetime.utcnow at 0x107cd9430>) |  |

**索引**：`ix_drafts_creator_id`；`ix_drafts_video_id`

**外键**：`creator_id` → `creators.id`；`video_id` → `videos.id`


## `feedback`

草稿打分/采用

| 字段 | 类型 | 主键 | 可空 | 默认 | 说明 |
|---|---|---|---|---|---|
| `id` | INTEGER | ✔ | 否 |  |  |
| `draft_id` | INTEGER |  | 否 |  |  |
| `liked` | BOOLEAN |  | 是 |  |  |
| `rating` | INTEGER |  | 是 |  |  |
| `comment` | TEXT |  | 否 |  |  |
| `hook_score` | INTEGER |  | 是 |  |  |
| `pace_score` | INTEGER |  | 是 |  |  |
| `ending_score` | INTEGER |  | 是 |  |  |
| `style_score` | INTEGER |  | 是 |  |  |
| `created_at` | DATETIME |  | 否 | CallableColumnDefault(<function datetime.utcnow at 0x107cd9fe0>) |  |

**索引**：`ix_feedback_draft_id`

**外键**：`draft_id` → `drafts.id`


## `hot_topics`

热点

| 字段 | 类型 | 主键 | 可空 | 默认 | 说明 |
|---|---|---|---|---|---|
| `id` | INTEGER | ✔ | 否 |  |  |
| `platform` | VARCHAR(20) |  | 否 |  |  |
| `title` | VARCHAR(255) |  | 否 |  |  |
| `heat` | VARCHAR(50) |  | 否 |  |  |
| `url` | VARCHAR(500) |  | 否 |  |  |
| `raw` | TEXT |  | 否 | {} |  |
| `topic_date` | VARCHAR(10) |  | 否 |  |  |
| `created_at` | DATETIME |  | 否 | CallableColumnDefault(<function datetime.utcnow at 0x107cda4b0>) |  |

**索引**：`ix_hot_topics_platform`；`ix_hot_topics_topic_date`


## `metrics_snapshots`

本地素材每日指标

| 字段 | 类型 | 主键 | 可空 | 默认 | 说明 |
|---|---|---|---|---|---|
| `id` | INTEGER | ✔ | 否 |  |  |
| `video_id` | INTEGER |  | 否 |  |  |
| `snapshot_date` | VARCHAR(10) |  | 否 |  |  |
| `plays` | INTEGER |  | 否 | 0 |  |
| `likes` | INTEGER |  | 否 | 0 |  |
| `favorites` | INTEGER |  | 否 | 0 |  |
| `comments` | INTEGER |  | 否 | 0 |  |
| `followers_gained` | INTEGER |  | 否 | 0 |  |
| `source` | VARCHAR(20) |  | 否 | manual |  |
| `created_at` | DATETIME |  | 否 | CallableColumnDefault(<function datetime.utcnow at 0x107cdbb60>) |  |

**索引**：`ix_metrics_snapshots_snapshot_date`；`ix_metrics_snapshots_video_id`

**外键**：`video_id` → `videos.id`


## `notifications`

通知

| 字段 | 类型 | 主键 | 可空 | 默认 | 说明 |
|---|---|---|---|---|---|
| `id` | INTEGER | ✔ | 否 |  |  |
| `kind` | VARCHAR(30) |  | 否 |  |  |
| `status` | VARCHAR(10) |  | 否 | done |  |
| `title` | VARCHAR(200) |  | 否 |  |  |
| `message` | TEXT |  | 否 |  |  |
| `target` | VARCHAR(255) |  | 否 | /home |  |
| `read` | BOOLEAN |  | 否 | False |  |
| `created_at` | DATETIME |  | 否 | CallableColumnDefault(<function datetime.utcnow at 0x107d74720>) |  |

**索引**：`ix_notifications_read`；`ix_notifications_kind`


## `persona_tags`

人设标签(风格/赛道/红线/金句)

| 字段 | 类型 | 主键 | 可空 | 默认 | 说明 |
|---|---|---|---|---|---|
| `id` | INTEGER | ✔ | 否 |  |  |
| `creator_id` | INTEGER |  | 是 |  |  |
| `label` | VARCHAR(100) |  | 否 |  |  |
| `description` | TEXT |  | 否 |  |  |
| `category` | VARCHAR(20) |  | 否 | style |  |
| `source` | VARCHAR(20) |  | 否 | ai |  |
| `status` | VARCHAR(20) |  | 否 | suggested |  |
| `version` | INTEGER |  | 否 | 1 |  |
| `created_at` | DATETIME |  | 否 | CallableColumnDefault(<function datetime.utcnow at 0x107d74930>) |  |

**索引**：`ix_persona_tags_creator_id`；`ix_persona_tags_label`

**外键**：`creator_id` → `creators.id`


## `pipeline_runs`

流水线运行

| 字段 | 类型 | 主键 | 可空 | 默认 | 说明 |
|---|---|---|---|---|---|
| `id` | INTEGER | ✔ | 否 |  |  |
| `run_date` | VARCHAR(10) |  | 否 |  |  |
| `status` | VARCHAR(20) |  | 否 | running |  |
| `candidates_count` | INTEGER |  | 否 | 0 |  |
| `generated_count` | INTEGER |  | 否 | 0 |  |
| `error` | TEXT |  | 否 |  |  |
| `created_at` | DATETIME |  | 否 | CallableColumnDefault(<function datetime.utcnow at 0x107d74e00>) |  |
| `updated_at` | DATETIME |  | 否 | CallableColumnDefault(<function datetime.utcnow at 0x107d75170>) |  |

**索引**：`ix_pipeline_runs_run_date`


## `platform_post_comments`

平台评论

| 字段 | 类型 | 主键 | 可空 | 默认 | 说明 |
|---|---|---|---|---|---|
| `id` | INTEGER | ✔ | 否 |  |  |
| `post_id` | INTEGER |  | 否 |  |  |
| `platform` | VARCHAR(20) |  | 否 |  |  |
| `text` | TEXT |  | 否 |  |  |
| `user_nick` | VARCHAR(100) |  | 否 |  |  |
| `created_at` | DATETIME |  | 否 | CallableColumnDefault(<function datetime.utcnow at 0x107e04460>) |  |

**索引**：`ix_platform_post_comments_post_id`

**外键**：`post_id` → `platform_posts.id`


## `platform_post_stats`

平台作品每日统计

| 字段 | 类型 | 主键 | 可空 | 默认 | 说明 |
|---|---|---|---|---|---|
| `id` | INTEGER | ✔ | 否 |  |  |
| `post_id` | INTEGER |  | 否 |  |  |
| `stat_date` | VARCHAR(10) |  | 否 |  |  |
| `plays` | INTEGER |  | 否 | 0 |  |
| `likes` | INTEGER |  | 否 | 0 |  |
| `favorites` | INTEGER |  | 否 | 0 |  |
| `shares` | INTEGER |  | 否 | 0 |  |
| `comments` | INTEGER |  | 否 | 0 |  |
| `extra` | TEXT |  | 否 | {} |  |
| `source` | VARCHAR(20) |  | 否 | tikhub |  |
| `created_at` | DATETIME |  | 否 | CallableColumnDefault(<function datetime.utcnow at 0x107d77d70>) |  |

**索引**：`ix_platform_post_stats_stat_date`；`ix_platform_post_stats_post_id`

**外键**：`post_id` → `platform_posts.id`


## `platform_posts`

平台作品

| 字段 | 类型 | 主键 | 可空 | 默认 | 说明 |
|---|---|---|---|---|---|
| `id` | INTEGER | ✔ | 否 |  |  |
| `account_id` | INTEGER |  | 否 |  |  |
| `platform` | VARCHAR(20) |  | 否 |  |  |
| `platform_post_id` | VARCHAR(200) |  | 否 |  |  |
| `title` | VARCHAR(500) |  | 否 |  |  |
| `desc` | TEXT |  | 否 |  |  |
| `tags` | TEXT |  | 否 | [] |  |
| `is_ad` | BOOLEAN |  | 否 | False |  |
| `ad_price` | INTEGER |  | 是 |  |  |
| `cover_url` | VARCHAR(1000) |  | 否 |  |  |
| `cover_path` | VARCHAR(255) |  | 否 |  |  |
| `video_url` | VARCHAR(1000) |  | 否 |  |  |
| `publish_time` | DATETIME |  | 是 |  |  |
| `raw` | TEXT |  | 否 | {} |  |
| `local_video_id` | INTEGER |  | 是 |  |  |
| `work_id` | INTEGER |  | 是 |  |  |
| `created_at` | DATETIME |  | 否 | CallableColumnDefault(<function datetime.utcnow at 0x107d771c0>) |  |
| `updated_at` | DATETIME |  | 否 | CallableColumnDefault(<function datetime.utcnow at 0x107d77270>) |  |

**索引**：`ix_platform_posts_work_id`；`ix_platform_posts_platform`；`ix_platform_posts_platform_post_id`；`ix_platform_posts_account_id`

**外键**：`account_id` → `creator_accounts.id`；`local_video_id` → `videos.id`；`work_id` → `works.id`


## `review_reports`

复盘报告

| 字段 | 类型 | 主键 | 可空 | 默认 | 说明 |
|---|---|---|---|---|---|
| `id` | INTEGER | ✔ | 否 |  |  |
| `run_date` | VARCHAR(10) |  | 否 |  |  |
| `report_type` | VARCHAR(20) |  | 否 | full |  |
| `content` | TEXT |  | 否 | {} |  |
| `created_at` | DATETIME |  | 否 | CallableColumnDefault(<function datetime.utcnow at 0x107d740f0>) |  |

**索引**：`ix_review_reports_run_date`


## `sync_jobs`

同步任务记录

| 字段 | 类型 | 主键 | 可空 | 默认 | 说明 |
|---|---|---|---|---|---|
| `id` | INTEGER | ✔ | 否 |  |  |
| `job_type` | VARCHAR(20) |  | 否 |  |  |
| `scope` | VARCHAR(20) |  | 否 |  |  |
| `creator_id` | INTEGER |  | 是 |  |  |
| `account_id` | INTEGER |  | 是 |  |  |
| `post_id` | INTEGER |  | 是 |  |  |
| `status` | VARCHAR(20) |  | 否 | running |  |
| `message` | TEXT |  | 否 |  |  |
| `stats` | TEXT |  | 否 | {} |  |
| `started_at` | DATETIME |  | 否 | CallableColumnDefault(<function datetime.utcnow at 0x107e04a90>) |  |
| `finished_at` | DATETIME |  | 是 |  |  |
| `created_at` | DATETIME |  | 否 | CallableColumnDefault(<function datetime.utcnow at 0x107e04bf0>) |  |

**索引**：`ix_sync_jobs_job_type`

**外键**：`creator_id` → `creators.id`；`account_id` → `creator_accounts.id`；`post_id` → `platform_posts.id`


## `topic_candidates`

选题候选

| 字段 | 类型 | 主键 | 可空 | 默认 | 说明 |
|---|---|---|---|---|---|
| `id` | INTEGER | ✔ | 否 |  |  |
| `run_date` | VARCHAR(10) |  | 否 |  |  |
| `hot_topic_id` | INTEGER |  | 是 |  |  |
| `title` | VARCHAR(255) |  | 否 |  |  |
| `platform` | VARCHAR(20) |  | 否 |  |  |
| `score` | INTEGER |  | 否 | 0 |  |
| `reason` | TEXT |  | 否 |  |  |
| `draft_id` | INTEGER |  | 是 |  |  |
| `created_at` | DATETIME |  | 否 | CallableColumnDefault(<function datetime.utcnow at 0x107cdaa30>) |  |

**索引**：`ix_topic_candidates_run_date`

**外键**：`hot_topic_id` → `hot_topics.id`；`draft_id` → `drafts.id`


## `topic_ideas`

灵感池

| 字段 | 类型 | 主键 | 可空 | 默认 | 说明 |
|---|---|---|---|---|---|
| `id` | INTEGER | ✔ | 否 |  |  |
| `source` | VARCHAR(20) |  | 否 | hot |  |
| `platform` | VARCHAR(20) |  | 否 |  |  |
| `title` | VARCHAR(255) |  | 否 |  |  |
| `detail` | TEXT |  | 否 |  |  |
| `post_id` | INTEGER |  | 是 |  |  |
| `post_title` | VARCHAR(500) |  | 否 |  |  |
| `creator_id` | INTEGER |  | 是 |  |  |
| `snapshot_date` | VARCHAR(10) |  | 否 |  |  |
| `used` | BOOLEAN |  | 否 | False |  |
| `created_at` | DATETIME |  | 否 | CallableColumnDefault(<function datetime.utcnow at 0x107cdb270>) |  |

**索引**：`ix_topic_ideas_snapshot_date`；`ix_topic_ideas_creator_id`；`ix_topic_ideas_platform`；`ix_topic_ideas_used`

**外键**：`post_id` → `platform_posts.id`；`creator_id` → `creators.id`


## `transcripts`

ASR 转写/校对/原始文案

| 字段 | 类型 | 主键 | 可空 | 默认 | 说明 |
|---|---|---|---|---|---|
| `id` | INTEGER | ✔ | 否 |  |  |
| `video_id` | INTEGER |  | 否 |  |  |
| `source_text` | TEXT |  | 否 |  |  |
| `transcript_text` | TEXT |  | 否 |  |  |
| `corrected_text` | TEXT |  | 否 |  |  |
| `asr_status` | VARCHAR(20) |  | 否 | pending |  |
| `created_at` | DATETIME |  | 否 | CallableColumnDefault(<function datetime.utcnow at 0x107e06560>) |  |

**索引**：`ix_transcripts_video_id`

**外键**：`video_id` → `videos.id`


## `videos`

本地素材

| 字段 | 类型 | 主键 | 可空 | 默认 | 说明 |
|---|---|---|---|---|---|
| `id` | INTEGER | ✔ | 否 |  |  |
| `filename` | VARCHAR(255) |  | 否 |  |  |
| `title` | VARCHAR(255) |  | 否 |  |  |
| `cover_path` | VARCHAR(255) |  | 否 |  |  |
| `platforms` | TEXT |  | 否 | [] |  |
| `creator_id` | INTEGER |  | 是 |  |  |
| `platform_post_id` | VARCHAR(200) |  | 否 |  |  |
| `work_id` | INTEGER |  | 是 |  |  |
| `status` | VARCHAR(20) |  | 否 | planned |  |
| `planned_publish_at` | DATETIME |  | 是 |  |  |
| `published_at` | DATETIME |  | 是 |  |  |
| `is_ad` | BOOLEAN |  | 否 | False |  |
| `ad_price` | INTEGER |  | 是 |  |  |
| `main_topics` | TEXT |  | 否 | [] |  |
| `tags` | TEXT |  | 否 | [] |  |
| `tags_confirmed` | BOOLEAN |  | 否 | False |  |
| `created_at` | DATETIME |  | 否 | CallableColumnDefault(<function datetime.utcnow at 0x107e05bc0>) |  |

**索引**：`ix_videos_work_id`；`ix_videos_creator_id`；`ix_videos_filename`

**外键**：`creator_id` → `creators.id`；`work_id` → `works.id`


## `works`

跨平台同作品

| 字段 | 类型 | 主键 | 可空 | 默认 | 说明 |
|---|---|---|---|---|---|
| `id` | INTEGER | ✔ | 否 |  |  |
| `creator_id` | INTEGER |  | 是 |  |  |
| `title` | VARCHAR(500) |  | 否 |  |  |
| `cover_path` | VARCHAR(255) |  | 否 |  |  |
| `created_at` | DATETIME |  | 否 | CallableColumnDefault(<function datetime.utcnow at 0x107e06ae0>) |  |
| `updated_at` | DATETIME |  | 否 | CallableColumnDefault(<function datetime.utcnow at 0x107e06c40>) |  |

**索引**：`ix_works_creator_id`

**外键**：`creator_id` → `creators.id`

## 附录：运行时补充索引（R-061，启动时幂等创建，不在模型 index=True）
| 表 | 索引 | 目的 |
|---|---|---|
| platform_posts | ix_platform_posts_local_video_id | 素材绑定查询 |
| platform_posts | ix_platform_posts_publish_time | 云端列表按时间排序 |
| videos | ix_videos_platform_post_id | 平台绑定查询 |
| notifications | ix_notifications_created_at | 清理/按时间检索 |
| platform_posts | ux_platform_posts_local_platform（唯一部分索引，R-061-D1） | 绑定单事实源：同一本地素材在单平台只绑一条 |

## 附录 B：素材语义与命名约定（R-033/R-058/R-061）
- 本地素材无真实文件时 filename 用占位名 `__cloud__{post_id}`（唯一约束友好；前端据此不显示“语音转文字”）
- 有真实文件的命名：`标题-视频.{ext}` / `标题-封面.{ext}`（安全清洗 + 重名 -2/-3）；存量平台封面已于 2026-09-05 批量回填改名（备份 echo_pre_cover_rename_*.db）
- 平台作品↔本地素材绑定以 `platform_posts.local_video_id` 为单事实源（R-061-D1 已加唯一部分索引）
