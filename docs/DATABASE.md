# 数据库表结构（人工维护 + 注释）

> 表结构来源：`backend/app/models/*.py`（SQLAlchemy 2.x 声明式），**人工维护**；`scripts/check_doc_consistency.py` 会在 `scripts/verify.sh` 中校验表数量与表名和代码一致。
> 数据库：PostgreSQL（R-235 起，SQLAlchemy 2.x + psycopg v3）。连接串由 `.env` 的 `ECHO_DATABASE_URL` 决定（无默认、缺失启动报错；驱动写法 `postgresql+psycopg://…`），运行时数据目录见 QUICKSTART。
> 结构演进：R-236 起由 `backend/alembic/versions/` 管理；启动执行 `upgrade head`，现有完整旧库首次自动 baseline。新增表、字段、索引、视图或结构相关数据变更必须新增 revision，并同步本文。
> 时间列统一存北京时间（core/timeutil.now，R-066）。JSON 类文本列默认 `[]` / `{}`。

## 表总览（38 张）

| 表 | 说明 |
|---|---|
| `ai_prompts` | AI 提示词版本库（R-021）：key 标识用途，version 递增，status=enabled 为当前生效版；R-129 起候选正文=可优化段+程序固定的输出契约段，支持候选拒绝(rejected)与历史回滚。 |
| `agent_actions` | AI 对话的写操作提案与审计（R-147 P2）：模型只**提议**（`status=pending`，含 `preview` 影响范围说明），作者在对话里点「确认执行」后才真正落库（`confirmed→done`），取消则 `cancelled`。`task_id` 记录入队的后台任务。 |
| `app_kv` | 轻量键值表：预算计数(tikhub_budget_used:日期)、R-022 优化节流计数等。 |
| `background_tasks` | 后台任务表：start_task 创建的异步任务（素材转写/每日流水线/平台同步/AI 生成等），记录 kind/payload/status/progress/note（阶段说明：下载中/转写中等，R-081）/error，结束自动写通知。 |
| `chat_conversations` | AI 对话会话（R-017）：标题 + 创建/更新时间，单用户多会话。 |
| `chat_messages` | AI 对话消息：角色（user/assistant/system）、内容、会话归属 conversation_id、是否流式完成等。 |
| `creator_account_snapshots` | 博主×平台账号主页指标按天快照：粉丝/获赞/作品数/关注数 + raw 原文，支撑涨粉曲线。(account_id, snapshot_date) 唯一。 |
| `creator_accounts` | 博主在某平台的账号配置：主页链接、解析出的平台 ID、增强配置(extra_config JSON)、同步开关/频率/最后同步时间/头像。 |
| `creators` | 博主：kind=owner 主博主 / benchmark 对标（parent_id 挂主博主）；is_current 标记当前主博主，切换时素材/人设/复盘整套随动。 |
| `draft_discussions` | 双模型讨论留痕（R-023）：围绕草稿的每轮讨论消息（模型/轮次/内容）。 |
| `draft_versions` | 草稿版本留痕（R-156）：每次定稿保存一条当前稿快照（正文/标题/封面字/标签），source=manual 手动定稿 / ai_discuss 讨论后自动定稿；版本链供改稿差异分析与生成 few-shot。 |
| `drafts` | 脚本草稿：每日选题/手动生成的 AI 稿 + 作者改写稿；prompt_version 记录生成时启用的提示词版本（R-129 M116），用于按版本聚合反馈。 |
| `feedback` | 作者反馈：R-211 起活信号=评价文本 comment + LLM 复盘心得 insight（完成/不采用触发分析）；rating/liked/四维分仅历史数据。 |
| `hot_topics` | 热点记录：平台+标题+日期去重；供选题匹配（R-025 扩充来源，R-065 后走 TikHub 热搜）。 |
| `inspiration_notes` | 灵感随手记（R-186）：一句观察/截图/经历存原料库（text/image_url/source），可一键提炼成选题并生成草稿（status=new/used，draft_id）。 |
| `metrics_snapshots` | 本地素材(videos)每日指标快照：手动录入/批量导入/抓取/平台同步聚合，驱动看板增长曲线与复盘。 |
| `notifications` | 右上角通知（R-019）：异步任务完成/失败，含目标页 target 与已读。 |
| `persona_checks` | 人设「增量 vs 全量」对齐校验记录（R-128）：覆盖率、AI 语义复核分、是否达标/是否回退全量、差异明细 JSON，供人设页展示 5% 对齐结果。 |
| `persona_tags` | 人设档案版本：标签 + 描述 + AI 自定维度(dimension) + 四层分层(layer: core_dna/stance/mode/forbidden，R-182) + 证据/频次 + 状态(suggested/confirmed/rejected)；版本化，AI 建议需作者确认。 |
| `pipeline_runs` | 每日流水线运行记录：当日幂等（同 run_date 不重跑）、成功/失败状态与摘要。 |
| `platform_post_comments` | 平台作品评论（入库本地查询，R-067 后带点赞数 likes，按点赞 Top50 入库展示）：post_id+text 去重。 |
| `platform_post_stats` | 平台作品互动指标按天快照：播放/点赞/收藏/评论/转发 + extra 平台特有字段。(post_id, stat_date) 唯一。 |
| `platform_posts` | 云端作品（平台原样数据，默认无本地视频）：platform+platform_post_id 唯一；local_video_id 绑定本地素材、work_id 跨平台同作品合并。 |
| `prompt_evals` | 提示词候选的金样本回放评分（R-129 M115）：候选版 vs 当前启用版在同一批金样本上的格式合法率/红线命中率/像作者率与综合分；supported=False 表示该功能暂不支持回放评分。 |
| `sync_jobs` | 平台同步任务留痕：类型(initial/daily/weekly/single/manual)/账号/状态/统计 + R-070 实时进度(progress_done/total/note)。 |
| `topic_candidates` | 选题候选：热点匹配/生成的候选稿，供每日选题流水线产出。 |
| `topic_ideas` | 选题池灵感（R-028）：来源=各平台热点或作品评论区（source=hot/comment），人工挑选，不自动推送。 |
| `transcripts` | 转写稿：ASR 原文(transcript_text)、AI 校对稿(source_text)与状态；video_id 唯一。 |
| `videos` | 本地素材：上传/导入视频元数据 + 封面 + 平台/赛道多选(JSON) + 发布状态/时间 + 绑定平台作品/合并作品。 |
| `works` | 跨平台同作品：同一内容三平台自动/手动合并，title 规范化去重，承载素材库云端合并卡。 |
| `douyin_creator_credentials` | 抖音创作者 Cookie 密文、可用状态、最近验证/成功同步时间与脱敏错误；密钥只在 `.env`。 |
| `douyin_post_metrics` | 自己抖音作品创作者指标按天快照：跳出/完播/平均播放/封面点击/主页访问/单条涨粉/趋势/raw。 |
| `douyin_reference_videos` | 抖音低粉榜和公开搜索参考：作者/公开互动/官方标签/类别关键词/分析/raw。 |
| `video_reviews` | 每次视频复盘主记录：输入指纹、比较对象、指标快照、总结、主页分析、新话题、模型与警告。 |
| `video_review_findings` | 复盘原因明细：规则、事实/推测、指标与内容证据、比较视频、修改建议。 |
| `video_topic_recommendations` | 首选/备选/后续主题：理由、适合依据、证据、内容顺序、来源、评分明细与采用时间。 |
| `video_improvement_plans` | 作者确认的修改计划：保留项、1～2 项修改、观察指标、关联新视频与检查结果。 |

