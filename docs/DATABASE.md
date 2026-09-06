# 数据库表结构（自动生成 + 人工注释）

> 表结构来源：`backend/app/models/*.py`（SQLAlchemy 2.x 声明式），由模型元数据生成，保证与代码一致；说明注释为人工维护。
> 数据库：SQLite 单文件。路径由 `.env` 的 `ECHO_DB_PATH` 决定（未配置时由 `ECHO_DATA_DIR` 派生为 `data/echo.db`；本项目 .env 当前指向 `echo_resource/echo.db`），运行时数据目录见 QUICKSTART。
> 时间列统一存北京时间（core/timeutil.now，R-066）。JSON 类文本列默认 `[]` / `{}`。

## 表总览（26 张）

| 表 | 说明 |
|---|---|
| `ai_prompts` | AI 提示词版本库（R-021）：key 标识用途，version 递增，status=enabled 为当前生效版，content 为提示词正文；支持历史回滚与自动优化候选。 |
| `app_kv` | 轻量键值表：预算计数(tikhub_budget_used:日期)、一次性迁移标记、R-022 优化节流计数等。 |
| `background_tasks` | 后台任务表：start_task 创建的异步任务（素材转写/每日流水线/平台同步/AI 生成等），记录 kind/payload/status/progress/error，结束自动写通知。 |
| `chat_conversations` | AI 对话会话（R-017）：标题 + 创建/更新时间，单用户多会话。 |
| `chat_messages` | AI 对话消息：角色（user/assistant/system）、内容、会话归属 conversation_id、是否流式完成等。 |
| `creator_account_snapshots` | 博主×平台账号主页指标按天快照：粉丝/获赞/作品数/关注数 + raw 原文，支撑涨粉曲线。(account_id, snapshot_date) 唯一。 |
| `creator_accounts` | 博主在某平台的账号配置：主页链接、解析出的平台 ID、增强配置(extra_config JSON)、同步开关/频率/最后同步时间/头像。 |
| `creators` | 博主：kind=owner 主博主 / benchmark 对标（parent_id 挂主博主）；is_current 标记当前主博主，切换时素材/人设/复盘整套随动。 |
| `draft_discussions` | 双模型讨论留痕（R-023）：围绕草稿的每轮讨论消息（模型/轮次/内容）。 |
| `drafts` | 脚本草稿：每日选题/手动生成的 AI 稿 + 作者改写稿（source 留底供改稿差异分析）；状态 used/…；素材双向关联 video_id。 |
| `feedback` | 作者反馈：草稿 1-5 星/采用与否，R-022 后含四维分节分（hook/pace/ending/style_score），信号回流人设学习。 |
| `hot_topics` | 热点记录：平台+标题+日期去重；供选题匹配（R-025 扩充来源，R-065 后走 TikHub 热搜）。 |
| `metrics_snapshots` | 本地素材(videos)每日指标快照：手动录入/批量导入/抓取/平台同步聚合，驱动看板增长曲线与复盘。 |
| `notifications` | 右上角通知（R-019）：异步任务完成/失败，含目标页 target 与已读。 |
| `persona_tags` | 人设档案版本：tags JSON + 描述 + 红线/边界 + 状态(suggested/enabled…)；版本化，AI 建议需作者确认。 |
| `pipeline_runs` | 每日流水线运行记录：当日幂等（同 run_date 不重跑）、成功/失败状态与摘要。 |
| `platform_post_comments` | 平台作品评论（入库本地查询，R-067 后带点赞数 likes，按点赞 Top50 入库展示）：post_id+text 去重。 |
| `platform_post_stats` | 平台作品互动指标按天快照：播放/点赞/收藏/评论/转发 + extra 平台特有字段。(post_id, stat_date) 唯一。 |
| `platform_posts` | 云端作品（平台原样数据，默认无本地视频）：platform+platform_post_id 唯一；local_video_id 绑定本地素材、work_id 跨平台同作品合并。 |
| `review_reports` | 复盘报告：A 报表/B 归因/C 建议/D 赛道方向的产出记录与原文。 |
| `sync_jobs` | 平台同步任务留痕：类型(initial/daily/weekly/single/manual)/账号/状态/统计 + R-070 实时进度(progress_done/total/note)。 |
| `topic_candidates` | 选题候选：热点匹配/生成的候选稿，供每日选题流水线产出。 |
| `topic_ideas` | 选题池灵感（R-028）：来源=各平台热点或作品评论区（source=hot/comment），人工挑选，不自动推送。 |
| `transcripts` | 转写稿：ASR 原文(transcript_text)、AI 校对稿(source_text)与状态；video_id 唯一。 |
| `videos` | 本地素材：上传/导入视频元数据 + 封面 + 平台/赛道多选(JSON) + 发布状态/时间 + 绑定平台作品/合并作品。 |
| `works` | 跨平台同作品：同一内容三平台自动/手动合并，title 规范化去重，承载素材库云端合并卡。 |

