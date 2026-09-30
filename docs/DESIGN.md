# DESIGN — 开发设计细节（代码级）

> 本文与代码一一对应，作为实现/排查时的地图。API 与表结构以 `docs/API.md`、`docs/DATABASE.md`（自动生成）为准。

## 0. 运行入口与配置

### backend/app/main.py
- `lifespan`：`init_db()` → `setup_scheduler()` → `start_inbox_watcher()`。
- 路由均挂 `/api/*` 且默认带 `Depends(require_token)`（`X-Access-Token`）。
- `GET /health` 免令牌；`/covers`（R-179 起带 `?w=` 时按需生成缩略图并落盘缓存 `covers/thumbs/`，注册在静态挂载之前）、`/uploads` 静态目录挂载；存在 `frontend_v2/dist` 时用 FastAPI 挂**根路径 `/`** 托管前端（hash 路由，R-208）。
- CORS 全开（局域网单用户）。

### backend/app/config.py
- pydantic-settings，env 前缀 `ECHO_`，读取根目录 `.env`（`env_file=(".env","../.env")`，从 backend 启动时解析项目根）。
- `normalize_mode(value, allowed, default)`：`TIKHUB_MODE/HOT_SOURCE_MODE/ASR_MODE` 先按 `#` 剥离行尾注释再 trim/lower，非法值**抛错**（R-068）。取值：`tikhub_mode ∈ mock|real`、`hot_source_mode ∈ mock|real`、`asr_mode ∈ mock|aliyun|siliconflow|tencent`（R-108/R-200）。
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
| benchmark.py | /api/benchmark | 博主对标：前3+最新展示（R-174）/转写补齐/AI可讲/洗稿（R-152 增 `rewrite-source`：素材库非主博主素材一键洗稿）；「重新对标」一键重跑（R-102，后台任务） |
| persona.py | /api/persona | 档案 CRUD/建议/一键确认/表达风格面板/金句候选/增量校验结果（R-128：`/check/latest`、`/recheck`）；R-131：`/style` 扩展风格范本与样本条数 |
| drafts.py | /api/drafts | 草稿 CRUD/生成(同步)/generate-async/打分；`POST` 拒绝空白草稿（R-154）且支持 `tags`；`POST /{id}/discuss` 基于原文重新讨论（R-155）；`POST /{id}/finalize` 定稿 + `GET /{id}/versions` + `POST /{id}/versions/{vid}/rollback` 回滚（R-156/R-157） |
| chat.py | /api/chat | 会话 CRUD + SSE 流式回复 |
| pipeline.py | /api/pipeline | 每日流水线手动触发/热点刷新/运行记录 |
| topics.py | /api/topics | 热点/话题缺口/匹配选题 |
| prompts.py | /api/prompts | 提示词版本 CRUD/启用/优化候选/历史回滚；R-129：候选拒绝、评测重跑、`/keys` 带评测与版本效果对比 |
| requirements.py | /api/requirements | 需求归档读写（文件为事实源） |
| notifications.py | /api/notifications | 通知列表/已读/清空 |
| tasks.py | /api/tasks | 后台任务状态查询 |
| settings.py | /api/settings | 页面可调设置 |
| uploads.py | /api/uploads | 编辑器插图上传 |

### 校验与错误
- 路由薄：参数校验在 Pydantic schema；业务在 services；HTTP 层把 `ValueError` 转 `400`（多数接口已做 try→HTTPException(400, str(exc))）。
- 后台长任务统一 `tasks.start_task(kind, payload, fn)`，完成/失败写 `notifications`（前端铃铛 + toast）。

## 2. 服务层（backend/app/services/）
- `ingest.py`：`import_video_task`（转写+校对+预打标签+入队人设增量校验+自动优化提示词触发）、`correct_transcript`、`persona_init_task`（逐篇提炼→AI 归纳合并→生成建议）、`enqueue_persona_incremental` / `persona_incremental_task`（增量 + 全量 5% 对齐校验，R-128）、`_rerun_if_pending`（任务期间有新素材则收尾补跑）。
- `transcription.py`：`Transcriber.transcribe` 按 `asr_mode` 路由：mock 假转写（离线）/ aliyun（`aliyun_filetrans` 泛化调用提交+轮询）/ siliconflow（`siliconflow_asr` 直传，R-108）/ tencent（`tencent_asr` 本地 base64 直传+轮询，R-200）。
- `aliyun_filetrans.py / aliyun_oss.py`：FileTrans 4.0（CommonRequest）与 OSS 上传/预签名 URL；上传前由 `media_tools`/`media_naming` 用 ffmpeg 抽 16k 单声道 wav。
- `tencent_asr.py`（R-200）：腾讯云录音文件识别 `CreateRecTask` + `DescribeTaskStatus`（SDK `tencentcloud-sdk-python-asr`，域名 `asr.tencentcloudapi.com`）；音频走**本地 base64 直传**（`SourceType=1`、`ChannelNum=1`、引擎 `EngineModelType` 由运行时配置，默认 `16k_zh_en_2.0`）；视频/超限音频先经 `media_tools.extract_audio_compact` 抽/压成 16k 单声道 mp3（码率按目标 5MB 自适应 16–32kbps），超限明确报错走失败通知、**不自动切换其它服务商**；结果优先取 `ResultDetail[].FinalSentence`，否则剥离 `Result` 的 `[起,止]` 时间戳。
- `siliconflow_asr.py`（R-108）：`POST {base}/audio/transcriptions` 直传音频转写（multipart file+model，无需 OSS 中转）；视频先抽音轨、纯音频直传；平台限制单文件 ≤50MB / ≤1 小时（`media_tools.probe_duration_seconds` 探测），超限明确报错走失败通知、**不自动切换其它服务商**。
- `pipeline.py`：每日流水线（R-140 起组候选与生成切片统一用 `model_settings.topics_count(db)`，即「AI 设置」的每日篇数）。`generation.py`：生成草稿（R-139 起统一调用 `debate.run_debate`：生成方初稿 + 评审方 N 轮 + 自检收口；不再单模型直出）；上下文 = 人设(tags+维度+红线+禁词) + 风格画像 + 检索到的风格样本（条数可配置 3~8，R-131） + **作者指定的风格范本**（必定注入） + **高表现内容的开场/结尾结构模板** + **作者改写稿 few-shot**（R-131；R-209 起按 source 归因：配对 = 最后一个作者侧版本 ← 其前一版，「AI 讨论后被回退」正确产出【AI 稿→作者改回的原稿】） + **被作者改回原稿的讨论方向**（R-209 反面信号 `_reverted_lessons`） + 金句/最佳实践 + 对标风格卡；黄金样本/结构模板的「认可」口径 R-211 起 = status done（历史 rating/liked 弃用）；`generation_user_message` 抽出供评测复用；生成后**自检**：**仅命中红线**才自动收口重写 1 次（R-207）；口癖/高频词覆盖率、AI 腔词只落 `drafts.quality.diagnostics`（纯诊断，不触发重写，避免机械塞口头禅→模仿腔）；草稿写入 `prompt_version`（R-129）与 `persona_version`（R-130）做归因。`_all_texts`（全量素材加权语料）供优化与每周重建（R-064）。
- **推理预算定标（R-142）**：`max_tokens` 不是消费额而是**上限**（只按实际生成量计费），所以「给足」几乎不增成本，但能保住两个能力：① 用 `finish_reason=length` 判断「被截断」（整套「识别思考吃光 → 抬预算重试 → 再降级」都靠它）；② 单次调用的成本天花板（区别于墙钟那种「花之后」的边界）。
  - 现状（R-143 起分两层）：**按任务标定的预算**在 `budget_settings.SLOTS`（可配置、存 `app_kv`、保存即生效）——脚本初稿 12000 / 评审 14000 / 修订 16000 / 对标洗稿 12000 / 转写校对 12000 / 人设归纳 8000 / 提示词优化 8000 / AI 对话 8000 / 对标可讲分析 4000；
    **厂家下限** `min_max_tokens` 退回成**安全网** 4000（只兜「有人随手写 300」，不再用它替代按任务标定）；生效值 = `max(设置, 下限)`，界面显示真实生效值；翻倍重试封顶 `MAX_TOKENS_CEILING=32000`。
  - 定标依据（实测，同一份评审提示词只改 max_tokens）：

    | max_tokens | finish | 思考 | 正文 | reasoning_tokens |
    |---|---|---|---|---|
    | 4000 | length | 5961 字 | **0** | 4001 |
    | 8000 | stop | 9869 字 | 833 字 | 6493 |
    | 12000 | stop | 9649 字 | 1034 字 | 6296 |
    | 16000 | stop | 12215 字 | 1031 字 | 8023 |
    | 4000（复测） | stop | 3945 字 | 1286 字 | 2418 |

    同一提示词的思考量波动 **2418～8023+ tokens**；预算落在波动区间内 → 约一半概率截断成空正文 → 误判降级。
  - **再校准方法**：不传 stream、逐个 max_tokens 打真实接口，记录 `finish_reason` / `reasoning_content` 长度 / `usage.completion_tokens_details.reasoning_tokens`；改动预算前 `tests/test_r142_thinking_budget.py` 会把「长输出功能的默认预算低于实测最坏值 × 余量」直接判红。
  - **可配置（R-143）**：`services/budget_settings.py` 是预算的唯一事实源（`SLOTS` / `budget_for(db,key)` / `save_budgets` / `reset_budgets`），调用点全部读它；`GET/PUT /api/settings/models` 带 `budgets`（不新增路由），前端在「模型设置」里有「推理预算（高级）」区块（含每项说明、默认值、生效值、一键恢复默认）。
  - 「不传 max_tokens（交给服务端默认）」实测也能跑通，但会失去上面两个能力，且默认值随供应商变化而不可见 —— 已评估后选择保留显式上限（作者 2026-09-12 选 A）。