## 核心数据流关系速览

- 博主体系：`creators`（owner/benchmark）→ `creator_accounts`（每平台账号）→ `creator_account_snapshots`（主页按天）
- 云端作品：`creator_accounts` → `platform_posts` → `platform_post_stats`（按天指标）/ `platform_post_comments`（评论 Top50）；`platform_posts.work_id` → `works`（跨平台同作品合并）；`local_video_id` → `videos`（转本地素材）
- 本地素材：`videos` → `transcripts`（转写稿）/ `metrics_snapshots`（按天聚合指标）；`videos.work_id` 与 `platform_post_id` 关联云端
- 内容生产：`hot_topics` → `topic_candidates` → `drafts` → `feedback` / `draft_discussions`
- 任务/通知：`background_tasks` + `sync_jobs` 记录后台工作，结束写 `notifications`；`app_kv` 存预算等标记

---

## `ai_prompts`

AI 提示词版本库（R-021）：key 标识用途，version 递增，status=enabled 为当前生效版，content 为提示词正文（R-129 起候选正文 = 可优化段 + 程序固定的输出契约段）；支持历史回滚、自动优化候选与候选拒绝（rejected）。

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

轻量键值表：预算计数(tikhub_budget_used:日期)、R-022 优化节流计数等。

| 字段 | 类型 | 主键 | 可空 | 默认 |
|---|---|---|---|---|
| `key` | VARCHAR(120) | ✔ | 否 |  |
| `value` | TEXT |  | 否 |  |