## 核心数据流关系速览

- 博主体系：`creators`（owner/benchmark）→ `creator_accounts`（每平台账号）→ `creator_account_snapshots`（主页按天）
- 云端作品：`creator_accounts` → `platform_posts` → `platform_post_stats`（按天指标）/ `platform_post_comments`（评论 Top50）；`platform_posts.work_id` → `works`（跨平台同作品合并）；`local_video_id` → `videos`（转本地素材）
- 本地素材：`videos` → `transcripts`（转写稿）/ `metrics_snapshots`（按天聚合指标）；`videos.work_id` 与 `platform_post_id` 关联云端
- 内容生产：`hot_topics` → `topic_candidates` → `drafts` → `feedback` / `draft_discussions`
- 任务/通知：`background_tasks` + `sync_jobs` 记录后台工作，结束写 `notifications`；`app_kv` 存预算/迁移标记

---

## `ai_prompts`

AI 提示词版本库（R-021）：key 标识用途，version 递增，status=enabled 为当前生效版，content 为提示词正文；支持历史回滚与自动优化候选。

| 字段 | 类型 | 主键 | 可空 | 默认 |
|---|---|---|---|---|
| `id` | INTEGER | ✔ | 否 |  |
| `key` | VARCHAR(40) |  | 否 |  |
| `version` | INTEGER |  | 否 | 1 |
| `content` | TEXT |  | 否 |  |
| `status` | VARCHAR(20) |  | 否 | enabled |
| `note` | TEXT |  | 否 |  |
| `created_at` | DATETIME |  | 否 | 当前时间（北京） |

**索引**：`ix_ai_prompts_key`（key）

**唯一约束**：`uq_prompt_version`（key, version）

---

## `app_kv`

轻量键值表：预算计数(tikhub_budget_used:日期)、一次性迁移标记、R-022 优化节流计数等。

| 字段 | 类型 | 主键 | 可空 | 默认 |
|---|---|---|---|---|
| `key` | VARCHAR(60) | ✔ | 否 |  |
| `value` | TEXT |  | 否 |  |

---

## `background_tasks`

后台任务表：start_task 创建的异步任务（素材转写/每日流水线/平台同步/AI 生成等），记录 kind/payload/status/progress/error，结束自动写通知。

| 字段 | 类型 | 主键 | 可空 | 默认 |
|---|---|---|---|---|
| `id` | INTEGER | ✔ | 否 |  |
| `kind` | VARCHAR(50) |  | 否 |  |
| `status` | VARCHAR(20) |  | 否 | pending |
| `progress` | INTEGER |  | 否 | 0 |
| `payload` | TEXT |  | 否 | {} |
| `error` | TEXT |  | 否 |  |
| `created_at` | DATETIME |  | 否 | 当前时间（北京） |
| `updated_at` | DATETIME |  | 否 | 当前时间（北京） |

**索引**：`ix_background_tasks_kind`（kind）

---

## `chat_conversations`

AI 对话会话（R-017）：标题 + 创建/更新时间，单用户多会话。