- **宽表与长串的布局约定（R-148）**：`.table th/td` 必须能换行（`overflow-wrap: anywhere` —— 它参与
  min-content 计算，长 slug/路径不会再把表格撑宽）；**列多或含控件的表要用 `table-layout: fixed` + 显式列宽**，
  不要靠内联 `min-width`（`table-layout:auto` 会把剩余空间全塞给某一列：实测「状态」列被撑到 805px）；
  `.table-wrap` 只作极窄屏兜底。验收方式：headless Chrome 量 `documentElement.scrollWidth - clientWidth`
  与 `wrap.scrollWidth - wrap.clientWidth`，两者都必须是 0。
- **AI 对话作为受限 agent（R-147）**：`ChatService.reply(..., conversation_id, on_step)` 是「多步工具循环」——
  回合/工具预算/墙钟可配，到限**收尾作答**而不是抛错；`on_step` 把每步（工具名/参数 → 结果摘要）抛给
  `api/chat.py::/stream`，后者用「后台线程 + 队列」把它转成 `event: step`（真正的步骤级流式，而不是"全算完再吐字"）。
  - **读**：`sql_query` 只允许查 `app/core/analytics_views.py` 里的 8 个只读视图，安全边界四层
    （只读连接 / 单条 SELECT / 表引用白名单 / 资源上限），见 `services/chat_sql.py`；系统消息注入视图 schema 卡片。
  - **写**：写工具只登记 `agent_actions` 提案（`pending` + 影响范围 `preview`），作者点「确认执行」后才落库；
    `services/agent_actions.py` 负责 propose/confirm/cancel 与审计；`services/draft_flow.py` 提供
    「建占位稿 + 入队讨论」「同稿回炉」两个动作，供 API 与 agent 共用。
  - **不做**：沙箱跑代码/shell（P3）—— 需独立容器 + 只读数据副本 + 禁网，风险高于收益。
- **AI 对话的接地气（R-146）**：`services/chat_service.py` 的工具凡是**分页**的都必须返回
  `{total, returned, truncated, <items>}`（`total` 用 `q.count()`，是**筛选后**的真实总数）——
  否则模型会把这一页的条数当成总数（实测「292 条素材」被答成「50 条」）。
  另外 `reply()` 会把**程序固定**的 `TOOL_DATA_RULES`（数量只认 total、不许编造、引用用真实标题/id）
  追加在系统消息末尾；它不落在 `ai_prompts` 里，所以「提示词优化」改不到 —— 与 R-129 的
  「可优化段 + 程序固定契约段」同一思路。新增工具时照这个模式走（有契约测试兜住）。
- **库结构与增量升级（R-144）**：结构事实源是 `backend/app/models/*.py`；启动时 `init_db()` 执行
  `create_all`（建缺失的表）+ `_ensure_indexes()`（补索引，`create_all` 对已存在的表整个跳过，所以索引要单独补）
  + 24 个幂等 `_migrate_*`（`PRAGMA table_info` 判存在 → `ALTER TABLE ADD COLUMN`，新列 `NOT NULL` 必须带 `DEFAULT`）
  + `ensure_defaults`（seed 默认提示词）。
  - **注意**：`create_all` **不会给已存在的表补列** —— 所以「往模型加字段」必须手写迁移，否则线上 `no such column`。
  - **启动顺序（R-145）**：`pending_upgrade()` 判断是否有待应用变更（库文件不存在=全新安装→跳过；结构已最新→跳过）
    → 有变更则 `auto_backup_before_upgrade()` 先备份到 `data/backups/pre_upgrade/<时间戳>.db`（SQLite backup API +
    `integrity_check`，保留 5 份，失败只告警不阻断）→ `init_db()` 升级 → 结构自检。这样「打包上去、启动就好」才安全可回滚。
  - `core/schema_guard.py`：① `missing_schema(bind)` 把模型声明的表/列与实际库对一遍；启动时 `run_startup_check()`
    跑一次，缺了就日志 error + 站内通知 + 落 `app_kv`（**绝不阻塞启动**）；② 迁移记账 `record_migration` / `migration_status`，
    表 `schema_migrations`（首次写基线 `baseline_pre_r144`），启动日志打印「库结构版本」。
  - 测试护栏：`tests/fixtures/schema_baseline.sql` 是生产库**结构快照**，`tests/test_r144_schema_guard.py`
    用它模拟老库跑 `init_db()` 并断言「模型每一列都存在」—— 治「本地测试全用全新库，漏写迁移 100% 绿」。
- `notify.py`（R-141）：`mail_config_problem(settings)` 是邮件配置的唯一体检入口（缺失 / 非 ASCII 占位符 / 非法邮箱 → 可读原因）；`_send` 把配置非法与 SMTP 异常都收敛成「log + 返回 False」，中文主题用 `Header(...,'utf-8').encode()` 做 RFC2047 编码，正文用 `msg.as_bytes()` 发送。因此邮件是**次要通道**：`run_daily_pipeline` 只在稿子生成失败时才置 failed。
- `platform_sync.py` 的灵感池入池（R-140）：`pool_ideas_from_comments(db, post, comments, *, account=None, per_post=None)` 是「评论 → 选题池」的**唯一实现**——`_collect_comments()`（全量/每周，非队列）与 `sync_post_comments()`（daily 逐素材队列 / 单帖）都调用它。限量：单帖 `ECHO_POOL_IDEAS_PER_POST`（默认 8，按点赞降序）、单博主每天 `ECHO_POOL_IDEAS_PER_DAY`（默认 40，`0`=不限）；保留「标题 ≥4 字」、按 `(source,title,snapshot_date)` 去重、重复点赞取大。`_pool_quota()` 负责当天剩余配额。同步说明与 payload 汇报 `pool_ideas`（灵感池新增 N 条）。
- `debate.py`：**所有脚本生成的唯一路径**（R-139）。`debate_rounds(db)` 取「AI 设置」轮次（Kv `debate_rounds` > `.env` > 5，夹 1–10）；`snapshot(db).generation_pair()` 解析生成方/评审方（可相同）；`_side_llm` 把某一方包成「该槽位主用 + 另一方兜底」；初稿用 `generation_user_message`（与金样本回放同一输入），**仅红线命中**再做一次收口修订（R-207：口癖/高频词覆盖率、AI 腔词只诊断、不重写）；结果写 `draft_discussions` 与 `Draft.quality`（models/used/fallback/rounds/rounds_done/issues/passed/style_coverage/diagnostics）。**R-178**：每条留痕还落库**实际出结果**的模型（`_llm_model_fields` → `used_slot/vendor/model_id`，取 `RoutedLLM.used_*`，降级后以事实为准）；每次讨论开头写一条 `kind='run'` 运行头（`_run_header`：当时配置的生成方/评审方 + 轮次，结束 `_finish_run_header` 回填 rounds_done/degraded）；状态条文案与接口展示统一走 `model_label()`（复用 `model_settings.VENDORS` 标签 → `DeepSeek · deepseek-flash`），不再出现槽位名 `model1/model2`。入口：`run_debate`（通用；R-155 增可选 `source_text/source_title`：传了就按原文改写出 标题/封面字/正文/标签，写回 `original_script` 供原文对照、`merge_tags` 合并去重，随后同样 N 轮+自检）、`run_debate_draft`（工作台后台任务）、`run_rewrite_debate`（对标洗稿，R-118）。原文讨论的入队/解析在 `draft_flow.resolve_discussion_source` / `start_discussion` / `discussion_task`（任务 kind=`draft_discuss`）。
- `library_service.py`（R-179）：**素材库列表的唯一口径**——本地素材（`video_query.visible_videos_query`，含 R-107 禁用账号排除）
  + 云端作品（与 `/api/works` 同分组：work_id 合并 + 未合并单条，成员按平台名排序）→ 剔除被云端作品绑定的本地素材 →
  按日期倒序（同日 kind/id 兜底）→ 筛选（平台/状态/有无视频/广告/关键词/标签/点赞区间，与搬移前前端 `applyFiltersTo` 同语义）→
  **游标分页**（`(date,kind,id)` 不透明串，滚动期间后台同步插入新条也不重复/漏条）。`GET /api/library` 返回
  `{total, filtered_total, facets.tags, items, next_cursor, has_more}`；前端 `useInfiniteQuery` 每批 20、距底 1 屏预取。
  卡片封面统一走 `?w=400` 缩略图（`core/thumbs.py`：按需生成 + `covers/thumbs/` 缓存 + 启动后台预热 + 上传/同步落地时顺手生成）。