---

## `background_tasks`

后台任务表：start_task 创建的异步任务（素材转写/每日流水线/平台同步/AI 生成等），记录 kind/payload/status/progress/note（阶段说明：下载中/转写中等，R-081）/error，结束自动写通知。

| 字段 | 类型 | 主键 | 可空 | 默认 |
|---|---|---|---|---|
| `id` | INTEGER | ✔ | 否 |  |
| `kind` | VARCHAR(50) |  | 否 |  |
| `status` | VARCHAR(20) |  | 否 | pending |
| `progress` | INTEGER |  | 否 | 0 |
| `note` | VARCHAR(255) |  | 否 |  |
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
- creators 1—N persona_checks
- creators 1—N creators（benchmark.parent_id）

---

## `draft_discussions`

双模型讨论留痕（R-023）：围绕草稿的每轮讨论消息（模型/轮次/内容）。
R-178 起每条**实际出结果**的模型也落库（`used_slot/vendor/model_id`，降级/兜底后以事实为准），
`kind='run'` 的行是**一次讨论的运行头**（`content` 为 JSON：当时配置的生成方/评审方 + 轮次 + 是否降级）。

| 字段 | 类型 | 主键 | 可空 | 默认 |
|---|---|---|---|---|
| `id` | INTEGER | ✔ | 否 |  |
| `draft_id` | INTEGER |  | 否 |  |
| `round` | INTEGER |  | 否 | 0 |
| `actor` | VARCHAR(20) |  | 否 |  |
| `kind` | VARCHAR(20) |  | 否 |  |
| `content` | TEXT |  | 否 |  |
| `used_slot` | VARCHAR(20) |  | 否 | '' |
| `vendor` | VARCHAR(40) |  | 否 | '' |
| `model_id` | VARCHAR(80) |  | 否 | '' |
| `created_at` | DATETIME |  | 否 | 当前时间（北京） |

**索引**：`ix_draft_discussions_draft_id`（draft_id）

**外键**：`draft_id` → `drafts.id`

---

## `draft_versions`

草稿版本留痕（R-156）：每次定稿保存一条当前稿快照（正文/标题/封面字/标签），`source` 区分手动定稿与 AI 讨论后自动定稿；版本链喂给改稿差异分析与生成 few-shot。

| 字段 | 类型 | 主键 | 可空 | 默认 |
|---|---|---|---|---|
| `id` | INTEGER | ✔ | 否 |  |
| `draft_id` | INTEGER |  | 否 |  |
| `title` | VARCHAR(255) |  | 否 |  |
| `cover_text` | VARCHAR(100) |  | 否 |  |
| `script` | TEXT |  | 否 |  |
| `tags` | TEXT |  | 否 | `[]` |
| `source` | VARCHAR(20) |  | 否 | manual |
| `note` | VARCHAR(200) |  | 否 |  |
| `created_at` | DATETIME |  | 否 | 当前时间（北京） |

**索引**：`ix_draft_versions_draft_id`（draft_id）

**外键**：`draft_id` → `drafts.id`

---

## `drafts`

脚本草稿：每日选题/手动生成的 AI 稿 + 作者改写稿（source 留底供改稿差异分析）；状态 `draft`=草稿 / `used`=待制作 / `done`=完成 / `archived`=不采用(废稿) / `deleted`=逻辑删除（R-159）；素材双向关联 video_id；prompt_version / persona_version 记录生成时启用的提示词版本与人设档案版本（R-129/R-130，0=历史/未知）；quality 存生成后自检结果 JSON（attempts/issues/passed/style_coverage，R-131）；publish_url/publish_platform/published_at 记录发布回填（R-184）；performance 存发布表现回填 JSON（R-189）；work_id 关联作品（历史发布回填，R-197）。

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
| `prompt_version` | INTEGER |  | 否 | 0 |
| `persona_version` | INTEGER |  | 否 | 0 |
| `quality` | TEXT |  | 否 | {} |
| `publish_url` | VARCHAR(500) |  | 否 |  |
| `publish_platform` | VARCHAR(20) |  | 否 |  |
| `published_at` | DATETIME |  | 是 |  |
| `performance` | TEXT |  | 否 | {} |
| `work_id` | INTEGER |  | 是 |  |
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