| 字段 | 类型 | 主键 | 可空 | 默认 |
|---|---|---|---|---|
| `id` | INTEGER | ✔ | 否 |  |
| `title` | VARCHAR(200) |  | 否 | 新对话 |
| `created_at` | DATETIME |  | 否 | 当前时间（北京） |
| `updated_at` | DATETIME |  | 否 | 当前时间（北京） |

---

## `chat_messages`

AI 对话消息：角色（user/assistant/system）、内容、会话归属 conversation_id、是否流式完成等。

| 字段 | 类型 | 主键 | 可空 | 默认 |
|---|---|---|---|---|
| `id` | INTEGER | ✔ | 否 |  |
| `conversation_id` | INTEGER |  | 是 |  |
| `role` | VARCHAR(20) |  | 否 |  |
| `content` | TEXT |  | 否 |  |
| `created_at` | DATETIME |  | 否 | 当前时间（北京） |

**索引**：`ix_chat_messages_conversation_id`（conversation_id）

**外键**：`conversation_id` → `chat_conversations.id`

---

## `creator_account_snapshots`

博主×平台账号主页指标按天快照：粉丝/获赞/作品数/关注数 + raw 原文，支撑涨粉曲线。(account_id, snapshot_date) 唯一。

| 字段 | 类型 | 主键 | 可空 | 默认 |
|---|---|---|---|---|
| `id` | INTEGER | ✔ | 否 |  |
| `account_id` | INTEGER |  | 否 |  |
| `snapshot_date` | VARCHAR(10) |  | 否 |  |
| `nickname` | VARCHAR(100) |  | 否 |  |
| `followers` | INTEGER |  | 否 | 0 |
| `likes_total` | INTEGER |  | 否 | 0 |
| `posts_total` | INTEGER |  | 否 | 0 |
| `following` | INTEGER |  | 否 | 0 |
| `raw` | TEXT |  | 否 | {} |
| `created_at` | DATETIME |  | 否 | 当前时间（北京） |

**索引**：`ix_creator_account_snapshots_snapshot_date`（snapshot_date）；`ix_creator_account_snapshots_account_id`（account_id）

**唯一约束**：`uq_acct_snap`（account_id, snapshot_date）

**外键**：`account_id` → `creator_accounts.id`

---

## `creator_accounts`

博主在某平台的账号配置：主页链接、解析出的平台 ID、增强配置(extra_config JSON)、同步开关/频率/最后同步时间/头像。

| 字段 | 类型 | 主键 | 可空 | 默认 |
|---|---|---|---|---|
| `id` | INTEGER | ✔ | 否 |  |
| `creator_id` | INTEGER |  | 否 |  |
| `platform` | VARCHAR(20) |  | 否 |  |
| `nickname` | VARCHAR(100) |  | 否 |  |
| `home_link` | VARCHAR(500) |  | 否 |  |
| `platform_user_id` | VARCHAR(200) |  | 否 |  |
| `avatar_path` | VARCHAR(255) |  | 否 |  |
| `avatar_url` | VARCHAR(1000) |  | 否 |  |
| `extra_config` | TEXT |  | 否 | {} |
| `enabled` | BOOLEAN |  | 否 | true |
| `sync_frequency` | VARCHAR(10) |  | 否 | daily |
| `last_sync_at` | DATETIME |  | 是 |  |
| `sync_status` | VARCHAR(20) |  | 否 | idle |
| `sync_message` | TEXT |  | 否 |  |
| `created_at` | DATETIME |  | 否 | 当前时间（北京） |

**索引**：`ix_creator_accounts_platform`（platform）；`ix_creator_accounts_creator_id`（creator_id）

**外键**：`creator_id` → `creators.id`

**关系**：
- creators 1—N creator_accounts
- creator_accounts 1—N creator_account_snapshots / platform_posts

---

## `creators`

博主：kind=owner 主博主 / benchmark 对标（parent_id 挂主博主）；is_current 标记当前主博主，切换时素材/人设/复盘整套随动。

