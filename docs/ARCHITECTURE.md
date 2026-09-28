# ARCHITECTURE — 系统架构总览

> 面向「新开发者 / 新设备部署」的完整架构说明。文档基准 = 当前代码（commit 2026-09-06，R-070 后）。
> 实现细节见 `DESIGN.md`；决策原因见 `DECISIONS.md`。

## 1. 技术栈与形态

| 层 | 选型 | 说明 |
|---|---|---|
| 后端 | Python 3.12+ / FastAPI / Uvicorn | 单进程单体；路由薄、业务厚；同步阻塞业务跑在后台线程 |
| 前端（当前，R-164） | React 19 + TS + Vite + Tailwind v4 + shadcn/ui + Framer Motion + TanStack Query | **默认前端**（R-168）：dev(3000) 代理 8000，build 后由 FastAPI 挂 **/v2**；登录态独立；API 类型由 `/openapi.json` 生成（`npm run gen:api`） |
| ~~老前端（已废弃 R-168）~~ | Vue 3 + Vite + Naive UI | 只读保留，禁止修改；build 产物仍挂根路径兜底，后续下线另立需求 |
| 数据库 | SQLite + SQLAlchemy 2.x（R-163 起 WAL + busy_timeout） | 单用户零运维；engine `check_same_thread=False, timeout=30` 支持多线程；WAL 支持并发读写 |
| schema 演进 | 幂等轻量迁移（`db.py` 内函数） | 每次启动 `init_db()` 检查补列/建索引；**未用 Alembic**（tech-debt） |
| 定时任务 | APScheduler BackgroundScheduler（进程内） | 每日流水线/平台同步两轮/指标留存/备份/清理/每周风格重建 |
| 后台任务 | `background_tasks` 表 + daemon 线程（tasks.py）+ 同步并发消费者池（sync_pool.py，R-163） | 长任务入库、结束自动写通知；同步类任务经队列线程池并行消费；无外部消息队列 |
| 文件监听 | watcher.py 线程轮询 `inbox`（10s） | 拖入视频移入 videos 并建行（**不自动转写**） |
| 外部服务 | 见 §3 | 全部真实接入（LLM/ASR/TikHub/热搜/SMTP） |

## 2. 目录与分层（依赖方向 api → services → models，禁止反向）

```
echo/
├── AGENTS.md / README.md
├── docs/                  # 见 README 导航；API.md、DATABASE.md 人工维护（verify 校验一致性）
├── requirements/          # 需求事实源 R-xxx + README 索引
├── backend/
│   ├── app/
│   │   ├── main.py        # FastAPI 组装：路由注册/令牌/静态托管/健康检查
│   │   ├── config.py      # pydantic-settings（ECHO_ 前缀；模式字段 normalize_mode 校验）
│   │   ├── db.py          # engine/SessionLocal/get_db/init_db + 幂等迁移
│   │   ├── api/           # 薄路由：videos/works/persona/drafts/chat/topics/metrics/review/
│   │   │                  #   pipeline/platform/creators/prompts/requirements/notifications/tasks/settings/uploads
│   │   ├── services/      # 业务层：generation/ingest/persona/persona_profile/prompt_service/prompt_contract/prompt_eval/transcription/topic_mining/
│   │   │                  #   platform_sync/works_service/creator_service/chat_service/prompt_service/…
│   │   │                  #   platform/{base,tikhub,budget,link_utils}.py（数据源适配器）
│   │   │                  #   platform_assets.py（封面/头像下载命名）
│   │   ├── core/          # 纯逻辑算法：retrieval/style_profile/transcript/matching/metrics/review/
│   │   │                  #   pipeline/diff/digest/draft_check/requirement_file/topics/platform_links/timeutil
│   │   ├── models/        # 28 张表（见 docs/DATABASE.md）
│   │   ├── schemas/       # Pydantic 出入参契约
│   │   ├── scheduler.py   # APScheduler 注册
│   │   ├── tasks.py       # start_task/_run_worker/通知/导入后自动优化提示词
│   │   └── watcher.py     # inbox 轮询
│   ├── tests/             # pytest（183 项，离线 mock 可跑）
│   └── .venv/
├── frontend/src/          # views(10 页)/components(23)/composables/api/router/lib
├── frontend_v2/src/       # R-164 全新前端（React 19+TS+Vite，Tailwind v4/shadcn/ui/Framer Motion/TanStack Query；api 由 /openapi.json 生成；生产挂 /v2）
└── scripts/               # verify.sh / backup.sh / update.sh
```