- `draft_status.py`（R-173）：**草稿 AI 长任务状态的唯一事实源**——讨论/洗稿/回炉/AI 生成共用一个键
  `app_kv['draft_ai:{id}']`（JSON：`state`(running|failed) / `kind` / `note` / `actor` / `phase` / `round` / `rounds` / `at`），
  不新增表、不新增字段。`set_running` 每个步骤覆盖写（`debate._status` 是它的薄封装），
  跑满 `clear`（删键 → 前端判定「讨论完成」），失败/中断 `set_failed`（保留「上次讨论中断（可重新讨论）」标记，**不转圈**）。
  读取侧 `read` / `read_many`（列表批量，无 N+1，新键优先）兼容 R-173 之前的旧键 `debate:{id}`（纯文案），
  写新键时顺手删旧键；`reset_stale_on_startup` 在服务启动时把残留 `running` 改判「服务重启，任务中断」（`tasks._cleanup_stale_draft_ai_state`）。
  两类「中途失败」也走 `set_failed` 而不是静默清空：① 任务整体异常（`draft_flow.debate_task` / `discussion_task`、
  `benchmark.rewrite_worker`、`api/drafts._rework_task`）；② R-118 允许的「某轮评审/修订失败就以当前稿定稿」——
  此时留痕里那条 note 仍在，卡片同时显示「讨论 x/y 轮后中断」，避免作者误以为这是正常结果。