| 字段 | 类型 | 主键 | 可空 | 默认 |
|---|---|---|---|---|
| `id` | INTEGER | ✔ | 否 |  |
| `kind` | VARCHAR(10) |  | 否 | owner |
| `parent_id` | INTEGER |  | 是 |  |
| `name` | VARCHAR(100) |  | 否 |  |
| `note` | TEXT |  | 否 |  |
| `is_current` | BOOLEAN |  | 否 | false |
| `created_at` | DATETIME |  | 否 | 当前时间（北京） |

**索引**：`ix_creators_is_current`（is_current）；`ix_creators_parent_id`（parent_id）

**外键**：`parent_id` → `creators.id`

**关系**：
- creators 1—N persona_tags
- creators 1—N creators（benchmark.parent_id）

---

## `draft_discussions`

双模型讨论留痕（R-023）：围绕草稿的每轮讨论消息（模型/轮次/内容）。

| 字段 | 类型 | 主键 | 可空 | 默认 |
|---|---|---|---|---|
| `id` | INTEGER | ✔ | 否 |  |
| `draft_id` | INTEGER |  | 否 |  |
| `round` | INTEGER |  | 否 | 0 |
| `actor` | VARCHAR(20) |  | 否 |  |
| `kind` | VARCHAR(20) |  | 否 |  |
| `content` | TEXT |  | 否 |  |
| `created_at` | DATETIME |  | 否 | 当前时间（北京） |

**索引**：`ix_draft_discussions_draft_id`（draft_id）

**外键**：`draft_id` → `drafts.id`

---

## `drafts`

脚本草稿：每日选题/手动生成的 AI 稿 + 作者改写稿（source 留底供改稿差异分析）；状态 used/…；素材双向关联 video_id。

| 字段 | 类型 | 主键 | 可空 | 默认 |
|---|---|---|---|---|
| `id` | INTEGER | ✔ | 否 |  |
| `creator_id` | INTEGER |  | 是 |  |
| `video_id` | INTEGER |  | 是 |  |
| `title` | VARCHAR(255) |  | 否 |  |
| `cover_text` | VARCHAR(100) |  | 否 |  |
| `script` | TEXT |  | 否 |  |
| `platform_shells` | TEXT |  | 否 | {} |
| `source` | VARCHAR(20) |  | 否 | manual |
| `original_script` | TEXT |  | 否 |  |
| `status` | VARCHAR(20) |  | 否 | draft |
| `version` | INTEGER |  | 否 | 1 |
| `created_at` | DATETIME |  | 否 | 当前时间（北京） |
| `updated_at` | DATETIME |  | 否 | 当前时间（北京） |

**索引**：`ix_drafts_video_id`（video_id）；`ix_drafts_creator_id`（creator_id）

**外键**：`creator_id` → `creators.id`；`video_id` → `videos.id`

**关系**：
- drafts 1—N feedback（打分）
- drafts 1—N draft_discussions（双模型讨论）

---

## `feedback`

作者反馈：草稿 1-5 星/采用与否，R-022 后含四维分节分（hook/pace/ending/style_score），信号回流人设学习。

| 字段 | 类型 | 主键 | 可空 | 默认 |
|---|---|---|---|---|
| `id` | INTEGER | ✔ | 否 |  |
| `draft_id` | INTEGER |  | 否 |  |
| `liked` | BOOLEAN |  | 是 |  |
| `rating` | INTEGER |  | 是 |  |
| `comment` | TEXT |  | 否 |  |
| `hook_score` | INTEGER |  | 是 |  |
| `pace_score` | INTEGER |  | 是 |  |
| `ending_score` | INTEGER |  | 是 |  |
| `style_score` | INTEGER |  | 是 |  |
| `created_at` | DATETIME |  | 否 | 当前时间（北京） |

**索引**：`ix_feedback_draft_id`（draft_id）

**外键**：`draft_id` → `drafts.id`

---

## `hot_topics`

热点记录：平台+标题+日期去重；供选题匹配（R-025 扩充来源，R-065 后走 TikHub 热搜）。

