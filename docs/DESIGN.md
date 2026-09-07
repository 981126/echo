# DESIGN — 开发设计细节（代码级）

> 本文与代码一一对应，作为实现/排查时的地图。API 与表结构以 `docs/API.md`、`docs/DATABASE.md`（自动生成）为准。

## 0. 运行入口与配置

### backend/app/main.py
- `lifespan`：`init_db()` → `setup_scheduler()` → `start_inbox_watcher()`。
- 路由均挂 `/api/*` 且默认带 `Depends(require_token)`（`X-Access-Token`）。
- `GET /health` 免令牌；`/covers`、`/uploads` 静态目录挂载；存在 `frontend/dist` 时用 FastAPI 托管前端（hash 路由）。
- CORS 全开（局域网单用户）。

### backend/app/config.py
- pydantic-settings，env 前缀 `ECHO_`，读取根目录 `.env`（`env_file=(".env","../.env")`，从 backend 启动时解析项目根）。
- `normalize_mode(value, allowed, default)`：`TIKHUB_MODE/HOT_SOURCE_MODE/ASR_MODE` 先按 `#` 剥离行尾注释再 trim/lower，非法值**抛错**（R-068）。取值：`tikhub_mode ∈ mock|real`、`hot_source_mode ∈ mock|real`、`asr_mode ∈ mock|aliyun|siliconflow`（R-108）。
- 路径：未显式给 `ECHO_DB_PATH/*_DIR` 时由 `ECHO_DATA_DIR` 派生（db=数据根/echo.db，inbox/videos/covers/uploads 同名子目录）。
- `get_settings()` lru_cache：改 `.env` 需重启进程。

### backend/app/db.py
- `Base.metadata.create_all` → `_ensure_indexes/_ensure_binding_integrity` → 各 `_migrate_*`（幂等补列/迁移）→ `ensure_defaults`（提示词 v1 种子）→ 时区迁移标记。
- 迁移函数：`_migrate_videos`（platforms/main_topics/cover_path/creator_id/platform_post_id/work_id/ad_price 补列与单值转 JSON）、`_migrate_creator_scope`（work_id/tags/is_ad/ad_price/creator_id、本地绑定唯一索引、videos↔posts 反向补绑）、`_migrate_account_avatars`、`_migrate_feedback_dims`、`_migrate_chat`（conversation_id 归属）、`_migrate_comment_likes`（R-067 likes）、`_migrate_sync_progress`（R-070 done/total/note）、`_fix_app_utc_columns`/`_fix_platform_timezone`（历史 +8h 一次性）。

## 1. API 层（backend/app/api/）
| 文件 | 前缀 | 职责 |
|---|---|---|
| videos.py | /api/videos | 上传/列表/详情/更新/确认标签/封面/视频文件/转写触发 |
| works.py | /api/works | 云端作品列表、to-local、meta、merge/split、auto-merge、删除、cleanup-tags |
| platform.py | /api/platform | 云端作品/评论/指标/同步触发与任务/预算/选题池/主页快照；bind-links |
| creators.py | /api/creators | 博主 CRUD/切换/账号 CRUD/头像/链接解析 |
| benchmark.py | /api/benchmark | 博主对标：Top3 展示/转写补齐/AI可讲/洗稿；「重新对标」一键重跑（R-102，后台任务） |
| metrics.py | /api/metrics | 手动录入/批量导入/汇总/单视频序列 |
| review.py | /api/review | 生成报告/最新报告/雷达 |
| persona.py | /api/persona | 档案 CRUD/建议/一键确认/表达风格面板/金句候选 |
| drafts.py | /api/drafts | 草稿 CRUD/生成(同步)/generate-async/打分 |
| chat.py | /api/chat | 会话 CRUD + SSE 流式回复 |
| pipeline.py | /api/pipeline | 每日流水线手动触发/热点刷新/运行记录 |
| topics.py | /api/topics | 热点/话题缺口/匹配选题 |
| prompts.py | /api/prompts | 提示词版本 CRUD/启用/优化候选/历史回滚 |
| requirements.py | /api/requirements | 需求归档读写（文件为事实源） |
| notifications.py | /api/notifications | 通知列表/已读/清空 |
| tasks.py | /api/tasks | 后台任务状态查询 |
| settings.py | /api/settings | 页面可调设置 |
| uploads.py | /api/uploads | 编辑器插图上传 |