作者反馈。R-211 起：**评价文本（comment）+ LLM 复盘心得（insight）**是唯一活信号；学习触发改状态流转（完成=好/不采用=差），rating/liked/四维分仅留历史数据、不再参与学习。

| 字段 | 类型 | 主键 | 可空 | 默认 |
|---|---|---|---|---|
| `id` | INTEGER | ✔ | 否 |  |
| `draft_id` | INTEGER |  | 否 |  |
| `liked` | BOOLEAN |  | 是 | R-211 起仅存结论快照（不参与学习查询） |
| `rating` | INTEGER |  | 是 | R-211 起弃用（历史数据） |
| `comment` | TEXT |  | 否 | 「记反馈」评价文本 |
| `hook_score` | INTEGER |  | 是 | R-211 起弃用（历史数据） |
| `pace_score` | INTEGER |  | 是 | R-211 起弃用（历史数据） |
| `ending_score` | INTEGER |  | 是 | R-211 起弃用（历史数据） |
| `style_score` | INTEGER |  | 是 | R-211 起弃用（历史数据） |
| `insight` | TEXT |  | 否 | R-211：完成/不采用触发的 LLM 复盘心得 |
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
| `title` | VARCHAR(1000) |  | 否 |  |
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

## `inspiration_notes`

灵感随手记（R-186）：一句观察/截图/经历存原料库，可一键提炼成选题并生成草稿。

| 字段 | 类型 | 主键 | 可空 | 默认 |
|---|---|---|---|---|
| `id` | INTEGER | ✔ | 否 |  |
| `creator_id` | INTEGER |  | 是 |  |
| `text` | TEXT |  | 否 |  |
| `image_url` | VARCHAR(500) |  | 否 |  |
| `source` | VARCHAR(20) |  | 否 | text |
| `status` | VARCHAR(20) |  | 否 | new |
| `draft_id` | INTEGER |  | 是 |  |
| `created_at` | DATETIME |  | 否 | 当前时间（北京） |

**索引**：`ix_inspiration_notes_creator_id`（creator_id）；`ix_inspiration_notes_status`（status）

**外键**：`creator_id` → `creators.id`；`draft_id` → `drafts.id`

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

## `persona_checks`

人设「增量 vs 全量」对齐校验记录（R-128）：每次新增已发布素材或手动重跑时写入，
记录集合覆盖率、AI 语义复核分、是否达标、是否已自动回退为全量结果，以及未覆盖条目明细。

| 字段 | 类型 | 主键 | 可空 | 默认 |
|---|---|---|---|---|
| `id` | INTEGER | ✔ | 否 |  |
| `creator_id` | INTEGER |  | 是 |  |
| `mode` | VARCHAR(20) |  | 否 | increment |
| `source_count` | INTEGER |  | 否 | 0 |
| `coverage` | FLOAT |  | 否 | 0.0 |
| `semantic` | FLOAT |  | 是 |  |
| `passed` | BOOLEAN |  | 否 | true |
| `fallback` | BOOLEAN |  | 否 | false |
| `detail` | TEXT |  | 否 | {} |
| `created_at` | DATETIME |  | 否 | 当前时间（北京） |

**索引**：`ix_persona_checks_creator_id`（creator_id）

**外键**：`creator_id` → `creators.id`

---

## `persona_tags`

人设档案版本：标签 + 描述 + AI 自定维度 + **四层分层(R-182: core_dna/stance/mode/forbidden)** + 证据/频次/最近出现/确认强度 + 红线/边界 + 状态(suggested/confirmed/rejected)；版本化，AI 建议需作者确认。