| 字段 | 类型 | 主键 | 可空 | 默认 |
|---|---|---|---|---|
| `id` | INTEGER | ✔ | 否 |  |
| `platform` | VARCHAR(20) |  | 否 |  |
| `title` | VARCHAR(255) |  | 否 |  |
| `heat` | VARCHAR(50) |  | 否 |  |
| `url` | VARCHAR(500) |  | 否 |  |
| `raw` | TEXT |  | 否 | {} |
| `topic_date` | VARCHAR(10) |  | 否 |  |
| `created_at` | DATETIME |  | 否 | 当前时间（北京） |

**索引**：`ix_hot_topics_topic_date`（topic_date）；`ix_hot_topics_platform`（platform）

**唯一约束**：`uq_hot`（platform, title, topic_date）

**关系**：
- hot_topics → topic_candidates（匹配选题）→ drafts（生成稿）

---

## `metrics_snapshots`

本地素材(videos)每日指标快照：手动录入/批量导入/抓取/平台同步聚合，驱动看板增长曲线与复盘。

| 字段 | 类型 | 主键 | 可空 | 默认 |
|---|---|---|---|---|
| `id` | INTEGER | ✔ | 否 |  |
| `video_id` | INTEGER |  | 否 |  |
| `snapshot_date` | VARCHAR(10) |  | 否 |  |
| `plays` | INTEGER |  | 否 | 0 |
| `likes` | INTEGER |  | 否 | 0 |
| `favorites` | INTEGER |  | 否 | 0 |
| `comments` | INTEGER |  | 否 | 0 |
| `followers_gained` | INTEGER |  | 否 | 0 |
| `source` | VARCHAR(20) |  | 否 | manual |
| `created_at` | DATETIME |  | 否 | 当前时间（北京） |

**索引**：`ix_metrics_snapshots_video_id`（video_id）；`ix_metrics_snapshots_snapshot_date`（snapshot_date）

**唯一约束**：`uq_metrics`（video_id, snapshot_date）

**外键**：`video_id` → `videos.id`

---

## `notifications`

右上角通知（R-019）：异步任务完成/失败，含目标页 target 与已读。

| 字段 | 类型 | 主键 | 可空 | 默认 |
|---|---|---|---|---|
| `id` | INTEGER | ✔ | 否 |  |
| `kind` | VARCHAR(30) |  | 否 |  |
| `status` | VARCHAR(10) |  | 否 | done |
| `title` | VARCHAR(200) |  | 否 |  |
| `message` | TEXT |  | 否 |  |
| `target` | VARCHAR(255) |  | 否 | /home |
| `read` | BOOLEAN |  | 否 | false |
| `created_at` | DATETIME |  | 否 | 当前时间（北京） |

**索引**：`ix_notifications_kind`（kind）；`ix_notifications_read`（read）

---

## `persona_tags`

人设档案版本：tags JSON + 描述 + 红线/边界 + 状态(suggested/enabled…)；版本化，AI 建议需作者确认。

| 字段 | 类型 | 主键 | 可空 | 默认 |
|---|---|---|---|---|
| `id` | INTEGER | ✔ | 否 |  |
| `creator_id` | INTEGER |  | 是 |  |
| `label` | VARCHAR(100) |  | 否 |  |
| `description` | TEXT |  | 否 |  |
| `category` | VARCHAR(20) |  | 否 | style |
| `source` | VARCHAR(20) |  | 否 | ai |
| `status` | VARCHAR(20) |  | 否 | suggested |
| `version` | INTEGER |  | 否 | 1 |
| `created_at` | DATETIME |  | 否 | 当前时间（北京） |

**索引**：`ix_persona_tags_creator_id`（creator_id）；`ix_persona_tags_label`（label）

**外键**：`creator_id` → `creators.id`

---

## `pipeline_runs`

每日流水线运行记录：当日幂等（同 run_date 不重跑）、成功/失败状态与摘要。

