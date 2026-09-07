# ARCHITECTURE — 系统架构总览

> 面向「新开发者 / 新设备部署」的完整架构说明。文档基准 = 当前代码（commit 2026-09-06，R-070 后）。
> 实现细节见 `DESIGN.md`；决策原因见 `DECISIONS.md`。

## 1. 技术栈与形态

| 层 | 选型 | 说明 |
|---|---|---|
| 后端 | Python 3.12+ / FastAPI / Uvicorn | 单进程单体；路由薄、业务厚；同步阻塞业务跑在后台线程 |
| 前端 | Vue 3 + Vite + Naive UI | Hash 路由 SPA，桌面/移动响应式；dev(5173) 代理 8000，也可 build 后由 FastAPI 托管 |
| 数据库 | SQLite + SQLAlchemy 2.x | 单用户零运维；engine `check_same_thread=False, timeout=30` 支持多线程 |
| schema 演进 | 幂等轻量迁移（`db.py` 内函数） | 每次启动 `init_db()` 检查补列/建索引；**未用 Alembic**（tech-debt） |
| 定时任务 | APScheduler BackgroundScheduler（进程内） | 每日流水线/平台同步两轮/指标留存/备份/清理/每周风格重建 |
| 后台任务 | `background_tasks` 表 + daemon 线程（tasks.py） | 长任务入库、结束自动写通知；无消息队列 |
| 文件监听 | watcher.py 线程轮询 `inbox`（10s） | 拖入视频移入 videos 并建行（**不自动转写**） |
| 外部服务 | 见 §3 | 全部真实接入（LLM/ASR/TikHub/热搜/SMTP） |

## 2. 目录与分层（依赖方向 api → services → models，禁止反向）

```
echo/
├── AGENTS.md / README.md
├── docs/                  # 见 README 导航；API.md、DATABASE.md 自动生成
├── requirements/          # 需求事实源 R-xxx + README 索引
├── backend/
│   ├── app/
│   │   ├── main.py        # FastAPI 组装：路由注册/令牌/静态托管/健康检查
│   │   ├── config.py      # pydantic-settings（ECHO_ 前缀；模式字段 normalize_mode 校验）
│   │   ├── db.py          # engine/SessionLocal/get_db/init_db + 幂等迁移
│   │   ├── api/           # 薄路由：videos/works/persona/drafts/chat/topics/metrics/review/
│   │   │                  #   pipeline/platform/creators/prompts/requirements/notifications/tasks/settings/uploads
│   │   ├── services/      # 业务层：generation/ingest/persona/transcription/topic_mining/
│   │   │                  #   platform_sync/works_service/creator_service/chat_service/prompt_service/…
│   │   │                  #   platform/{base,tikhub,budget,link_utils}.py（数据源适配器）
│   │   │                  #   platform_assets.py（封面/头像下载命名）
│   │   ├── core/          # 纯逻辑算法：retrieval/style_profile/transcript/matching/metrics/review/
│   │   │                  #   pipeline/diff/digest/draft_check/requirement_file/topics/platform_links/timeutil
│   │   ├── models/        # 26 张表（见 docs/DATABASE.md）
│   │   ├── schemas/       # Pydantic 出入参契约
│   │   ├── scheduler.py   # APScheduler 注册
│   │   ├── tasks.py       # start_task/_run_worker/通知/导入后自动优化提示词
│   │   └── watcher.py     # inbox 轮询
│   ├── tests/             # pytest（53 项，离线 mock 可跑）
│   └── .venv/
├── frontend/src/          # views(11 页)/components(24)/composables/api/router/lib
└── scripts/               # verify.sh / backup.sh / update.sh
```

## 3. 外部服务与适配器（全部真实）

| 外部 | 用途 | 代码 | 关键配置（.env，ECHO_ 前缀） |
|---|---|---|---|
| DeepSeek / Kimi | 生成/校对/复盘/对话/双模型讨论 | `services/llm.py`、`debate.py` | `DEEPSEEK_API_KEY/BASE_URL/MODEL`、`KIMI_*`、`GENERATION_MODEL` |
| TikHub | 平台数据源（抖音/B站/小红书） | `services/platform/tikhub.py`（实现 `base.DataSource`） | `TIKHUB_API_KEY/BASE_URL/MODE/DAILY_BUDGET` |
| 阿里云 OSS | ASR 文件中转（临时预签名） | `aliyun_oss.py` | `ALIYUN_OSS_BUCKET/REGION` |
| 阿里云 FileTrans | 录音文件识别 4.0 | `aliyun_filetrans.py` | `ALIYUN_ASR_ACCESS_KEY_ID/SECRET/APP_KEY`、`ASR_MODE=aliyun` |
| 硅基流动 | 音频直传转写（Qwen/Qwen3-ASR-1.7B，R-108） | `siliconflow_asr.py` | `SILICONFLOW_API_KEY/BASE_URL/ASR_MODEL`、`ASR_MODE=siliconflow` |
| QQ SMTP | 邮件推送 | `services/notify.py` | `SMTP_HOST/PORT/USER/AUTH_CODE/MAIL_TO` |