| 字段 | 类型 | 主键 | 可空 | 默认 |
|---|---|---|---|---|
| `id` | INTEGER | ✔ | 否 |  |
| `creator_id` | INTEGER |  | 是 |  |
| `label` | VARCHAR(100) |  | 否 |  |
| `description` | TEXT |  | 否 |  |
| `dimension` | VARCHAR(30) |  | 否 |  |
| `category` | VARCHAR(20) |  | 否 | style |
| `layer` | VARCHAR(20) |  | 否 | stance |
| `evidence` | TEXT |  | 否 |  |
| `frequency` | INTEGER |  | 否 | 0 |
| `last_seen_at` | DATETIME |  | 是 |  |
| `confirm_strength` | INTEGER |  | 否 | 1 |
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

## `prompt_evals`

提示词候选的金样本回放评分（R-129 M115）：每次产出候选自动跑一次，候选版与当前版在同一批金样本上对比。

| 字段 | 类型 | 主键 | 可空 | 默认 |
|---|---|---|---|---|
| `id` | INTEGER | ✔ | 否 |  |
| `key` | VARCHAR(40) |  | 否 |  |
| `candidate_version` | INTEGER |  | 否 | 0 |
| `base_version` | INTEGER |  | 否 | 0 |
| `candidate_score` | FLOAT |  | 否 | 0.0 |
| `base_score` | FLOAT |  | 否 | 0.0 |
| `supported` | BOOLEAN |  | 否 | true |
| `reason` | TEXT |  | 否 |  |
| `detail` | TEXT |  | 否 | {} |
| `created_at` | DATETIME |  | 否 | 当前时间（北京） |

**索引**：`ix_prompt_evals_key`（key）

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
| `title` | VARCHAR(1000) |  | 否 |  |
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

## `agent_actions`

AI 对话写操作的提案与审计（R-147 P2）。

| 列 | 类型 | 说明 |
|---|---|---|
| `id` | INTEGER | 主键 |
| `conversation_id` | INTEGER | 来源会话（可空=遗留单线程） |
| `message_id` | INTEGER | 预留：关联的助手消息 |
| `action` | VARCHAR(50) | `generate_draft` / `rework_draft` / `set_draft_status` |
| `payload` | TEXT | 动作参数（JSON） |
| `preview` | VARCHAR(500) | 给作者看的「这一步会做什么」 |
| `status` | VARCHAR(20) | `pending` / `confirmed` / `cancelled` / `done` / `failed` |
| `result` | TEXT | 执行结果说明 |
| `error` | TEXT | 失败原因 |
| `task_id` | INTEGER | 若入队了后台任务，记录任务 id |
| `created_at` / `decided_at` | DATETIME | 登记时间 / 作者决定时间 |

## `web_search_logs`

联网搜索留痕（R-227 / R-233）：每次生成/洗稿调用联网搜索时**每个来源各落一行**（豆包、DeepSeek），保留 query 与该路候选（含正文与过滤原因），便于核对与额度对账。

| 列 | 类型 | 说明 |
|---|---|---|
| `id` | INTEGER | 主键 |
| `draft_id` | INTEGER | 关联草稿（可空） |
| `creator_id` | INTEGER | 归属主博主（可空） |
| `query` | VARCHAR(500) | 实际搜索词（双源共用） |
| `source` | VARCHAR(20) | 来源：`doubao`（豆包）/ `deepseek`（R-233） |
| `time_range` | VARCHAR(40) | 时间范围过滤（空=不限） |
| `results` | TEXT | 该路候选中 JSON：`{"kept":[...],"rejected":[{"title","url","reason"}]}`（含正文/摘要/站点，原样留痕） |
| `used` | TEXT | 生成方选文后，正文实际引用到的来源 JSON（双行写同一份） |
| `created_at` | DATETIME | 创建时间（北京时间） |

## `douyin_creator_credentials`

R-237：本人或已授权抖音账号的创作者 Cookie。数据库只存 Fernet 密文，解密密钥只放 `.env` 的 `ECHO_DOUYIN_COOKIE_KEY`。

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | INTEGER | 主键 |
| `account_id` | INTEGER | 对应 `creator_accounts.id`，唯一 |
| `cookie_value` | TEXT | Cookie 密文，接口永不回显 |
| `status` | VARCHAR(20) | `missing/valid/expired/invalid` |
| `last_validated_at` | DATETIME | 最近验证时间（可空） |
| `last_success_at` | DATETIME | 最近成功获取数据时间（可空） |
| `last_error` | TEXT | 脱敏失败原因 |
| `created_at` / `updated_at` | DATETIME | 创建/修改时间 |