| 字段 | 类型 | 主键 | 可空 | 默认 |
|---|---|---|---|---|
| `id` | INTEGER | ✔ | 否 |  |
| `run_date` | VARCHAR(10) |  | 否 |  |
| `status` | VARCHAR(20) |  | 否 | running |
| `candidates_count` | INTEGER |  | 否 | 0 |
| `generated_count` | INTEGER |  | 否 | 0 |
| `error` | TEXT |  | 否 |  |
| `created_at` | DATETIME |  | 否 | 当前时间（北京） |
| `updated_at` | DATETIME |  | 否 | 当前时间（北京） |

**索引**：`ix_pipeline_runs_run_date`（run_date）

---

## `platform_post_comments`

平台作品评论（入库本地查询，R-067 后带点赞数 likes，按点赞 Top50 入库展示）：post_id+text 去重。

| 字段 | 类型 | 主键 | 可空 | 默认 |
|---|---|---|---|---|
| `id` | INTEGER | ✔ | 否 |  |
| `post_id` | INTEGER |  | 否 |  |
| `platform` | VARCHAR(20) |  | 否 |  |
| `text` | TEXT |  | 否 |  |
| `likes` | INTEGER |  | 否 | 0 |
| `user_nick` | VARCHAR(100) |  | 否 |  |
| `created_at` | DATETIME |  | 否 | 当前时间（北京） |

**索引**：`ix_platform_post_comments_post_id`（post_id）

**外键**：`post_id` → `platform_posts.id`

---

## `platform_post_stats`

平台作品互动指标按天快照：播放/点赞/收藏/评论/转发 + extra 平台特有字段。(post_id, stat_date) 唯一。

| 字段 | 类型 | 主键 | 可空 | 默认 |
|---|---|---|---|---|
| `id` | INTEGER | ✔ | 否 |  |
| `post_id` | INTEGER |  | 否 |  |
| `stat_date` | VARCHAR(10) |  | 否 |  |
| `plays` | INTEGER |  | 否 | 0 |
| `likes` | INTEGER |  | 否 | 0 |
| `favorites` | INTEGER |  | 否 | 0 |
| `shares` | INTEGER |  | 否 | 0 |
| `comments` | INTEGER |  | 否 | 0 |
| `extra` | TEXT |  | 否 | {} |
| `source` | VARCHAR(20) |  | 否 | tikhub |
| `created_at` | DATETIME |  | 否 | 当前时间（北京） |

**索引**：`ix_platform_post_stats_stat_date`（stat_date）；`ix_platform_post_stats_post_id`（post_id）

**唯一约束**：`uq_post_stat`（post_id, stat_date）

**外键**：`post_id` → `platform_posts.id`

---

## `platform_posts`

云端作品（平台原样数据，默认无本地视频）：platform+platform_post_id 唯一；local_video_id 绑定本地素材、work_id 跨平台同作品合并。

| 字段 | 类型 | 主键 | 可空 | 默认 |
|---|---|---|---|---|
| `id` | INTEGER | ✔ | 否 |  |
| `account_id` | INTEGER |  | 否 |  |
| `platform` | VARCHAR(20) |  | 否 |  |
| `platform_post_id` | VARCHAR(200) |  | 否 |  |
| `title` | VARCHAR(500) |  | 否 |  |
| `desc` | TEXT |  | 否 |  |
| `tags` | TEXT |  | 否 | [] |
| `is_ad` | BOOLEAN |  | 否 | false |
| `ad_price` | INTEGER |  | 是 |  |
| `cover_url` | VARCHAR(1000) |  | 否 |  |
| `cover_path` | VARCHAR(255) |  | 否 |  |
| `video_url` | VARCHAR(1000) |  | 否 |  |
| `publish_time` | DATETIME |  | 是 |  |
| `raw` | TEXT |  | 否 | {} |
| `local_video_id` | INTEGER |  | 是 |  |
| `work_id` | INTEGER |  | 是 |  |
| `created_at` | DATETIME |  | 否 | 当前时间（北京） |
| `updated_at` | DATETIME |  | 否 | 当前时间（北京） |

**索引**：`ix_platform_posts_work_id`（work_id）；`ix_platform_posts_platform`（platform）；`ix_platform_posts_platform_post_id`（platform_post_id）；`ix_platform_posts_account_id`（account_id）