**数据源适配器（R-062）**：`services/platform/base.py` 定义 `DataSource` Protocol
（`fetch_profile/fetch_user_posts/fetch_post_stats/fetch_comments/get_balance`），
`make_source(platform)` 支持按单平台或整体注册替换（`register_platform_source`），业务层不感知来源。
`CommentData`（text/likes/user_nick）用于评论按点赞 Top50（R-067）。

**模式护栏（R-068）**：`config.normalize_mode` 对 `TIKHUB_MODE/HOT_SOURCE_MODE/ASR_MODE` 去注释黏连并白名单校验，
非法值启动即抛错——防止「看似 real 实则 mock」用假数据覆盖真实指标（历史事故，勿回退）。

## 4. 运行形态与定时任务（scheduler.py 为准）

- Web：uvicorn :8000；dev 前端 vite :5173（/api 代理 8000）
- 启动时：`init_db()`（建表+迁移+索引）→ `setup_scheduler()` → `start_inbox_watcher()`（10s 轮询）

| 定时 | 任务 | 行为 |
|---|---|---|
| 每日 `daily_push_time`（默认 07:00） | 每日流水线 | 热点→选题匹配→生成≥3→入库→（可选邮件） |
| 每日 `daily_push_time` +1h（默认 08:00） | 指标与留存 | cookie 通道未启用 → 仅 `apply_retention`（热点 30 天清理） |
| 每日 `platform_sync_times`（默认 07:30 / 18:00） | 平台同步 | 后台任务 `run_sync(scope=daily, with_media=True)`：当前主博主三平台 top15 + 前15条视频下载/转写（R-085）+ 评论采集 |
| 每日 02:30 | 备份 | `scripts/backup.sh`（SQLite 热备 + requirements/docs 快照，留 10 份） |
| 每日 04:00 | 清理 | 通知>90 天、后台任务>30 天、sync_jobs>60 天、platform_post_stats>400 天 |
| 每周日 03:20 | 风格重建 | 基于全量素材画像+加权样本产出生成提示词候选（不启用）+ 通知 |

## 5. 数据存储（.env 决定，当前非仓库 data/）
| 配置 | 当前值示例 | 内容 |
|---|---|---|
| `ECHO_DATA_DIR` | `/Users/yeah/document/echo_resource` | 数据根 |
| `ECHO_DB_PATH` | `…/echo.db` | SQLite 库 |
| videos / covers / uploads / inbox | `…/videos|covers|uploads|inbox` | 视频文件 / 封面 / 编辑器插图 / 待入库 |
仓库 `data/` 为空壳，不是运行时目录。

## 6. 数据库（26 表）
见 `docs/DATABASE.md`（自动生成）。关系速览：
```
creators → creator_accounts → platform_posts → platform_post_stats / platform_post_comments
                              └─ work_id → works（跨平台合并）
                              └─ local_video_id → videos → transcripts / metrics_snapshots
videos → drafts → feedback / draft_discussions
hot_topics → topic_candidates → drafts
creators → persona_tags / creator_account_snapshots
background_tasks / sync_jobs / notifications / app_kv
```
要点：
- `platform_posts(platform, platform_post_id)` 唯一；`platform_post_stats(post_id, stat_date)` 唯一；
  `platform_post_comments(post_id,text)` 业务去重（含 likes）
- `sync_jobs` 带 R-070 进度列 progress_done/progress_total/progress_note，供前端进度条轮询
- 时间列统一北京时间（core/timeutil.now，R-066）

## 7. 关键数据流
1. **导入学习**：上传/inbox → videos 行 → 编辑页手动「语音转文字」（抽音轨→按 .env 选 阿里云 FileTrans(OSS 中转) 或 硅基流动直传，R-108→校对稿回填）→ 确认标签 → 进入人设/风格语料
2. **平台同步**：run_sync（daily top15 带视频下载转写 / weekly 3 / initial 全量）→ 账号并发（每平台独立线程/会话）→ 作品 upsert + 指标按天 upsert + 评论 Top50 → auto_merge 合并 work → daily 再对前15条媒体补齐（下载+转写，R-085）→ 进度实时写 sync_jobs → 完成通知
3. **选题/生成**：热点/灵感 → 人设+风格检索加权（TF-IDF/RAG）→ 生成（可双模型讨论）→ 草稿 → 作者改写 → 反馈回流
4. **复盘**：本地指标 + 平台数据 → 看板增长曲线 → ABCD 复盘报告

## 8. 质量与安全
- 门禁 `scripts/verify.sh`：ruff + mypy + pytest（53 项，离线 mock）+ 前端 lint/build + 文档存在性
- Web 入口 `X-Access-Token`（ECHO_ACCESS_TOKEN）；静态资源 /health/openapi 免令牌
- 密钥仅 .env（gitignore）；备份每日自动 + 手动脚本
- 预算护栏：TikHub 每日请求预算（默认 2000，Kv 可覆盖），超限停止本轮并通知