## `douyin_post_metrics`

自己抖音作品的创作者指标按天快照；`(post_id, snapshot_date)` 唯一。NULL 表示平台未返回，不等于 0。

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | INTEGER | 主键 |
| `post_id` | INTEGER | 对应 `platform_posts.id` |
| `snapshot_date` | VARCHAR(10) | 指标日期 |
| `captured_at` | DATETIME | 实际抓取时间 |
| `bounce_2s_rate` | FLOAT | 2 秒跳出率（0～1，可空） |
| `finish_5s_rate` | FLOAT | 5 秒完播率（0～1，可空） |
| `finish_rate` | FLOAT | 完整完播率（0～1，可空） |
| `avg_play_seconds` | FLOAT | 平均播放时长（秒，可空） |
| `cover_click_rate` | FLOAT | 封面点击率（0～1，可空） |
| `profile_visits` | INTEGER | 观看后主页访问量（可空） |
| `follower_gain` | INTEGER | 单条视频粉丝增量（可空） |
| `traffic_sources` | TEXT | 播放来源 JSON |
| `search_terms` | TEXT | 搜索词 JSON |
| `retention_trend` / `like_trend` / `bounce_trend` | TEXT | 留存/点赞/跳出趋势 JSON |
| `similar_author_trend` | TEXT | 平台同类作者趋势 JSON |
| `trend_reliable` | BOOLEAN | 播放≥200且趋势非空 |
| `raw` | TEXT | 创作者接口原始响应，不含 Cookie |
| `created_at` | DATETIME | 创建时间 |

索引：`ix_douyin_post_metrics_post_date`、`ix_douyin_post_metrics_snapshot_date`。

## `douyin_reference_videos`

低粉榜和公开搜索视频，独立于手动同行关系，不进入作者人设语料。

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | INTEGER | 主键 |
| `external_post_id` | VARCHAR(200) | 抖音作品 ID，唯一 |
| `source` / `source_label` | VARCHAR | 来源与官方标签 |
| `author_id` / `author_nickname` | VARCHAR | 公开作者 ID/昵称 |
| `author_followers` | INTEGER | 公开粉丝数（可空） |
| `title` / `cover_url` / `video_url` | VARCHAR/TEXT | 标题、封面、原视频链接 |
| `publish_time` | DATETIME | 发布时间（可空） |
| `duration_seconds` | INTEGER | 时长（秒，可空） |
| `plays` / `likes` / `comments` / `shares` | INTEGER | 公开互动（可空） |
| `category_id` / `keyword` | VARCHAR | 筛选类别和关键词 |
| `top_comments` | TEXT | 公开评论 JSON |
| `analysis` | TEXT | 公开内容分析 JSON |
| `analyzed_at` | DATETIME | 最近分析时间（可空） |
| `raw` | TEXT | 公开接口原始响应 |
| `first_seen_at` / `last_seen_at` | DATETIME | 首次/最近出现时间 |

## `video_reviews`

每次分析新建记录，不覆盖历史复盘。

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | INTEGER | 主键 |
| `account_id` / `post_id` | INTEGER | 本人抖音账号和作品 |
| `task_id` | INTEGER | 后台任务（可空） |
| `status` | VARCHAR(20) | `running/done/partial/failed` |
| `input_fingerprint` | VARCHAR(64) | 输入与规则版本指纹 |
| `rule_version` | VARCHAR(20) | 归因规则版本 |
| `comparison_count` | INTEGER | 实际比较视频数 |
| `comparison_post_ids` | TEXT | 比较作品 ID JSON |
| `summary` | TEXT | 一句话结论 |
| `overall_result` | VARCHAR(30) | `good/mixed/needs_improvement/unknown` |
| `metrics_snapshot` | TEXT | 分析当时的指标、事实和图表快照 |
| `homepage_analysis` | TEXT | 主页检查与作者补充信息 |
| `new_topics` | TEXT | 账号新话题 JSON |
| `warnings` | TEXT | 缺数据和降级说明 |
| `model_name` / `prompt_version` | VARCHAR/INTEGER | 实际模型与提示词版本 |
| `error` | TEXT | 脱敏错误 |
| `created_at` / `completed_at` | DATETIME | 发起/完成时间 |