**唯一约束**：`uq_platform_post`（platform, platform_post_id）

**外键**：`account_id` → `creator_accounts.id`；`local_video_id` → `videos.id`；`work_id` → `works.id`

**关系**：
- creator_accounts 1—N platform_posts（账号下的作品）
- platform_posts N—1 works（work_id 合并）
- platform_posts 1—1 videos（local_video_id 转本地素材后）
- platform_posts 1—N platform_post_stats / platform_post_comments

---

## `review_reports`

复盘报告：A 报表/B 归因/C 建议/D 赛道方向的产出记录与原文。

| 字段 | 类型 | 主键 | 可空 | 默认 |
|---|---|---|---|---|
| `id` | INTEGER | ✔ | 否 |  |
| `run_date` | VARCHAR(10) |  | 否 |  |
| `report_type` | VARCHAR(20) |  | 否 | full |
| `content` | TEXT |  | 否 | {} |
| `created_at` | DATETIME |  | 否 | 当前时间（北京） |

**索引**：`ix_review_reports_run_date`（run_date）

---

## `sync_jobs`

平台同步任务留痕：类型(initial/daily/weekly/single/manual)/账号/状态/统计 + R-070 实时进度(progress_done/total/note)。

| 字段 | 类型 | 主键 | 可空 | 默认 |
|---|---|---|---|---|
| `id` | INTEGER | ✔ | 否 |  |
| `job_type` | VARCHAR(20) |  | 否 |  |
| `scope` | VARCHAR(20) |  | 否 |  |
| `creator_id` | INTEGER |  | 是 |  |
| `account_id` | INTEGER |  | 是 |  |
| `post_id` | INTEGER |  | 是 |  |
| `status` | VARCHAR(20) |  | 否 | running |
| `message` | TEXT |  | 否 |  |
| `stats` | TEXT |  | 否 | {} |
| `progress_total` | INTEGER |  | 否 | 0 |
| `progress_done` | INTEGER |  | 否 | 0 |
| `progress_note` | VARCHAR(255) |  | 否 |  |
| `started_at` | DATETIME |  | 否 | 当前时间（北京） |
| `finished_at` | DATETIME |  | 是 |  |
| `created_at` | DATETIME |  | 否 | 当前时间（北京） |

**索引**：`ix_sync_jobs_job_type`（job_type）

**外键**：`creator_id` → `creators.id`；`account_id` → `creator_accounts.id`；`post_id` → `platform_posts.id`

---

## `topic_candidates`

选题候选：热点匹配/生成的候选稿，供每日选题流水线产出。

| 字段 | 类型 | 主键 | 可空 | 默认 |
|---|---|---|---|---|
| `id` | INTEGER | ✔ | 否 |  |
| `run_date` | VARCHAR(10) |  | 否 |  |
| `hot_topic_id` | INTEGER |  | 是 |  |
| `title` | VARCHAR(255) |  | 否 |  |
| `platform` | VARCHAR(20) |  | 否 |  |
| `score` | INTEGER |  | 否 | 0 |
| `slot` | VARCHAR(10) |  | 否 |  |
| `reason` | TEXT |  | 否 |  |
| `draft_id` | INTEGER |  | 是 |  |
| `created_at` | DATETIME |  | 否 | 当前时间（北京） |

**索引**：`ix_topic_candidates_run_date`（run_date）

**外键**：`hot_topic_id` → `hot_topics.id`；`draft_id` → `drafts.id`

---

## `topic_ideas`

选题池灵感（R-028）：来源=各平台热点或作品评论区（source=hot/comment），人工挑选，不自动推送。