- `llm_router.py`（R-139）：统一模型路由与降级层。`snapshot(db)` 取线程安全的配置快照（普通 dict，无 Session）；`RoutedLLM` 接口与 `OpenAIClient` 兼容（`chat`/`chat_json`/`chat_completion`），主模型「输出不合法」可重试 1 次，随后降级到备用槽位；降级触发=报错/超时/空正文/缺契约字段（`chat_json(require=(...))`）；参数归一化=不支持 temperature 的厂家不传该参数 + `max_tokens` 抬到厂家下限（防推理模型正文被思考吃光）；降级写日志 + 站内通知（`_default_notify`，同功能 30 分钟冷却，自己开短连接所以跨线程安全）；`RoutedLLM.degraded/used_slot/routing()` 供调用方标记。`primary_llm(db, feature)` 是非脚本生成功能的统一入口。
- `llm.py` 的两个关键健壮性设定（R-139）：① `min_max_tokens` 归一化保证推理模型的思考不把正文预算吃光（R-142 实测定标：DeepSeek 8000 / Kimi 10000——同一步骤思考量波动 2418～8023+ tokens，定低了就会「评审总是降级」）；② `_post` 用**流式读取（`iter_bytes`，httpx 负责解压 gzip）+ 墙钟上限**（`ECHO_LLM_TIMEOUT_SECONDS`，默认 600s）；不设 stream 时 `read` 等价于「单次调用总时限」，故与墙钟同值，语义为「单次调用最多 600s」。连接级瞬时错误由 `llm_router` 重试一次（超时不重试）——httpx 的 read timeout 会被长连接的持续字节重置，实测一次调用挂过 39 分钟；HTTP 4xx/5xx、响应结构异常、空正文+有思考分别转成可读的 `LLMError` / `LLMUnusableOutput`。
- `model_settings.py`（R-138）：模型槽位配置（`VENDORS` 厂家目录、`SLOT_KEYS`、`ROLES`、`ASR_MODES`、`ASR_SILICONFLOW_MODELS/ASR_TENCENT_MODELS`）；`get_model_config` 含旧 `generation_model` 无感迁移、ASR 默认模型按服务商感知（`default_asr_model`/`_coerce_asr_model`，R-200：切腾讯后不沿用上一家模型名）；`resolve_slots/generation_roles/asr_config/topics_count` 供运行时读取；全部存 `app_kv` → **保存即生效**（`Transcriber(mode=..., model=...)`、`SiliconFlowASR(model=...)`、`TencentAsr(model=...)` 也改为接受运行时覆盖）。
- `model_health.py`（R-139）：保存模型设置后异步跑双模型兼容性自检（3 个极简样例 × 2 个槽位，校验文本/JSON 契约），结果写 Kv `model_selfcheck_result`，由 `GET /api/settings/models` 的 `selfcheck` 带回前端并写站内通知。
- `topic_mining.py`：热点源类（mock/公开接口/Bilibili、Douyin、Xiaohongshu/TikHub 热搜实现）；`get_sources` 按 `hot_source_mode` 选择；`fetch_and_store` 入库去重（platform+title+date）。
- `persona.py`：LLM 分析（逐篇提取 `analyze_one` / 全量归纳 `merge_full` / 增量合并 `merge_incremental` / 语义复核 `compare_profiles` / 打标）；提示词只给「方向盘」（角色+观察方向），维度与措辞由 AI 自定，程序只解析固定字段；`_split_phrases` 与 `suggest_phrase_candidates`（金句候选）。
- `persona_profile.py`（R-128）：人设分析管线——`extract_pieces`（逐篇提取，结果按「提示词指纹+文案 hash」缓存于 app_kv，内容不变复用、与全量重算等价）、`full_profile` / `merge_profile`（全量归纳合并：优先把每篇提炼结果原样喂模型做全局归纳，失败或 >120 篇再走「机械近义去重 + 分批归纳」）、`incremental_profile`（当前档案+新篇）、`profile_coverage`（集合覆盖率，支持近义模糊匹配）、`compare_profiles`（覆盖率 + AI 语义复核，均 ≥95% 才通过，否则回退全量）、`current_profile` / `persist_suggestions`（维度→category 映射落库，含 150 条防御上限）。
- `prompt_service.py`：提示词 key→版本管理；`ensure_defaults`、`save_new_version/enable_version/create_candidate`、`reject_candidate`、`get_prompt_version`、`prompt_group`（人设引擎/生产提示词分组，R-130）、`version_effect`（按版本聚合草稿反馈 + 人设版本跨度提示；R-211 认可口径=status done，历史 rating 仅参考）、`feedback_context`（**R-211 status 驱动**：认可=done / 避免=archived 非纯手写，附作者亲笔评价 + insight 复盘心得；历史 rating/liked/四维分弃用）、`learning_material`（全量加权前 16 条 + **AI 归纳合并后的人设档案**，R-064/R-128）、`optimize`（R-129：按 key 语料 → 注入契约与上下文说明 → 候选自检失败重试 1 次 → 契约段程序拼接 → 自动排队评测；失败抛 `PromptOptimizeError`）、`maybe_auto_optimize_prompt`（R-208：素材累计阈值自动排队优化生成提示词，样本不足静默跳过；取代 R-131 的只发提醒）、`auto_optimize_generation_task`、`optimize_rule_keys_task`（手动一键优化规则型 key）。`OPT_SYSTEM` 明确「不得写死作者传记/红线，只给方向盘」，并给出**可改（角色/方法/结构/篇幅/原则）与不可改（事实/红线/输出契约）清单**；候选受 **≤1.5×当前版本** 的长度约束（R-132），并要求模型附「变更说明」写进候选 note。
- `prompt_contract.py`（R-129）：提示词优化契约——`material_for`（按 key 取真实样本，取不到返回空→「样本不足」）、`contract_for`（程序固定的输出契约段）、`context_note_for`（运行时 user 上下文说明，避免优化器重复注入）、`budget_for`（长度预算）、`validate_candidate`（长度/契约字段/写死事实校验）、`assemble_candidate`（可优化段 + 契约段分层拼接）。
- `prompt_eval.py`（R-129 M115）：金样本回放评分——`golden_set`（高表现素材选题 Top5 + 高/低分草稿各 3 条 + 风格标记 + 红线）、`_probes`（按 key 组装回放输入）、`_score_outputs`（格式合法率/红线命中率/像作者率 → 综合分）、`evaluate`（候选 vs 当前版同批金样本对比，落 `prompt_evals`）、`prompt_eval_task`（后台任务 + 通知）。只展示分数，不设启用门槛。
- `style_profile`（core）：口癖/句长/感叹反问占比等画像；R-057 表达风格面板 + 禁词注入。
- `metrics.py`：`_platform_breakdown`（平台最新指标，供生成加权）/`summary`/`radar`（赛道雷达，R-136 自 review 迁入）/`apply_retention`（热点 30 天清理）；R-136 已删除无调用方的 upsert/import/fetch/series。
- `chat_service.py`：只读工具集 + 流式问答；工具：search_videos/get_video_detail/get_persona/list_requirements/get_metrics_summary/get_today_topics/get_review_report/get_radar/search_drafts/generate_draft（写操作需明确同意）。SSE 由 api/chat 组装。
- `benchmark.py`：对标聚合（**R-174：最新15条按互动分取前3 + 第四篇=该对标最新一篇**（共 4 条；重叠按互动分顺延保位，R-152 原为前2+最新=3 条），R-109：10→15；广告/同款漏标过滤；文案只用 ASR 转写稿）+ `target_units`（R-152 统一的展示/补齐目标选取，`with_text_first` 保留 R-106 展示口径）+ `ensure_top_with_text`（前3+最新缺文案自动下载转写、无文案顺延；有文案后严格 AI 审核软广/商单/引流并落库排除，R-103/R-106）+ `resolve_rewrite_source`（R-152：素材库按 video_id/post_id/work_id 解析 ASR 文案与来源，供 `/rewrite-source` 洗稿）+ `rerun_benchmarks(db, owner, update, refetch)`（R-102/R-109：refetch=True 手动重捞最新15条；refetch=False 每日同步后自动触发、不重复拉取，只重算前3+最新/补缺转写）；/top 有文案优先（空文案被下一条顶上，R-106）。
- `platform_sync.py`：见 §4。
- `works_service.py`：标题规范化（去话题/标点/空白/小写）+ 自动合并 + 手动合并/拆分 + `list_works`（合并作品含各平台）+ `post_item`（作品序列化）。
- `creator_service.py`：当前博主/切换/账号元数据/全网粉丝汇总/删除保护。
- `platform_assets.py`：封面/头像下载本地、HEIC 兼容、占位 SVG（mock 无封面时）。
- `notify.py`：QQ SMTP 每日推送 digest/失败告警（HTML）。
- `requirements_service.py`：以 `requirements/` 文件为事实源读写（列表/详情/新建/状态机）。
- `media_naming.py / media_tools.py`：R-058「标题-视频/封面」命名、抽音轨工具。
 - `diff_analysis.py / feedback.py / feedback_analysis.py`：改稿差异分析、反馈回流、反馈学习分析（R-211）。
   R-156：`analyze_diff` 接收**版本链**（初稿→…→定稿）看逐版修改；`diff_task` 为后台任务体。
   **R-209 归因**：版本 `source` 分**作者侧** `{manual, rollback}` 与 **AI 侧** `{ai_generate, ai_discuss, ai_rewrite}`；
   `analyzable()` 判定——终版必须是作者侧（否则学到的是 AI 的改动而不是作者偏好）且链中须有 AI 侧版本
   （否则是纯手写自改，R-210 只学正文）；`analyze_sourced_diff` 按 source 标注每版身份并附归因规则
   （AI 版间差异 ≠ 作者修改；回退 AI 版 = 否定该方向）。
   **R-211 反馈学习**：`feedback_analysis.maybe_trigger` 挂在 `PATCH /drafts/{id}` 状态流转上——
   进 `done`（完成=好）/ `archived`（不采用=差，**纯手写稿豁免**）入队 `feedback_analysis` 后台任务
   （卡片状态条「学习分析中」，`draft_status` kind=`feedback`，R-202 切页可恢复）；
   LLM 分析「正文 + 带归因的版本链 + 评价文本」为什么好/差，心得落 `feedback.insight`。
 - `draft_versions.py`（R-156/R-157/R-209/R-210）：定稿快照 `snapshot_version`（支持 `content` 覆盖，用于「洗稿前 ASR」这类非当时状态的快照）、
   `finalize_version`（留一版 + 按 `analyzable` 判定才入队差异分析）、`list_versions`、
   `chains_for_drafts`/`version_stages`（≥2 版用版本链，否则退回原文→当前稿）、
   `chains_with_sources`（R-209：带 source 的链，归因消费用）、`pure_manual_map`/`is_pure_manual`（R-210：
   纯手写=source manual 且无讨论记录且无 AI 侧版本，讨论过即使回退也不算）、`latest_comment_map`（R-211）。
   自动留版：洗稿 `run_rewrite_debate`（前=素材 ASR、后=洗稿稿）、讨论 `draft_flow.discussion_task`（无版本先留「讨论前」再留「讨论后」）、
   AI 生成 `generation.generate_draft` 与 `draft_flow.debate_task`（`snapshot=False` 用于金样本自测 / 回炉中间稿，回炉结果记到原稿）。
   回滚（R-209 推翻 R-157）：覆盖写回 + **留一版 `source="rollback"`**（note「回退到版本 #N」）；跨过 AI 侧版本时
   `debate.mark_latest_run_reverted` 回填最近讨论运行头 `reverted: true`（为双模型组合效果统计留事实）。

## 3. 核心算法（backend/app/core/）
- `timeutil.py`：`now()/today()/tz`（默认 Asia/Shanghai，`ECHO_TIMEZONE` 覆盖）——全项目唯一时间来源。
- `retrieval.py`：字符二元组 TF-IDF 检索（中文）。
- `style_profile.py`：风格画像统计。
- `transcript.py`：转写稿切分/处理。
- `matching.py`：热点标题与确认关键词的命中打分。
- `metrics.py`：互动率等规范化。
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
- **限速与重试（R-151 → R-163）**：R-151 曾按「单路由 1 请求/秒」串行排队；R-163 依 TikHub 套餐口径改为**全局合计 ≤ 10 请求/秒**——`_throttle_route(path)` 先过**进程内全局令牌桶**（`_TokenBucket`，速率 `ECHO_TIKHUB_RATE_LIMIT` 默认 10、容量 `ECHO_TIKHUB_RATE_BURST` 默认 10；锁内预留令牌、锁外 sleep），所有接口共享，是并行消费的前提；并保留：
  - **按路由 429 退避兜底**：某 path 收到 429 时 `_penalize_route` 临时抬高该路由下次允许时间（`_ROUTE_BACKOFF_SECONDS=2s`），避免持续撞限流；`_ROUTE_MIN_INTERVAL` 默认 0（可配，用于需要时恢复按路由排队）。
  - 有界重试 4 次尝试、退避 `1.5s → 4.0s → 8.0s`，仅对 `httpx.TransportError`（SSL EOF/连接重置/超时）与 HTTP `429/500/502/503/504` 生效；**4xx 永久错误立即抛**；被限流时服务端有时直接掐断 TLS 隧道（本机 httpx 读 macOS 系统代理 `127.0.0.1:7890`）。
  - 重试 `warning` / 最终失败 `error` 写日志（R-133 logger），错误消息保持 `TikHub 请求失败:` 前缀并追加「（已重试 N 次）」。