### 校验与错误
- 路由薄：参数校验在 Pydantic schema；业务在 services；HTTP 层把 `ValueError` 转 `400`（多数接口已做 try→HTTPException(400, str(exc))）。
- 后台长任务统一 `tasks.start_task(kind, payload, fn)`，完成/失败写 `notifications`（前端铃铛 + toast）。

## 2. 服务层（backend/app/services/）
- `ingest.py`：`import_video_task`（转写+校对+预打标签+人设建议+自动优化提示词触发）、`correct_transcript`、`persona_init_task`（全量初始化）、`suggest_persona_updates`（增量建议，需作者确认）。
- `transcription.py`：`Transcriber.transcribe` 按 `asr_mode` 路由：mock 假转写（离线）/ aliyun（`aliyun_filetrans` 泛化调用提交+轮询）/ siliconflow（`siliconflow_asr` 直传，R-108）。
- `aliyun_filetrans.py / aliyun_oss.py`：FileTrans 4.0（CommonRequest）与 OSS 上传/预签名 URL；上传前由 `media_tools`/`media_naming` 用 ffmpeg 抽 16k 单声道 wav。
- `siliconflow_asr.py`（R-108）：`POST {base}/audio/transcriptions` 直传音频转写（multipart file+model，无需 OSS 中转）；视频先抽音轨、纯音频直传；平台限制单文件 ≤50MB / ≤1 小时（`media_tools.probe_duration_seconds` 探测），超限明确报错走失败通知、**不自动切换其它服务商**。
- `generation.py`：生成草稿（DeepSeek/Kimi/random/alternate）；上下文 = 人设(tags+红线+禁词) + 风格画像 + 检索到的最高分样本（TF-IDF，表现加权+时间衰减）+ 金句/最佳实践 + 对标风格卡。`_all_texts`（全量素材加权语料）供优化与每周重建（R-064）。
- `debate.py`：双模型 5 轮讨论定稿，写入 `draft_discussions`；失败降级单模型。
- `topic_mining.py`：热点源类（mock/公开接口/Bilibili、Douyin、Xiaohongshu/TikHub 热搜实现）；`get_sources` 按 `hot_source_mode` 选择；`fetch_and_store` 入库去重（platform+title+date）。
- `persona.py`：LLM 分析（初版/打标/建议）；`_split_phrases` 与 `suggest_phrase_candidates`（金句候选）。
- `prompt_service.py`：提示词 key→版本管理；`ensure_defaults`、`save_new_version/enable_version/create_candidate`、`feedback_context`、`learning_material`（全量加权前 16 条，R-064）、`optimize/auto_optimize_generation`（每 3 条新素材触发候选，R-022）。
- `style_profile`（core）：口癖/句长/感叹反问占比等画像；R-057 表达风格面板 + 禁词注入。
- `review.py`：ABCD 复盘：A 报表（按视频/赛道/平台）、B 归因（启发式+LLM）、C 建议、D 赛道方向；`_radar` 赛道雷达（按互动率）。
- `metrics.py`：`upsert_snapshot/import_snapshots/fetch_daily/series_for_video/_platform_breakdown/summary`；`apply_retention`（热点 30 天清理）。
- `chat_service.py`：只读工具集 + 流式问答；工具：search_videos/get_video_detail/get_persona/list_requirements/get_metrics_summary/get_today_topics/get_review_report/get_radar/search_drafts/generate_draft（写操作需明确同意）。SSE 由 api/chat 组装。
- `benchmark.py`：对标聚合（最新10条按互动分 Top3；广告/同款漏标过滤；文案只用 ASR 转写稿）+ `ensure_top3_with_text`（缺文案自动下载转写、无文案顺延；有文案后严格 AI 审核软广/商单/引流并落库排除，R-103/R-106）+ `rerun_benchmarks`；/top 有文案优先（空文案被下一条顶上，R-106）（R-102：逐个对标重捞最新10条 → 自动补 Top3 文案，供后台任务回调进度）。
- `platform_sync.py`：见 §4。
- `works_service.py`：标题规范化（去话题/标点/空白/小写）+ 自动合并 + 手动合并/拆分 + `list_works`（合并作品含各平台）+ `post_item`（作品序列化）。
- `creator_service.py`：当前博主/切换/账号元数据/全网粉丝汇总/删除保护。
- `platform_assets.py`：封面/头像下载本地、HEIC 兼容、占位 SVG（mock 无封面时）。
- `notify.py`：QQ SMTP 每日推送 digest/失败告警（HTML）。
- `requirements_service.py`：以 `requirements/` 文件为事实源读写（列表/详情/新建/状态机）。
- `media_naming.py / media_tools.py`：R-058「标题-视频/封面」命名、抽音轨工具。
- `diff_analysis.py / feedback.py`：改稿差异分析、反馈回流。