## `video_review_findings`

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | INTEGER | 主键 |
| `review_id` | INTEGER | 所属复盘 |
| `dimension` | VARCHAR(20) | 播放/互动/完播/涨粉 |
| `rule_key` | VARCHAR(60) | 程序规则标识 |
| `title` | VARCHAR(300) | 小白可读原因 |
| `judgement_type` | VARCHAR(20) | `fact/hypothesis/unknown` |
| `conclusion` | TEXT | 具体结论 |
| `metric_evidence` | TEXT | 指标依据 JSON |
| `content_evidence` | TEXT | 转写/评论/主页依据 JSON |
| `comparison_post_ids` | TEXT | 比较视频 ID JSON |
| `suggestion` | TEXT | 可执行修改建议 |
| `target_metric` | VARCHAR(30) | 主要改善目标 |
| `sort_order` | INTEGER | 展示顺序 |
| `created_at` | DATETIME | 创建时间 |

## `video_topic_recommendations`

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | INTEGER | 主键 |
| `review_id` | INTEGER | 所属复盘 |
| `parent_id` | INTEGER | 后续主题指向首选（可空） |
| `role` | VARCHAR(20) | `primary/backup/follow_up` |
| `rank` | INTEGER | 同角色顺序；与 review_id/role 唯一 |
| `topic` | VARCHAR(500) | 具体主题 |
| `reason` / `fit_reason` | TEXT | 推荐理由与适合作者的原因 |
| `evidence` | TEXT | 真实证据 JSON |
| `outline` | TEXT | 简要内容顺序，不是完整脚本 |
| `opening_line` | TEXT | 开头第一句建议 |
| `target_metric` | VARCHAR(30) | 主要目标 |
| `follow_up_role` | VARCHAR(40) | 后续内容作用 |
| `source_types` | TEXT | 来源类型 JSON |
| `score` | FLOAT | 本次排序分，不是爆款概率 |
| `score_detail` | TEXT | 各维度得分与扣分 JSON |
| `adopted_at` | DATETIME | 作者采用时间（可空） |
| `created_at` | DATETIME | 创建时间 |

## `video_improvement_plans`

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | INTEGER | 主键 |
| `review_id` | INTEGER | 来源复盘 |
| `source_post_id` | INTEGER | 原视频 |
| `recommendation_id` | INTEGER | 采用主题（可空） |
| `kept_text` | TEXT | 本次保留的做法 |
| `changes` | TEXT | 作者确认的 1～2 项修改 JSON |
| `target_metrics` | TEXT | 主要观察指标 JSON |
| `status` | VARCHAR(20) | `recorded/linked/checked` |
| `published_post_id` | INTEGER | 关联的新发布视频（可空） |
| `check_result` | TEXT | 改善/未改善/不确定及依据 |
| `checked_at` | DATETIME | 最近检查时间（可空） |
| `created_at` / `updated_at` | DATETIME | 创建/修改时间 |

## 只读分析视图（不是表，供 AI 对话的 `sql_query` 使用）

R-147 P1：把「可以让 AI 看的数据」做成视图，**原始表不给模型**（`app_kv` 含明文模型 Key、`ai_prompts` 含提示词正文，
都不在视图里）。视图由 `app/core/analytics_views.py` 在启动时幂等重建（`DROP VIEW IF EXISTS` + `CREATE VIEW`），
`sql_query` 只允许查询这些名字。

| 视图 | 内容 |
|---|---|
| `v_videos` | 素材（标题/状态/平台/赛道/是否广告/发布时间） |
| `v_drafts` | 草稿（状态/来源/字数/脚本前 120 字/人设与提示词版本） |
| `v_feedback` | 反馈（总分/四维分/评论） |
| `v_persona_tags` | 人设标签与红线 |
| `v_topics` | 每日选题候选（槽位/分数/理由） |
| `v_ideas` | 灵感池（评论/热榜） |
| `v_metrics` | 指标快照（按天） |
| `v_platform_posts` | 平台云端作品（含博主归属/是否已绑定本地素材） |