### 幂等与去重
- 作品：`(platform, platform_post_id)` 唯一约束 + `_ensure_post` 先查后建/更新（含 title/cover/publish_time/raw/tags/cover_path）。
- 指标：`(post_id, stat_date)` 唯一 upsert（当天多次同步覆盖成最新，历史保留）。
- 评论：`_upsert_comments` 按 post_id+text 去重、点赞保留更高值、**按点赞降序取 Top50**（R-067）。
- 进度：`sync_jobs.progress_done/progress_total/progress_note`，`_job_progress` 用 SQL 原子累加（R-070）；`GET /api/platform/jobs` 输出进度供前端轮询（R-161：可选 `status` 过滤，前端只拉 `status=running`，避免历史 job 挤占运行中进度）。

### 编排（run_sync）
- 入口：手动（博主页 全量/前15条/对标单账号「同步」/单账号/当前主博主「同步所有博主前15条」）、定时（06:00/17:00 两轮 `run_daily_sync_all`：主博主+全部对标统一 daily 带视频下载转写，R-109）、单条（posts/videos/works 同步）。
- R-162（替换 R-160）：`enqueue_all_top15_sync(owner)` 为「当前主博主 + 全部对标」各写一条 `platform_sync` 队列任务（pending）并**预置一条 running 的 SyncJob**（progress_note=「排队中…」，前端所有卡片立即显示动画）；已在排队/执行的博主与无启用账号者跳过。接口 `POST /api/platform/sync-all`（无主博主/无可同步博主 400，同批任务在跑 409）。
- **R-163 并发消费**：`all_top15_worker` → `run_all_top15_sync(owner, entries)` 用 `sync_pool.gather` **线程池并行**消费博主（替代 R-162 的逐个串行）——每个博主一个新 Session、`sync_pool.claim_task` 原子认领其 pending 队列任务（`UPDATE … WHERE status='pending'`），复用预置 job 调 `run_sync(scope=daily, creator_id=…, with_media=True, job=…)`；单个失败不阻断其余，任一 `BudgetExceeded` 触发取消标记、未开始者置 failed；完成后 `maybe_start_benchmark_rerun(refetch=False)`。定时 `run_daily_sync_all` 同样并行（主博主沿用 `creator_id=None`，对标显式 id）。
- `scope=daily`：每平台 top15（R-085/R-086 最终 15）；`weekly`：对标每账号 top3；`initial`：`count<=0 → _real_posts_all` 翻页全量。daily 且 with_media=True 时同步后对前 N 条跑媒体补齐（下载视频+自动转写）。
- 并发：账号级 `ThreadPoolExecutor(max_workers=3)` 每账号独立 SQLAlchemy session；**R-163** 博主级 `ECHO_SYNC_CONCURRENCY`（默认 4）、素材级 `ECHO_SYNC_MEDIA_CONCURRENCY`（默认 2，独立小池），`services/sync_pool.py` 提供 `claim_task`/`gather`/`pool_size`/`session_factory`。素材队列 `run_card_sync_queue` 亦并行：每条独立 Session；同一合并作品去重改由主线程按平台优先级**确定性预标记**（避免并发重复下载）；单条失败/预算耗尽只影响自身与未开始条目；评论/灵感池计数即使媒体步骤失败也如实汇总。
- 结束：`auto_merge_creator` 合并同标题跨平台帖 → `works`；写 SyncJob stats/message + 账号 sync_status；通知中心收到完成。
- 本地素材卡片同步 `sync_local_video_metrics`：遍历 `_bound_platform_posts`（local_video_id + work_id + platform_post_id 三路去重）拉各平台指标 + 评论 Top50，并写 `metrics_snapshots`（当天多平台聚合）；单平台失败不中断，全部失败才报错。
- 云端合并卡同步 `sync_work_posts`（R-067 新增）：遍历 work 下全部平台帖（原只同步 cloudPosts[0]）。

### 卡片同步按钮状态（前端 R-069）
同步中状态按卡片唯一 `key`（`v<id>` 本地 / `w<id>` 合并 / `p<id>` 单条）判断，避免 work_id 与 post id 数字撞车误高亮。

## 5. 定时与后台（scheduler.py / tasks.py）
- 计划见 ARCHITECTURE §4。`_platform_sync_job` 通过 `start_task` 跑 `run_sync(scope=daily)`。
- R-109：取消原独立 06:00 自动「重新对标」定时（R-105）；每日两轮同步完成后由 `run_daily_sync_all` 自动触发一次「重新对标」（`maybe_start_benchmark_rerun(refetch=False)`，已有 rerun 在跑则跳过），对标页手动「重新对标」仍 refetch=True 重捞最新 15 条。
- `tasks.py`：`background_tasks` 表 + daemon 线程；progress 0→10→100；完成写 Notification；`import_video` 完成后累计素材到阈值（默认 10 条）**自动排队优化生成提示词**（R-208，取代 R-022/R-064/R-131 的自动产出/提醒）。
- **R-202 非实时结果可见**：① `core/task_meta.py` 提供 `KIND_LABELS` + `target(kind,payload,result)`，`tasks.py`（通知）与 `api/tasks.py`（列表）共用；`TaskOut` 增派生字段 `label/target`（不落库）。② `/api/tasks` 的 `status`/`kind` 支持逗号分隔多值，`status` 含 running/pending 时按 `created_at` 正序。③ SSE `task.update` 负载带 `kind/label/target`，供前端顶栏指示器直接消费。④ `find_running_task(kind, payload_match)`：同 scope 已在跑则复用其 task_id（防重复烧 LLM）。⑤ 原同步慢接口改为后台任务：`benchmark_prepare`/`opportunity_clusters`/`opportunity_weekly`/`opportunity_gap`/`draft_angles`/`prompt_optimize`/`hot_refresh`/`publish_backfill`（结果落 `task.result`）；前端 `ActiveWorkProvider`（挂载回扫 + SSE + 10s 轮询兜底）+ `useTaskScope`（task_id 存 sessionStorage，切页/刷新恢复）。规范见 §8.6。
- `watcher.py`：10s 轮询 inbox，移入 videos 目录并建 `Video` 行（文件名 uuid 前缀防重），**不自动转写**（R-033，手动按钮触发）。

## 6. 前端结构（frontend_v2/）
- **唯一前端**（R-164；老前端 `frontend/` 已于 R-208 下线删除）。React 19 + TS + Vite + Tailwind v4 + shadcn/ui + Framer Motion + TanStack Query；API 客户端类型由 `/openapi.json` 生成（`npm run gen:api`）。dev 3000 代理 8000，生产 build 后由 FastAPI 挂**根路径 `/`**。
- `src/router`（hash 路由）、`src/api/`（client + 生成类型 + 任务）、`src/hooks/`（`use-active-work` 进行中底座、`use-task-scope`）、`src/lib/motion.ts`（动效令牌）。
- `src/pages/`：home（内容机会/热点灵感）、videos（素材库卡片墙 + 右侧抽屉编辑）、drafts（脚本工作台四 tab + Tiptap + 讨论 + 正文对比 + 版本；**新建草稿实时保存** `pages/drafts/autosave.ts`，见下）、**prompter（R-214/R-215 全屏提词器 + 内置网页录像，顶层路由，不进 AppShell）**、chat（SSE）、persona（人设四层 + 高置信自动确认徽标/撤销）、prompts（AI 设置：基础/高级两层）、benchmark、creators（时间线）、login。
- **草稿实时保存（R-212）**：`pages/drafts/autosave.ts` 是**不含 React/DOM 的纯逻辑**（`createAutoSaver`，11 例单测），抽屉只做接线：
  - 只对「本次由【新建草稿】进入」的会话启用（`draft === null`，会话内持续有效；打开已有稿仍是【保存】/【取消】）；
  - 任何变动 → 防抖 900ms：首次 `POST /api/drafts`（沿用 R-154「全空不建稿」），拿到 id 后走 `PATCH`；内容指纹相同不重复写；
  - **单飞 + 队列**：保存进行中又有改动就排队，当前这次完成后继续写最新内容（否则保存期间敲的字会漏）；
  - 关抽屉（遮罩 / X / Esc /【关闭】）→ `closeOut()` 立刻补一次（防抖窗口里的最后几个字也不丢）；【保存】/讨论回填的服务端内容用 `markSaved()` 记账，避免重复 PATCH；
  - 自动建出的稿被清空 → `onDiscard(id)` 交页面 `PATCH {status:'deleted'}` 逻辑删除（不留空卡片）；
  - 组件跨会话常驻挂载 → 每次打开必须 `saver.reset()`（否则上一轮的 id 会被复用、把内容写到上一张稿上）。