## 3. 核心算法（backend/app/core/）
- `timeutil.py`：`now()/today()/tz`（默认 Asia/Shanghai，`ECHO_TIMEZONE` 覆盖）——全项目唯一时间来源。
- `retrieval.py`：字符二元组 TF-IDF 检索（中文）。
- `style_profile.py`：风格画像统计。
- `transcript.py`：转写稿切分/处理。
- `matching.py`：热点标题与确认关键词的命中打分。
- `metrics.py`：互动率等规范化。
- `review.py`：复盘启发式。
- `diff.py`：改稿差异（diff 文本）。
- `digest.py`：每日邮件 HTML。
- `draft_check.py`：生成前体检（红线/人设词频/开头钩子/结尾引导，R-030⑦）。
- `pipeline.py`：`today_key()` 等流水线幂等键。
- `requirement_file.py`：R-xxx 文件解析/编号。
- `platform_links.py`：根据 platform_post_id/raw 拼作品页 URL。
- `topics.py`：平台/赛道多选规范化。

## 4. 平台同步（platform_sync.py）——重点
### 数据结构
`DataSource` Protocol（base.py）；`PostData`（platform_post_id/title/cover/stats/raw…）、`ProfileData`、`CommentData(text, likes, user_nick)`。

### 数据源 TikHub（tikhub.py）
- mode=mock：确定性种子假数据（离线验收）；mode=real：真实 REST（douyin app v3 / xhs app v2 / bilibili web）。
- 预算：每次真实/模拟请求后 `_charge(db)` 计数（Kv `tikhub_budget_used:<date>`），超 `tikhub_daily_budget`（默认 2000，可页面调）抛 `BudgetExceeded` → 停止本轮并通知。
- 列表自带 stats 则不额外请求；B站列表无赞藏评 → `_backfill_bili_stats` 每轮最多 150 条单条详情补全。

### 幂等与去重
- 作品：`(platform, platform_post_id)` 唯一约束 + `_ensure_post` 先查后建/更新（含 title/cover/publish_time/raw/tags/cover_path）。
- 指标：`(post_id, stat_date)` 唯一 upsert（当天多次同步覆盖成最新，历史保留）。
- 评论：`_upsert_comments` 按 post_id+text 去重、点赞保留更高值、**按点赞降序取 Top50**（R-067）。
- 进度：`sync_jobs.progress_done/progress_total/progress_note`，`_job_progress` 用 SQL 原子累加（R-070）；`GET /api/platform/jobs` 输出进度供前端轮询。