## 3. 外部服务与适配器（全部真实）

| 外部 | 用途 | 代码 | 关键配置（.env，ECHO_ 前缀） |
|---|---|---|---|
| 模型1 / 模型2（可配厂家） | 生成/校对/复盘/对话/双模型讨论 | `services/llm.py`、`llm_router.py`、`model_settings.py`、`debate.py` | 界面「AI 设置 → 模型设置」（app_kv）；`.env` `DEEPSEEK_*`/`KIMI_*` 作 Key 回退 |
| TikHub | 平台数据源（抖音/B站/小红书） | `services/platform/tikhub.py`（实现 `base.DataSource`） | `TIKHUB_API_KEY/BASE_URL/MODE/DAILY_BUDGET` |
| 阿里云 OSS | ASR 文件中转（临时预签名） | `aliyun_oss.py` | `ALIYUN_OSS_BUCKET/REGION` |
| 阿里云 FileTrans | 录音文件识别 4.0 | `aliyun_filetrans.py` | `ALIYUN_ASR_ACCESS_KEY_ID/SECRET/APP_KEY`、`ASR_MODE=aliyun` |
| 硅基流动 | 音频直传转写（Qwen/Qwen3-ASR-1.7B，免费，R-108） | `siliconflow_asr.py` | `SILICONFLOW_API_KEY/BASE_URL/ASR_MODEL`、`ASR_MODE=siliconflow` |
| QQ SMTP | 邮件推送 | `services/notify.py` | `SMTP_HOST/PORT/USER/AUTH_CODE/MAIL_TO` |

**数据源适配器（R-062）**：`services/platform/base.py` 定义 `DataSource` Protocol
（`fetch_profile/fetch_user_posts/fetch_post_stats/fetch_comments/get_balance`），
`make_source(platform)` 支持按单平台或整体注册替换（`register_platform_source`），业务层不感知来源。
`CommentData`（text/likes/user_nick）用于评论按点赞 Top50（R-067）。

**模式护栏（R-068）**：`config.normalize_mode` 对 `TIKHUB_MODE/HOT_SOURCE_MODE/ASR_MODE` 去注释黏连并白名单校验，
非法值启动即抛错——防止「看似 real 实则 mock」用假数据覆盖真实指标（历史事故，勿回退）。

## 4. 运行形态与定时任务（scheduler.py 为准）

- Web：uvicorn :8000；dev 新前端 vite :3000（/api 代理 8000）；老前端 5173 已废弃
- 启动时：`init_db()`（建表+迁移+索引）→ `setup_scheduler()` → `start_inbox_watcher()`（10s 轮询）

| 定时 | 任务 | 行为 |
|---|---|---|
| 每日 `daily_push_time`（默认 07:00） | 每日流水线 | 热点→选题匹配→生成≥3→入库→（可选邮件） |
| 每日 `daily_push_time` +1h（默认 08:00） | 指标与留存 | cookie 通道未启用 → 仅 `apply_retention`（热点 30 天清理） |
| 每日 `platform_sync_times`（默认 06:00 / 17:00） | 平台同步 | 后台任务 `run_daily_sync_all`（R-109；R-163 起主博主+对标**并发**同步）：每账号三平台 top15 + 前15条视频下载/转写（R-085/R-109）+ 评论采集；同步完成后自动触发一次「重新对标」（refetch=False，不重复拉取） |
| 每日 02:30 | 备份 | `scripts/backup.sh`（SQLite 热备 + requirements/docs 快照，留 10 份） |
| 每日 04:00 | 清理 | 通知>90 天、后台任务>30 天、sync_jobs>60 天、platform_post_stats>400 天 |
| 每周日 03:20 | 风格重建 | 基于全量素材画像+加权样本产出生成提示词候选（不启用）+ 通知 |