- **草稿断网兜底（R-213）**：`pages/drafts/local-copy.ts` 管**一份**「还没同步到服务器」的 localStorage 副本（`echo_v2_draft_local_copy`，含内容 + 时间 + 草稿 id；读写都不抛，脏数据读成 `null`）。
  - **顺序**：`schedule()` 里**先写本地副本、再排防抖**——断网/刷新/关抽屉都留得住；`persist` 成功且没有更新的 `pending` 时才 `storage.clear()`（否则会把并发期间的新改动一起清掉）。
  - **失败分类**：`4xx`（`ApiError.status`）= 请求本身有问题 → `'error'` 不重试；其余（断网/超时/5xx）→ `'offline'` + 退避重试 `1s→2s→…→30s`（读 `pending`，**抽屉关了也继续补**），`window online` → `retryNow()` 立刻补。
  - **恢复**：打开抽屉读一次副本，仅当「副本 id 与当前稿匹配（副本 id=0 ↔ 新建草稿会话）」时显示提示条 `data-testid="draft-local-copy"`（`softIn` 起步 0.85）——【恢复】回填编辑器、【丢弃】删副本，**不静默覆盖**服务端内容。
  - `dispose()`（卸载）**故意不清副本**：这正是刷新/关标签页后还能恢复的原因。
- **提词器 + 内置录像（R-214 / R-215，`pages/prompter/`）**：全屏页 `#/prompter/:draftId`，**顶层路由不进 `AppShell`**（无导航/顶栏），`Esc` 回 `#/drafts`；后端**零改动**（只读 `GET /api/drafts/{id}`，录像走既有 `POST /api/videos/upload`）。
  - `prompter-text.ts`（纯逻辑，20 例单测）：Markdown → 口播纯文本（图片降级 alt、表格拍平、围栏代码/分隔线不口播）→ 按空行分段；字数（不计空白）→ 时长 `├ 字数 ÷ 4 字/秒 ┤`；`rAF` 匀速推进 `advanceScroll(scrollTop, dt, 速度, max)`；设置（字号 28–120 / 行距 1.4–2.4 / 速度 4–160px·s⁻¹ / 镜像）落 `localStorage('echo_v2_prompter')`，脏 JSON 一律收敛成默认值不抛。
  - **读字基准线 = 屏幕上沿往下「一个行高」**（不是屏幕高度百分比）：正文首行贴屏幕上沿（作者要求视线不下移），作者读的就是最上面那行 → 这样**任何视口高度/字号**下「一进页面高亮第一段、滚到底高亮最后一段、段随滚动单调前进」都成立；底部占位 = `视口高 − 基准线`，滚动上限再按「最后一段上沿 − 基准线」夹一次，于是**停下 = 全部念完**（短稿不用滚时不停表，由作者按空格停）。
  - **浮点滚动位置必须自己记账（踩坑）**：Chromium 会把 `el.scrollTop = 0.22` 取整回 0，若每帧读回 DOM 再累加，13.4px/s 的推进会被永久抹成 0（实测「按了播放但正文一动不动，计时却在走」）。做法：`scrollPosRef`（浮点）为权威值，只在 `Math.round` 变化时写 DOM；暂停/手动滚动时以 DOM 为准回灌（差值 > 1~4px 即认为是用户滚的）。
  - 正文区**零动画**（`transition: none`，只有段高亮换字色）；控制条 3s 无操作淡出（只改透明度，不改布局）；入场 `softIn`（0.9 → 1），倒计时/回放面板同样**不从 `opacity:0` 起步**（R-175）。
  - `recorder.ts`（纯逻辑，20 例单测）：格式协商阶梯 `mp4/avc1 → webm/vp9 → webm/vp8 → webm`（`isTypeSupported` 抛错视为不支持）并在状态带**明示实际格式**；`MediaRecorder` 1s 分片、块留内存；状态机 `idle → countdown → recording → recorded`（`reset` 回 idle）；空格判据 `spaceAction`（倒计时/录制中=停止且优先；摄像头就绪且空闲=开始录制；否则=提词播放/暂停）；5 分钟安全阀；**MP4 录后校验**（读不出有限时长即判 Chrome 已知的 mp4/avc1 损坏）→ 自动 `forceWebm` 退回 WebM 并提示重录；文件名 `标题-YYYYMMDD-HHmm.ext`。
  - 设备：`getUserMedia(1920×1080@30 + 内置麦)`，授权后按 label 偏好选默认（相机优先 Insta360/Ace Pro/UVC，麦克风优先内建），失败按 `NotAllowed/NotFound/NotReadable` 给中文文案 + 【重试授权】；预览小窗在**右下角且为它留出右侧空带**（`paddingRight`），不压正文。
- 动效规范与点检见 §8；非实时结果可见规范见 §8.6。