### 编排（run_sync）
- 入口：手动（博主页 全量/前15条/每周/单账号）、定时（07:30/18:00，daily 带视频下载转写 R-085）、单条（posts/videos/works 同步）。
- `scope=daily`：每平台 top15（R-085/R-086 最终 15）；`weekly`：对标每账号 top3；`initial`：`count<=0 → _real_posts_all` 翻页全量。daily 且 with_media=True 时同步后对前 N 条跑媒体补齐（下载视频+自动转写）。
- 并发：`ThreadPoolExecutor(max_workers=3)` 每账号独立 SQLAlchemy session（account 级隔离，单平台失败不拖垮其它）。
- 结束：`auto_merge_creator` 合并同标题跨平台帖 → `works`；写 SyncJob stats/message + 账号 sync_status；通知中心收到完成。
- 本地素材卡片同步 `sync_local_video_metrics`：遍历 `_bound_platform_posts`（local_video_id + work_id + platform_post_id 三路去重）拉各平台指标 + 评论 Top50，并写 `metrics_snapshots`（当天多平台聚合）；单平台失败不中断，全部失败才报错。
- 云端合并卡同步 `sync_work_posts`（R-067 新增）：遍历 work 下全部平台帖（原只同步 cloudPosts[0]）。

### 卡片同步按钮状态（前端 R-069）
同步中状态按卡片唯一 `key`（`v<id>` 本地 / `w<id>` 合并 / `p<id>` 单条）判断，避免 work_id 与 post id 数字撞车误高亮。

## 5. 定时与后台（scheduler.py / tasks.py）
- 计划见 ARCHITECTURE §4。`_platform_sync_job` 通过 `start_task` 跑 `run_sync(scope=daily)`。
- R-105：`_benchmark_rerun_job` 每天 06:00 自动「重新对标」（每日生成 07:00 前 1 小时）：无主博主/无对标或已有 benchmark_rerun 任务在跑则跳过；否则 start_task 落后台执行（不阻塞调度线程）。
- `tasks.py`：`background_tasks` 表 + daemon 线程；progress 0→10→100；完成写 Notification；`import_video` 完成后若语料已≥阈值（每 3 条新素材）自动产出提示词候选并通知（R-022/R-064）。
- `watcher.py`：10s 轮询 inbox，移入 videos 目录并建 `Video` 行（文件名 uuid 前缀防重），**不自动转写**（R-033，手动按钮触发）。

## 6. 前端结构（frontend/src/）
- `router.js`：/home /videos /drafts /chat /persona /requirements /prompts /dashboard /creators /login（hash）。
- `api.js`：统一 fetch + `X-Access-Token`；401 自动跳登录。
- `views/`：HomeView（时间线+热点灵感）、VideosView（素材库：卡片/编辑弹窗/转本地/评论 tab/合并）、DraftsView（三 tab+打分）、ChatView（SSE 流式）、PersonaView、PromptsView、DashboardView、CreatorsView（博主/账号/作品/同步+进度条）、RequirementsView、LoginView。
- `components/`：MaterialCard/CloudPostTile/PlatformStats/MediaComments/…/SyncProgressBar（R-070，1s 轮询 jobs）。
- `composables/media.js`：fetchVideos/fetchWorks 统一入口。
- `lib/`：format.js（平台名/数字缩写）、options.js（平台/赛道/状态选项）、timeline.js。
- dev：vite 5173 代理后端 8000（`vite.config`）；构建产物 dist 由后端托管。

## 7. 常见改动指南
- 加接口：api/xxx.py + schemas + services；记得跑 verify；涉及注释/文档同步。
- 加表/列：models/*.py + db.py 幂等迁移函数（init_db 注册）；改完生成 DATABASE.md。
- 改平台字段：先看 platform_sync 与 tikhub `_real_*` 解析函数。
- 改生成上下文：generation.py + prompt_service + ai_prompts 页面（版本化，不要写死进系统提示词之外的代码）。