| 字段 | 类型 | 主键 | 可空 | 默认 |
|---|---|---|---|---|
| `id` | INTEGER | ✔ | 否 |  |
| `source` | VARCHAR(20) |  | 否 | hot |
| `platform` | VARCHAR(20) |  | 否 |  |
| `title` | VARCHAR(255) |  | 否 |  |
| `detail` | TEXT |  | 否 |  |
| `post_id` | INTEGER |  | 是 |  |
| `post_title` | VARCHAR(500) |  | 否 |  |
| `creator_id` | INTEGER |  | 是 |  |
| `snapshot_date` | VARCHAR(10) |  | 否 |  |
| `likes` | INTEGER |  | 否 | 0 |
| `used` | BOOLEAN |  | 否 | false |
| `created_at` | DATETIME |  | 否 | 当前时间（北京） |

**索引**：`ix_topic_ideas_used`（used）；`ix_topic_ideas_platform`（platform）；`ix_topic_ideas_snapshot_date`（snapshot_date）；`ix_topic_ideas_creator_id`（creator_id）

**外键**：`post_id` → `platform_posts.id`；`creator_id` → `creators.id`

---

## `transcripts`

转写稿：ASR 原文(transcript_text)、AI 校对稿(source_text)与状态；video_id 唯一。

| 字段 | 类型 | 主键 | 可空 | 默认 |
|---|---|---|---|---|
| `id` | INTEGER | ✔ | 否 |  |
| `video_id` | INTEGER |  | 否 |  |
| `source_text` | TEXT |  | 否 |  |
| `transcript_text` | TEXT |  | 否 |  |
| `corrected_text` | TEXT |  | 否 |  |
| `asr_status` | VARCHAR(20) |  | 否 | pending |
| `created_at` | DATETIME |  | 否 | 当前时间（北京） |

**索引**：`ix_transcripts_video_id`（video_id）

**外键**：`video_id` → `videos.id`

---

## `videos`

本地素材：上传/导入视频元数据 + 封面 + 平台/赛道多选(JSON) + 发布状态/时间 + 绑定平台作品/合并作品。

| 字段 | 类型 | 主键 | 可空 | 默认 |
|---|---|---|---|---|
| `id` | INTEGER | ✔ | 否 |  |
| `filename` | VARCHAR(255) |  | 否 |  |
| `title` | VARCHAR(255) |  | 否 |  |
| `cover_path` | VARCHAR(255) |  | 否 |  |
| `platforms` | TEXT |  | 否 | [] |
| `creator_id` | INTEGER |  | 是 |  |
| `platform_post_id` | VARCHAR(200) |  | 否 |  |
| `work_id` | INTEGER |  | 是 |  |
| `status` | VARCHAR(20) |  | 否 | planned |
| `planned_publish_at` | DATETIME |  | 是 |  |
| `published_at` | DATETIME |  | 是 |  |
| `is_ad` | BOOLEAN |  | 否 | false |
| `ad_price` | INTEGER |  | 是 |  |
| `main_topics` | TEXT |  | 否 | [] |
| `tags` | TEXT |  | 否 | [] |
| `tags_confirmed` | BOOLEAN |  | 否 | false |
| `created_at` | DATETIME |  | 否 | 当前时间（北京） |

**索引**：`ix_videos_work_id`（work_id）；`ix_videos_creator_id`（creator_id）；`ix_videos_filename`（filename）

**外键**：`creator_id` → `creators.id`；`work_id` → `works.id`

**关系**：
- videos 1—1 transcripts
- videos 1—N metrics_snapshots
- videos 1—N drafts（关联脚本）
- videos.platform_post_id 绑定首平台作品、work_id 绑定合并作品

---

## `works`

跨平台同作品：同一内容三平台自动/手动合并，title 规范化去重，承载素材库云端合并卡。

| 字段 | 类型 | 主键 | 可空 | 默认 |
|---|---|---|---|---|
| `id` | INTEGER | ✔ | 否 |  |
| `creator_id` | INTEGER |  | 是 |  |
| `title` | VARCHAR(500) |  | 否 |  |
| `cover_path` | VARCHAR(255) |  | 否 |  |
| `created_at` | DATETIME |  | 否 | 当前时间（北京） |
| `updated_at` | DATETIME |  | 否 | 当前时间（北京） |

**索引**：`ix_works_creator_id`（creator_id）

**外键**：`creator_id` → `creators.id`

---