## 7. 常见改动指南
- 加接口：api/xxx.py + schemas + services；记得跑 verify；涉及注释/文档同步。
- 加表/列：models/*.py + db.py 幂等迁移函数（init_db 注册）；改完生成 DATABASE.md。
- 改平台字段：先看 platform_sync 与 tikhub `_real_*` 解析函数。
- 改生成上下文：generation.py + prompt_service + ai_prompts 页面（版本化，不要写死进系统提示词之外的代码）。

## 8. 前端动效规范（frontend_v2，R-175 起强制）
> 作者要求：**做功能该有的动画不能省，所有的动画必须要美观流畅**。动效是产品的一部分，不是可选装饰；
> 代码评审/自测时按本节逐条对。

### 8.1 动效令牌（唯一来源：`frontend_v2/src/lib/motion.ts`）
| 令牌 | 值 | 用途 |
|---|---|---|
| `EASE_OUT_EXPO` | `[0.16, 1, 0.3, 1]` | 全站统一曲线（入场/位移都走它） |
| `EASE_SPRING` | `spring(stiffness 380, damping 34)` | 抽屉/弹窗等"物理感"位移 |
| `pageVariants` | opacity 0→1 + y 12→0 + blur 4→0，0.32s | 路由级页面切换（`AppShell` 的 `<Outlet>`） |
| `listVariants` + `itemVariants` | stagger 0.045s + y 14→0，0.34s | 列表/卡片墙入场 |
| `cardHover` / `fadeIn` | y -3 / opacity 0→1 | 卡片悬停、轻量出现 |
| `softIn`（R-178） | 0.24s，`EASE_OUT_EXPO` | **新元素/新标签入场**（模型标签、运行头摘要、新批次卡片）：配 `opacity 0.85→1` + y 8–10→0，**禁止从 0 起步** |
| `ThinkingDots`（`components/ui/thinking-dots.tsx`） | 三点循环跳动（**纯 CSS 关键帧** `.thinking-dot`，0.9s + 0.15s 错峰；R-206 起不再用 framer 循环关键帧，见 §8.4） | AI 长任务"正在思考" |

### 8.2 必须有的动效（缺一不可）
- 路由切换：页面入场（`pageVariants`，由 `AppShell` 统一提供，页面自身不要再包一层整页动画）。
- 列表/卡片墙：父 `listVariants` + 子 `itemVariants`，**只播一次**（内嵌组件定义会导致每次 re-render 重播，R-169/R-171/R-173 三次踩坑）。
- 列表「换一批结果」（改筛选/切对象后查询）：**逐格交接 + 进场是退场的倒放**，用 `lib/motion.ts#listReplace`
  （退场老动画 0.35s 淡出 + 缩到 0.94 + `index×0.035` 错峰扫过；新卡从 `opacity 0 / scale 0.8` 显影长大回 1，**0.5s + `backOut` 过冲**
  —— `0.8 → 略微冲过 1 → 落回`，过冲在中段，整段都看得见；延迟 = 本格退场延迟 + 0.35 + 0.04 呼吸）。
  同屏**同时**退场+入场会让两组卡在同一批格子里交叉淡入，新卡的动画等于白做（R-199 实测：可见卡片数全程 ≥20，用户只觉得「没有动画」）；
  但**不要顺手改退场**——作者要的就是那波老动画（R-199 第二轮返工）；进场也只用镜像 + 放大振幅（第三轮返工）。
- **`AnimatePresence mode="popLayout"` 的子元素必须 forwardRef**（R-199 真凶）：popLayout 靠给子元素挂 ref 量盒子，
  再用 `position: absolute !important` 把退场元素弹出文档流。子元素若是 `memo(function …)` 且没 forwardRef，
  framer 量到 0 → 退场元素**留在流里**：网格高度翻倍、后到的卡被挤到屏幕外去播入场动画，回来时动画早演完了
  （表现为「清掉有动画、结果卡没有动画 / 入场一点都不明显」）。`MaterialCard` 已改 `memo(forwardRef(...))` 并有回归单测。
- TAB 切换：`components/ui/tabs.tsx` 的 `TabsContent` 统一入场（Radix 未选中会卸载 Content → 每次切回都会播）；**选中态滑块**（R-204）用共享 `layoutId` 的 `motion.span` 在 tab 间 spring 平滑移动（`useId` 保证多实例不串）。
- 抽屉/弹窗：遮罩淡入 + 面板位移（`ui/drawer.tsx`、`ui/dialog.tsx`）；开关都要有退场。
  **R-205 教训**：`Drawer` 用「受控 `animate` + 关闭后延迟卸载」而非 `AnimatePresence`（React19+framer v12 下 exit 不触发）；
  消费方**不得** `if (!open) return null`（会先把组件卸载，退场根本没机会播）。Radix 弹层（通知/下拉/选择）退出必须有 `data-[state=closed]:animate-out …`。
- 加载与状态变化：骨架屏、进度条（`SyncProgressBar`）、AI 长任务状态条（讨论/洗稿/回炉，R-173）——**"在跑"必须有可见的动态**，
  不能让用户猜是不是结束了。
  - **有"保存/提交"语义的编辑区必须让保存过程可见（R-212）**：草稿抽屉底部的「保存中…（spinner）→ 已自动保存 HH:MM / 自动保存失败」
    状态位用 `softIn`（`0.85 → 1` + y 3，**不从 opacity 0 起步**），收口 `opacity 1 / transform none`；
    状态位按 `data-state` 暴露 `idle/dirty/saving/saved/error`，点检脚本据此断言。
  - **状态条的 `key` 只能跟"形态"（`running`/`failed`），绝不能含会频繁变化的文案（R-206）**：抽屉讨论 tab 曾用
    `key={state + note}`，讨论每换一步（写初稿→评审→修订→收口）就整条重挂 → 三点动画节点被替换、从头重播，旧条高度收 0、
    新条从全透明长出来（实测 8s 4 次重挂、34 帧里两条状态条并存）。文案变化应就地更新（React 直接改文本），
    重挂只留给"形态"切换。
- **直播式列表（只往下长：讨论留痕、日志、消息）必须有"跟到最新"的编排（R-206）**：
  - 入场就按 §8.2 的标准列表令牌来：父 `listVariants` + 子 `itemVariants`（0→1 + y 14，0.34s，stagger 0.045），
    与草稿页卡片墙同一套观感。**别只给一条 `softIn`（0.85→1 + y 10）**——R-206 第一版就是这么写的，
    逐帧截图确认「肉眼分辨不出」，作者反馈「切到讨论 tab 没有动画」（第二版改回标准令牌后：点下去 55ms 整列还在淡入、188ms 落定）。
  - 滚动视口**贴底**（距底 ≤24px，`pages/drafts/discuss-follow.ts#isNearBottom`）时，新条目自动跟随到底；
  - 作者**向上翻看历史**时不得抢滚动条，改为浮出可点的「N 条新留痕 ↓」（用 `softIn` 从 `0.85 / y-6` 起步），点了平滑落到底；
  - 浮层钉在滚动区**上沿**而不是下沿：抽屉 `DrawerBody` 自身可滚（上方半屏表单 + 列表 52vh 会超出可视区），
    钉在底部会被 body 裁掉一半（R-206 实测：27px 的胶囊只剩 10px 可见）；文案压正文时用实底 `bg-card`，半透明 `accent-soft` 会糊。
  - 切换进 tab 时要先把最新一条滚进视野（`behavior:'auto'`，否则新条目的入场动画又播在屏幕外）；
    `ScrollArea` 需要读滚动位置时传 `viewportRef`（真正的滚动元素是 Radix 的 **Viewport**，不是 Root）。
- 交互反馈：按钮/卡片 hover、按下、选中态（0.15–0.22s，用 CSS transition 即可）。

### 8.3 三条硬规则（踩过坑，别再犯）
1. **不能省**：新页面/新交互一律给动效；"先不做动画"不算完成。
2. **"整块面板"的切换类动画禁止从 `opacity: 0` 起步**：新面板挂载时旧面板已被卸载（Radix `Presence` / 条件渲染），
   从 0 开始会先渲染出一帧空白 → 整块内容白闪一下。**R-175 实测**：AI 设置切 tab 时 `opacity: 0.00` 帧让大卡片白闪；
   改为 `opacity 0.85 + y 8`、0.22s 后消失。**起步 ≥0.6 + 位移表达"新内容进来了"**。
   **区别对待（R-206）**：这条只管**面板/容器本身**（白闪是它造成的）；面板里的**列表子项**走 §8.2 的 `itemVariants`
   （`opacity 0 → 1` 错峰入场，与草稿页卡片墙一致）——容器背景与结构已就位，子项从 0 淡入是"列表进场"，不是"白闪"。
3. **不改变布局、必须收口**：位移 ≤12px、缩放 ≥0.96，不做高度动画（会连带滚动跳变）；
   动画结束必须落到 `opacity: 1 / transform: none`，不允许卡在中间值（R-173 的"轮询不停/状态卡住"就是判据写错的教训）。
4. **"读字工具"要主动放弃动画（R-214）**：提词正文区**逐帧零动画**（`transition: none`，段高亮只换字色、不位移不缩放），
   因为读稿时任何动效都会干扰视线；但**控制条淡出/唤醒、倒计时数字、REC 红点呼吸、回放面板入场**这些"状态表达"照样要给
   （判据：正文区 40 帧 `opacity/transform` 只有 1 种取值 + 0 个 running animation，见 §8.5 的 `r214-prompter.mjs`）。

### 8.4 反例（已踩过的坑）
- 从 `opacity: 0` 起步 → 切换时白闪（R-175）。
- 组件定义在另一个组件函数体内 → 每次 re-render 都是新类型 → 整棵子树重建、入场动画重播（R-169/R-171/R-173）。
- `AnimatePresence mode="wait"` 包 React 19 的 `Outlet` → 页内 setState 误触发整页卸载重挂（R-164 实测）。
- 列表换批时「退场 + 入场同时播」（`mode="popLayout"` 的退场卡绝对定位在原格子上）→ 新卡在旧卡底下淡入，
  看起来就是「结果卡没有动画」（R-199）。**换批必须序列化：退场走完再入场。**
- 动画状态与后端状态各写一套 → 判据永不成立（R-173：等 `done/idle/failed` 三个永不出现的值）。
- 筛选下拉的「全部」选项文案写成字段名（`<SelectItem value="all">广告</SelectItem>`）→ Radix `SelectValue` 只要
  `value` 非空就按正常前景色渲染选中项文字，默认（不筛选）态看起来跟真的筛了「仅广告」一样（R-198）。
  约定：**下拉默认态一律用 `components/ui/filter-value.tsx` 的 `FilterValue`**（默认灰字字段名、选中具体值才高亮并显示值），
  下拉内保留「全部」项用于取消筛选；现用于素材库工具栏（博主/发布状态/有无视频/是否广告）。
- **"动画在屏幕外播完了"→ 用户说"没有动画"（R-199 素材卡 / R-206 讨论留痕）**：只往下长的列表不断追加时，
  新条目的入场动画照样播，但播在可视区之外（R-206 实测：新留痕在可视区下方 3667~3730px，`scrollTop` 恒 0，视口只有 494px）。
  判据不是"有没有动画"，而是"人能不能看见"：要么自动跟随、要么给"有新内容"的可点提示（见 §8.2）。
- **`AnimatePresence initial={false}` 会吃掉"切进来时已经在的那一批"的入场动画（R-206）**：Radix 每次切 tab 都重挂 Content，
  `initial={false}` 让整批子元素直接以 `opacity 1 / transform none` 出现（实测 110 帧 0 帧在动）→ 用户感受就是"这个 tab 没动画"。
  只在"避免首帧闪白/避免整批齐动"的场合才用它，且必须确认这不是用户唯一能看到的动画。
- **`AnimatePresence initial={false}` 会把子组件的 framer "循环关键帧"冻死在第一帧（R-206 真凶）**：
  Presence 把子组件的 `initial` 置为 false，对 `animate={{ opacity: [0.25, 1, 0.25], y: [0, -2, 0] }}` 这种
  **关键帧数组**，framer 只把样式停到第一帧就不再推进——生产包实测 98 帧里 `transform`/`opacity` 各只有 1 种取值、
  `getAnimations()` 为空（草稿页卡片上同一个 `ThinkingDots` 没有这层包裹，是正常的）。**给点补显式 `initial` 也兜不住**（实测）。
  约定：① 别把「在跑」的循环指示器放进 `initial={false}` 的 Presence 里；② 循环指示器优先用 CSS 关键帧（无条件会动）。
- **依赖 `[tab]` 的 effect 拿不到 `TabsContent` 里的 ref（R-206 实测）**：本项目 Radix 的 `TabsContent` 比这一层晚一个 commit
  才把内容挂上，切 tab 那一帧 effect 里 `ref.current` 与 DOM 都还是 `null`（之后再也不会重跑）→ 监听/测量一律用**回调 ref**。

### 8.5 点检方法（自测用）
- **数值探针**：无头浏览器里用 `requestAnimationFrame` 采样目标元素的 `opacity/transform`，检查
  ① 面板/容器首帧不透明（≥0.6，R-175）② 落定为 `1 / none` ③ 时长与令牌一致；顺带记录滚动容器 `scrollTop/scrollHeight` 有无跳变。
  **列表子项另算**：判据是「有淡入帧 + 有位移帧 + 落定」，不是「首帧不透明」（见 §8.3 规则 2 的区别对待）。
- **自己看一遍再交付**：探针全绿 ≠ 人眼看得见（R-206 第一版 21 个动画帧全绿，作者仍说「没有动画」）。
  用「点下去立刻连拍」确认 50~200ms 之间画面确实在变：`frontend_v2/r206-frames.mjs [url] [草稿ID]` 或截图序列。
- **验收要在作者实际使用的入口上做**：作者用的是后端托管的根路径 `/`（`frontend_v2/dist`），
  **改完必须重新 `vite build`**（`scripts/verify.sh` 会重建），否则页面还是旧 bundle——R-206 第二轮作者说「还是一样的没有动画」，
  真凶就是页面加载的入口 js 在新 dist 里已经不存在了；SPA 不会自己重新拉包，需要刷新页面。
- **逐帧截图**：CDP `Page.startScreencast`（`everyNthFrame: 1`）抓切换前后 15 帧，肉眼确认没有空白帧/闪白。
- 交互点检：主页、素材库、脚本工作台（含抽屉 4 个 tab）、AI 设置、博主对标、博主管理、人设、AI 对话逐个切一遍。
- **现成探针**：素材库换批 `frontend_v2/r199-*.mjs`；抽屉讨论 tab（入场帧数 / 状态条是否重挂 / 新留痕是否在可视区 /
  翻历史有没有被抢滚动条）`frontend_v2/r206-discuss-tab-motion.mjs [草稿ID]`（会 mock `debate-status`+`discussions`，不花钱；
  全绿时进程退出码 0）；「状态条三点是否真的在动」`frontend_v2/r206-dots.mjs [url] [草稿ID]`
  （草稿页卡片 + 抽屉讨论 tab 两处都测，输出「不同 transform/opacity 取值数」与 WAAPI 状态；会 mock 一个 running 状态，不花钱）；
  「新建草稿实时保存」`frontend_v2/r212-autosave.mjs`（真实链路：打字→自动落库 / 点遮罩关闭补存 / 重开内容还在 /
  清空后关闭自动删除 / 状态位落定 `1 + none`；会真实建稿并在跑完逻辑删除，全绿退出码 0）；
  「断网兜底」`frontend_v2/r213-offline.mjs`（拦住 `/api/drafts` 写请求模拟后端不可达：断网打字→`offline` + 本地副本 + 停手仍在退避重试 /
  关抽屉不丢 / 刷新后提示条可恢复 / 联网补存成功且副本清掉；同样真实建稿后逻辑删除）；
  **「提词器 + 网页录像」`frontend_v2/r214-prompter.mjs`**（需 8000 + 3000 在跑，跑完逻辑删除自建草稿，全绿退出码 0）：
  纯黑全屏/无导航残留、首行贴屏幕上沿、12 段分段、正文区逐帧零动画、空格播放（滚动推进 + 计时递增 + rAF 帧率）、
  全部快捷键（空格/↑↓/`±`/`[`/`]`/M/R/Esc）、滚到底高亮落最后一段、设置持久化（刷新沿用）、控制条 3s 淡出 + 鼠标唤醒 + `?` 面板、
  摄像头（fake 设备）→ 3s 倒计时 → 录制 → 空格停止 → 回放时长>0 → 下载文件名与格式一致、预览小窗不压正文、
  【存入素材库】打桩断言 multipart 请求 + **Node 直连后端真上传一次**（用完 `DELETE /api/videos/{id}` 清理）、长稿滚动内存无增长、抽屉【提词器】入口直达。
  用法：`cd frontend_v2 && node r214-prompter.mjs`（对生产入口验收加 `ECHO_WEB=http://localhost:8000`，此时需先 `npm run build`）。

### 8.6 非实时结果：进行中必须可见（R-202 起强制）
> 作者：**「所有非实时返回的结果，该有的动画都需要有，保持动画美观流畅，不然容易误导用户」**。
> 这是一条硬性规范，也是 DoD 红线：不满足 = 功能不算完成。

**适用范围**：任何「非实时返回 / 耗时」的功能——后端异步任务（`background_tasks`）与同步慢接口（LLM/网络/批量计算）。

> **边界（R-212）**：编辑区的**实时自动保存**是毫秒级同步快接口，不落 `background_tasks`，因此不要求「切页/刷新恢复进行中」；
> 但**仍必须可见、失败不得静默**：草稿抽屉底部状态位从「保存中…」到「已自动保存 HH:MM / 自动保存失败，点【保存】重试」。
> **R-213**：后端不可达时状态位显示「连不上服务器，已本地暂存（重试 N）」，并**自动退避重试**（不是等作者手动点）——
> 内容此刻已在 localStorage 副本里，刷新/关抽屉都不丢，重开给恢复提示条。

**必须满足**
1. **发起即见进行中动效**：按钮 spinner / 卡片覆盖层 / 进度条 / AI 状态条；不能让用户猜是不是结束了。
2. **切页/刷新可恢复**：离开页面再回来，只要后端仍在跑，页面**必须**仍是进行中动效（依据 `background_tasks` / `sync_jobs` / `draft_status` 等**服务端状态**，而非组件本地 `useState`）。
3. **全局可见**：顶栏常驻「进行中 N」指示器（`ActiveWorkProvider`），任何页面都能确认后台还有任务在跑。
4. **完成/失败干净落定**：动效收口到 `opacity 1 / transform none`，状态切到完成或失败（不残留转圈）。
5. **结果不丢**：转换/耗时任务的结果从服务端取（`task.result`），回来能回填展示，而不是「动画没了、结果也没了」。

**机制（唯一事实源）**
- 后端：`background_tasks`（pending/running/done/failed + progress + note + result）为**唯一事实源**；`GET /api/tasks?status=running,pending` 供回扫；SSE `task.update`（`/api/events`）实时推送。
- 前端 `ActiveWorkProvider`（挂 `AppShell`，跨路由常驻）三段式：
  ① **挂载回扫**（补齐切页/刷新时正在跑的任务）；
  ② **SSE 实时增量**（`task.update` 即改，秒级）；
  ③ **10s 轮询兜底**（SSE 断线不重放事件，且部分任务只在开始/结束推送；**仅在有进行中任务时开启**，空闲停）。
- 页面本地乐观态（点击瞬间）与服务端任务态**合并**，以服务端态为准；任务 `done/failed` 时由页面刷新自身 query。

**禁止**
- 只用组件本地 `useState` 表示「在跑」——一卸载就没了（本规范要修的主症状）。
- 轮询不停/状态卡在中间值（判据必须落在服务端真实终态，见 8.4）。
- 从 `opacity: 0` 起步的进行中/完成动效（会闪空白，见 8.3）。

**点检（必须做）**
- headless：发起 → 切到别的页 → 切回，确认**仍有进行中动效**且顶栏计数正确（中间可刷新一次浏览器）；等任务完成，确认动效落定、结果回填。
- 断言依据是**后端状态**（`/api/tasks`），不是画面截图；画面只验证「可见/流畅/无闪帧」。