## 5. 数据存储（.env 决定，当前非仓库 data/）
| 配置 | 当前值示例 | 内容 |
|---|---|---|
| `ECHO_DATA_DIR` | `/Users/yeah/document/echo_resource` | 数据根 |
| `ECHO_DB_PATH` | `…/echo.db` | SQLite 库 |
| videos / covers / uploads / inbox | `…/videos|covers|uploads|inbox` | 视频文件 / 封面（+ `covers/thumbs/` 缩略图缓存，R-179）/ 编辑器插图 / 待入库 |
仓库 `data/` 为空壳，不是运行时目录。

## 6. 数据库（27 表）
见 `docs/DATABASE.md`（人工维护，verify 校验）。关系速览：
```
creators → creator_accounts → platform_posts → platform_post_stats / platform_post_comments
                              └─ work_id → works（跨平台合并）
                              └─ local_video_id → videos → transcripts / metrics_snapshots
videos → drafts → feedback / draft_discussions
hot_topics → topic_candidates → drafts
creators → persona_tags / persona_checks / creator_account_snapshots
background_tasks / sync_jobs / notifications / app_kv
```
要点：
- `platform_posts(platform, platform_post_id)` 唯一；`platform_post_stats(post_id, stat_date)` 唯一；
  `platform_post_comments(post_id,text)` 业务去重（含 likes）
- `sync_jobs` 带 R-070 进度列 progress_done/progress_total/progress_note，供前端进度条轮询
- 时间列统一北京时间（core/timeutil.now，R-066）

## 7. 关键数据流
1. **导入学习**：上传/inbox → videos 行 → 编辑页手动「语音转文字」（抽音轨→按 .env 选 阿里云 FileTrans(OSS 中转) 或 硅基流动直传，R-108→校对稿回填）→ 确认标签 → 进入人设/风格语料
2. **平台同步**：run_sync（daily top15 带视频下载转写 / weekly 3 / initial 全量）→ 账号并发（每平台独立线程/会话）→ 作品 upsert + 指标按天 upsert + 评论 Top50 → auto_merge 合并 work → daily 再对前15条媒体补齐（下载+转写，R-085）；**R-163** 博主级（sync-all / 每日同步）与素材级（逐素材队列）皆经 `sync_pool` 线程池并发消费、TikHub 全局令牌桶控速 → 进度实时写 sync_jobs → 完成通知
3. **选题/生成**：热点/灵感（灵感池入池：daily 逐素材队列与全量/每周同步共用 `pool_ideas_from_comments`，限量 单帖≤8 / 每博主每天≤40，R-140）→ 人设+风格检索加权（TF-IDF/RAG）→ 双模型讨论（生成方 × 评审方）→ 草稿 → 作者改写 → 反馈回流
   - 非脚本生成的 AI 功能（人设/预打标/校对/差异/对话/提示词优化/金样本评测/对标分析）统一走 `llm_router.primary_llm`：**模型1 主用 → 模型2 降级**（报错/超时/空正文/输出不合法），参数按厂家归一化，降级写日志 + 站内通知
4. ~~复盘~~：已下线（R-097/R-136）；赛道雷达保留在 `services/metrics.radar`，可经 AI 对话查询

## 8. 质量与安全
- 门禁 `scripts/verify.sh`：ruff + mypy + pytest（183 项，离线 mock）+ 前端 lint/build + 文档存在性 + 文档一致性
- Web 入口 `X-Access-Token`（ECHO_ACCESS_TOKEN）；静态资源 /health/openapi 免令牌
- 密钥仅 .env（gitignore）；备份每日自动 + 手动脚本
- 预算护栏：TikHub 每日请求预算（默认 2000，Kv 可覆盖），超限停止本轮并通知
- 外部接口韧性（R-151/R-163）：TikHub 客户端走**全局令牌桶**（所有接口合计 ≤ `ECHO_TIKHUB_RATE_LIMIT` 默认 10 req/s，突发 `ECHO_TIKHUB_RATE_BURST`），
  并对瞬时故障（`httpx.TransportError`：SSL EOF/连接重置/超时）与 `429/5xx` 做 4 次尝试、退避 1.5s→4.0s→8.0s 的重试；
  某路由 429 时按路由退避兜底；4xx 永久错误不重试；重试与最终失败都写日志（本机 httpx 会读 macOS 系统代理 `127.0.0.1:7890`，代理抖动是已知故障源）
