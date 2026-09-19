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
| benchmark.py | /api/benchmark | 博主对标：前2+最新展示（R-152）/转写补齐/AI可讲/洗稿（R-152 增 `rewrite-source`：素材库非主博主素材一键洗稿）；「重新对标」一键重跑（R-102，后台任务） |
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
- `transcription.py`：`Transcriber.transcribe` 按 `asr_mode` 路由：mock 假转写（离线）/ aliyun（`aliyun_filetrans` 泛化调用提交+轮询）/ siliconflow（`siliconflow_asr` 直传，R-108）。
- `aliyun_filetrans.py / aliyun_oss.py`：FileTrans 4.0（CommonRequest）与 OSS 上传/预签名 URL；上传前由 `media_tools`/`media_naming` 用 ffmpeg 抽 16k 单声道 wav。
- `siliconflow_asr.py`（R-108）：`POST {base}/audio/transcriptions` 直传音频转写（multipart file+model，无需 OSS 中转）；视频先抽音轨、纯音频直传；平台限制单文件 ≤50MB / ≤1 小时（`media_tools.probe_duration_seconds` 探测），超限明确报错走失败通知、**不自动切换其它服务商**。
- `pipeline.py`：每日流水线（R-140 起组候选与生成切片统一用 `model_settings.topics_count(db)`，即「AI 设置」的每日篇数）。`generation.py`：生成草稿（R-139 起统一调用 `debate.run_debate`：生成方初稿 + 评审方 N 轮 + 自检收口；不再单模型直出）；上下文 = 人设(tags+维度+红线+禁词) + 风格画像 + 检索到的风格样本（条数可配置 3~8，R-131） + **作者指定的风格范本**（必定注入） + **高表现内容的开场/结尾结构模板** + **作者改写稿 few-shot**（R-131；R-156 起优先用版本链的首版→终版，无版本退回 `original_script→script`） + 金句/最佳实践 + 对标风格卡；`generation_user_message` 抽出供评测复用；生成后**自检**（红线/禁词/口癖覆盖率）不达标自动重写 1 次，结果落 `drafts.quality`；草稿写入 `prompt_version`（R-129）与 `persona_version`（R-130）做归因。`_all_texts`（全量素材加权语料）供优化与每周重建（R-064）。
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
- `debate.py`：**所有脚本生成的唯一路径**（R-139）。`debate_rounds(db)` 取「AI 设置」轮次（Kv `debate_rounds` > `.env` > 5，夹 1–10）；`snapshot(db).generation_pair()` 解析生成方/评审方（可相同）；`_side_llm` 把某一方包成「该槽位主用 + 另一方兜底」；初稿用 `generation_user_message`（与金样本回放同一输入），自检不通过再做一次收口修订；结果写 `draft_discussions` 与 `Draft.quality`（models/used/fallback/rounds/rounds_done/issues/passed/style_coverage）。入口：`run_debate`（通用；R-155 增可选 `source_text/source_title`：传了就按原文改写出 标题/封面字/正文/标签，写回 `original_script` 供原文对照、`merge_tags` 合并去重，随后同样 N 轮+自检）、`run_debate_draft`（工作台后台任务）、`run_rewrite_debate`（对标洗稿，R-118）。原文讨论的入队/解析在 `draft_flow.resolve_discussion_source` / `start_discussion` / `discussion_task`（任务 kind=`draft_discuss`）。
- `llm_router.py`（R-139）：统一模型路由与降级层。`snapshot(db)` 取线程安全的配置快照（普通 dict，无 Session）；`RoutedLLM` 接口与 `OpenAIClient` 兼容（`chat`/`chat_json`/`chat_completion`），主模型「输出不合法」可重试 1 次，随后降级到备用槽位；降级触发=报错/超时/空正文/缺契约字段（`chat_json(require=(...))`）；参数归一化=不支持 temperature 的厂家不传该参数 + `max_tokens` 抬到厂家下限（防推理模型正文被思考吃光）；降级写日志 + 站内通知（`_default_notify`，同功能 30 分钟冷却，自己开短连接所以跨线程安全）；`RoutedLLM.degraded/used_slot/routing()` 供调用方标记。`primary_llm(db, feature)` 是非脚本生成功能的统一入口。
- `llm.py` 的两个关键健壮性设定（R-139）：① `min_max_tokens` 归一化保证推理模型的思考不把正文预算吃光（R-142 实测定标：DeepSeek 8000 / Kimi 10000——同一步骤思考量波动 2418～8023+ tokens，定低了就会「评审总是降级」）；② `_post` 用**流式读取（`iter_bytes`，httpx 负责解压 gzip）+ 墙钟上限**（`ECHO_LLM_TIMEOUT_SECONDS`，默认 600s）；不设 stream 时 `read` 等价于「单次调用总时限」，故与墙钟同值，语义为「单次调用最多 600s」。连接级瞬时错误由 `llm_router` 重试一次（超时不重试）——httpx 的 read timeout 会被长连接的持续字节重置，实测一次调用挂过 39 分钟；HTTP 4xx/5xx、响应结构异常、空正文+有思考分别转成可读的 `LLMError` / `LLMUnusableOutput`。
- `model_settings.py`（R-138）：模型槽位配置（`VENDORS` 厂家目录、`SLOT_KEYS`、`ROLES`、`ASR_MODES`）；`get_model_config` 含旧 `generation_model` 无感迁移；`resolve_slots/generation_roles/asr_config/topics_count` 供运行时读取；全部存 `app_kv` → **保存即生效**（`Transcriber(mode=..., model=...)`、`SiliconFlowASR(model=...)` 也改为接受运行时覆盖）。
- `model_health.py`（R-139）：保存模型设置后异步跑双模型兼容性自检（3 个极简样例 × 2 个槽位，校验文本/JSON 契约），结果写 Kv `model_selfcheck_result`，由 `GET /api/settings/models` 的 `selfcheck` 带回前端并写站内通知。
- `topic_mining.py`：热点源类（mock/公开接口/Bilibili、Douyin、Xiaohongshu/TikHub 热搜实现）；`get_sources` 按 `hot_source_mode` 选择；`fetch_and_store` 入库去重（platform+title+date）。
- `persona.py`：LLM 分析（逐篇提取 `analyze_one` / 全量归纳 `merge_full` / 增量合并 `merge_incremental` / 语义复核 `compare_profiles` / 打标）；提示词只给「方向盘」（角色+观察方向），维度与措辞由 AI 自定，程序只解析固定字段；`_split_phrases` 与 `suggest_phrase_candidates`（金句候选）。
- `persona_profile.py`（R-128）：人设分析管线——`extract_pieces`（逐篇提取，结果按「提示词指纹+文案 hash」缓存于 app_kv，内容不变复用、与全量重算等价）、`full_profile` / `merge_profile`（全量归纳合并：优先把每篇提炼结果原样喂模型做全局归纳，失败或 >120 篇再走「机械近义去重 + 分批归纳」）、`incremental_profile`（当前档案+新篇）、`profile_coverage`（集合覆盖率，支持近义模糊匹配）、`compare_profiles`（覆盖率 + AI 语义复核，均 ≥95% 才通过，否则回退全量）、`current_profile` / `persist_suggestions`（维度→category 映射落库，含 150 条防御上限）。
- `prompt_service.py`：提示词 key→版本管理；`ensure_defaults`、`save_new_version/enable_version/create_candidate`、`reject_candidate`、`get_prompt_version`、`prompt_group`（人设引擎/生产提示词分组，R-130）、`version_effect`（按版本聚合草稿反馈 + 人设版本跨度提示）、`feedback_context`（星级+四维分节分+「AI 原稿→作者改后」diff）、`learning_material`（全量加权前 16 条 + **AI 归纳合并后的人设档案**，R-064/R-128）、`optimize`（R-129：按 key 语料 → 注入契约与上下文说明 → 候选自检失败重试 1 次 → 契约段程序拼接 → 自动排队评测；失败抛 `PromptOptimizeError`）、`maybe_notify_prompt_refresh`（R-131：素材累计阈值只发提醒，不再自动产出候选）、`optimize_rule_keys_task`（手动一键优化规则型 key）。`OPT_SYSTEM` 明确「不得写死作者传记/红线，只给方向盘」，并给出**可改（角色/方法/结构/篇幅/原则）与不可改（事实/红线/输出契约）清单**；候选受 **≤1.5×当前版本** 的长度约束（R-132），并要求模型附「变更说明」写进候选 note。
- `prompt_contract.py`（R-129）：提示词优化契约——`material_for`（按 key 取真实样本，取不到返回空→「样本不足」）、`contract_for`（程序固定的输出契约段）、`context_note_for`（运行时 user 上下文说明，避免优化器重复注入）、`budget_for`（长度预算）、`validate_candidate`（长度/契约字段/写死事实校验）、`assemble_candidate`（可优化段 + 契约段分层拼接）。
- `prompt_eval.py`（R-129 M115）：金样本回放评分——`golden_set`（高表现素材选题 Top5 + 高/低分草稿各 3 条 + 风格标记 + 红线）、`_probes`（按 key 组装回放输入）、`_score_outputs`（格式合法率/红线命中率/像作者率 → 综合分）、`evaluate`（候选 vs 当前版同批金样本对比，落 `prompt_evals`）、`prompt_eval_task`（后台任务 + 通知）。只展示分数，不设启用门槛。
- `style_profile`（core）：口癖/句长/感叹反问占比等画像；R-057 表达风格面板 + 禁词注入。
- `metrics.py`：`_platform_breakdown`（平台最新指标，供生成加权）/`summary`/`radar`（赛道雷达，R-136 自 review 迁入）/`apply_retention`（热点 30 天清理）；R-136 已删除无调用方的 upsert/import/fetch/series。
- `chat_service.py`：只读工具集 + 流式问答；工具：search_videos/get_video_detail/get_persona/list_requirements/get_metrics_summary/get_today_topics/get_review_report/get_radar/search_drafts/generate_draft（写操作需明确同意）。SSE 由 api/chat 组装。
- `benchmark.py`：对标聚合（**R-152：最新15条按互动分取前2 + 第三篇=该对标最新一篇**（重叠按互动分顺延保底3条），R-109：10→15；广告/同款漏标过滤；文案只用 ASR 转写稿）+ `target_units`（R-152 统一的展示/补齐目标选取，`with_text_first` 保留 R-106 展示口径）+ `ensure_top3_with_text`（前2+最新缺文案自动下载转写、无文案顺延；有文案后严格 AI 审核软广/商单/引流并落库排除，R-103/R-106）+ `resolve_rewrite_source`（R-152：素材库按 video_id/post_id/work_id 解析 ASR 文案与来源，供 `/rewrite-source` 洗稿）+ `rerun_benchmarks(db, owner, update, refetch)`（R-102/R-109：refetch=True 手动重捞最新15条；refetch=False 每日同步后自动触发、不重复拉取，只重算前2+最新/补缺转写）；/top 有文案优先（空文案被下一条顶上，R-106）。
- `platform_sync.py`：见 §4。
- `works_service.py`：标题规范化（去话题/标点/空白/小写）+ 自动合并 + 手动合并/拆分 + `list_works`（合并作品含各平台）+ `post_item`（作品序列化）。
- `creator_service.py`：当前博主/切换/账号元数据/全网粉丝汇总/删除保护。
- `platform_assets.py`：封面/头像下载本地、HEIC 兼容、占位 SVG（mock 无封面时）。
- `notify.py`：QQ SMTP 每日推送 digest/失败告警（HTML）。
- `requirements_service.py`：以 `requirements/` 文件为事实源读写（列表/详情/新建/状态机）。
- `media_naming.py / media_tools.py`：R-058「标题-视频/封面」命名、抽音轨工具。
- `diff_analysis.py / feedback.py`：改稿差异分析、反馈回流。R-156：`analyze_diff` 接收**版本链**（初稿→…→定稿）看逐版修改；`apply_diff_suggestions` 版本链优先（无版本退回 `original_script→script`）；`diff_task` 为后台任务体。
- `draft_versions.py`（R-156/R-157）：定稿快照 `snapshot_version`（支持 `content` 覆盖，用于「洗稿前 ASR」这类非当时状态的快照）、
  `finalize_version`（留一版 + ≥2 版才触发差异分析）、`list_versions`、`chains_for_drafts`/`version_stages`（≥2 版用版本链，否则退回原文→当前稿）。
  自动留版：洗稿 `run_rewrite_debate`（前=素材 ASR、后=洗稿稿）、讨论 `draft_flow.discussion_task`（无版本先留「讨论前」再留「讨论后」）、
  AI 生成 `generation.generate_draft` 与 `draft_flow.debate_task`（`snapshot=False` 用于金样本自测 / 回炉中间稿，回炉结果记到原稿）。
  回滚 = 把版本快照覆盖回草稿并保存（不额外留痕、不改状态）。

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
- **限速与重试（R-151）**：TikHub 限「单路由 1 请求/秒」（429 原文实测），而 daily 同步是多账号并行 + 逐条素材再打评论接口，必然超限；被限流时服务端有时回 429、有时**直接掐断 TLS 隧道**（本机 httpx 默认读 macOS 系统代理 `127.0.0.1:7890`，故报 `[SSL: UNEXPECTED_EOF_WHILE_READING]`）。`TikHubClient._get()` 因此：
  - `_throttle_route(path)`：进程内按 **API path** 排队（最小间隔 `_ROUTE_MIN_INTERVAL=1.2s`，`threading.Lock` 预留时间片、锁外 sleep），不同路由互不阻塞；
  - 有界重试 4 次尝试、退避 `1.5s → 4.0s → 8.0s`，仅对 `httpx.TransportError`（SSL EOF/连接重置/超时）与 HTTP `429/500/502/503/504` 生效；**4xx 永久错误立即抛**；
  - 重试 `warning` / 最终失败 `error` 写日志（R-133 logger），错误消息保持 `TikHub 请求失败:` 前缀并追加「（已重试 N 次）」。

### 幂等与去重
- 作品：`(platform, platform_post_id)` 唯一约束 + `_ensure_post` 先查后建/更新（含 title/cover/publish_time/raw/tags/cover_path）。
- 指标：`(post_id, stat_date)` 唯一 upsert（当天多次同步覆盖成最新，历史保留）。
- 评论：`_upsert_comments` 按 post_id+text 去重、点赞保留更高值、**按点赞降序取 Top50**（R-067）。
- 进度：`sync_jobs.progress_done/progress_total/progress_note`，`_job_progress` 用 SQL 原子累加（R-070）；`GET /api/platform/jobs` 输出进度供前端轮询（R-161：可选 `status` 过滤，前端只拉 `status=running`，避免历史 job 挤占运行中进度）。

### 编排（run_sync）
- 入口：手动（博主页 全量/前15条/对标单账号「同步」/单账号/当前主博主「同步所有博主前15条」）、定时（06:00/17:00 两轮 `run_daily_sync_all`：主博主+全部对标统一 daily 带视频下载转写，R-109）、单条（posts/videos/works 同步）。
- R-162（替换 R-160）：`enqueue_all_top15_sync(owner)` 为「当前主博主 + 全部对标」各写一条 `platform_sync` 队列任务（pending）并**预置一条 running 的 SyncJob**（progress_note=「排队中…」，前端所有卡片立即显示动画）；已在排队/执行的博主与无启用账号者跳过。`all_top15_worker` → `run_all_top15_sync(owner, entries)` **一个消费者逐个消费**，每个复用预置 job 调 `run_sync(scope=daily, creator_id=…, with_media=True, job=…)`（`run_sync` 新增 `job` 参数，缺省行为不变）；单个失败不阻断其余，`BudgetExceeded` 停止；完成后 `maybe_start_benchmark_rerun(refetch=False)`。接口 `POST /api/platform/sync-all`（无主博主/无可同步博主 400，同批任务在跑 409）。
- `scope=daily`：每平台 top15（R-085/R-086 最终 15）；`weekly`：对标每账号 top3；`initial`：`count<=0 → _real_posts_all` 翻页全量。daily 且 with_media=True 时同步后对前 N 条跑媒体补齐（下载视频+自动转写）。
- 并发：`ThreadPoolExecutor(max_workers=3)` 每账号独立 SQLAlchemy session（account 级隔离，单平台失败不拖垮其它）。
- 结束：`auto_merge_creator` 合并同标题跨平台帖 → `works`；写 SyncJob stats/message + 账号 sync_status；通知中心收到完成。
- 本地素材卡片同步 `sync_local_video_metrics`：遍历 `_bound_platform_posts`（local_video_id + work_id + platform_post_id 三路去重）拉各平台指标 + 评论 Top50，并写 `metrics_snapshots`（当天多平台聚合）；单平台失败不中断，全部失败才报错。
- 云端合并卡同步 `sync_work_posts`（R-067 新增）：遍历 work 下全部平台帖（原只同步 cloudPosts[0]）。

### 卡片同步按钮状态（前端 R-069）
同步中状态按卡片唯一 `key`（`v<id>` 本地 / `w<id>` 合并 / `p<id>` 单条）判断，避免 work_id 与 post id 数字撞车误高亮。

## 5. 定时与后台（scheduler.py / tasks.py）
- 计划见 ARCHITECTURE §4。`_platform_sync_job` 通过 `start_task` 跑 `run_sync(scope=daily)`。
- R-109：取消原独立 06:00 自动「重新对标」定时（R-105）；每日两轮同步完成后由 `run_daily_sync_all` 自动触发一次「重新对标」（`maybe_start_benchmark_rerun(refetch=False)`，已有 rerun 在跑则跳过），对标页手动「重新对标」仍 refetch=True 重捞最新 15 条。
- `tasks.py`：`background_tasks` 表 + daemon 线程；progress 0→10→100；完成写 Notification；`import_video` 完成后若语料已≥阈值（每 3 条新素材）自动产出提示词候选并通知（R-022/R-064）。
- `watcher.py`：10s 轮询 inbox，移入 videos 目录并建 `Video` 行（文件名 uuid 前缀防重），**不自动转写**（R-033，手动按钮触发）。

## 6. 前端结构（frontend/src/）
- `router.js`：/home /videos /drafts /chat /persona /prompts /benchmark /creators /login（hash）。
- `api.js`：统一 fetch + `X-Access-Token`；401 自动跳登录。
- `views/`：HomeView（时间线+热点灵感）、VideosView（素材库：卡片/编辑弹窗/转本地/评论 tab/合并；R-152/R-153 非主博主素材**编辑页**「洗稿」，卡片列表不放入口）、DraftsView（**R-158：三 tab（草稿/待制作/废稿），废稿可恢复；「删除」二次确认后逻辑删除且任何 tab 不可见（部分回退 R-152 的隐藏）；R-159：加 `done` 状态与「完成」tab，待制作可【完成】/【退回草稿】，完成可【退回待制作】**+打分；R-154：新建草稿本地空白稿、内容全空不落库，弹窗叉掉/取消/保存后统一 `load()` 刷新；R-155：讨论 tab 无留痕显示【讨论】、有留痕底部【重新讨论】，跑 `draft_discuss` 后台任务，完成后把标题/封面字/正文/标签/原文案刷回弹窗并 `load()`；R-156：【定稿】按钮 + 【版本】tab（版本列表），版本链反哺改稿差异分析与生成 few-shot；R-157：【版本】每条可【回滚到此版本】【查看】（回滚=覆盖保存），原【原文对照】改为【正文对比】（左右各一个版本下拉框选任意两版对比））、ChatView（SSE 流式）、PersonaView、PromptsView、BenchmarkView、CreatorsView（博主/账号/作品/同步+进度条；R-162 当前主博主按钮改「同步所有博主前15条」并调 `/api/platform/sync-all`，队列预置所有博主的 running job 使卡片同时显示动画；R-161 syncing 状态按 id 用 reactive Set 记录，修多账号连点动画丢失）、LoginView。
- `components/`：MaterialCard/CloudPostTile/PlatformStats/MediaComments/…/SyncProgressBar（R-070，1s 轮询 jobs）；
  **`RewriteDiffModal.vue`（R-152）**：博主对标页与素材库共用的「原文/洗稿」左右对照弹窗（`buildDiff`）；
  **`ScriptEditor.vue`（R-150，Tiptap v3 块编辑器）**：`v-model` 绑 **Markdown 字符串**（对外与旧 textarea 等价，
  `drafts.script` 契约不变）；扩展 = StarterKit + Image + Placeholder + TableKit + TaskList/TaskItem + `@tiptap/markdown`；
  `onUpdate → editor.getMarkdown()` 回写，外部换稿走 `setContent({ contentType: 'markdown', emitUpdate: false })`；
  插图（工具栏/粘贴/拖拽）复用 `uploadImage()`；DraftsView 用 `defineAsyncComponent` 懒加载（ProseMirror 不进首屏）。
- `composables/media.js`：fetchVideos/fetchWorks 统一入口；`composables/rewrite.js`（R-152）：素材库「洗稿」发起 `POST /api/benchmark/rewrite-source` + 轮询任务，状态模块级跨页保留。
- `lib/`：format.js（平台名/数字缩写）、options.js（平台/赛道/状态选项）、timeline.js。
- dev：vite 5173 代理后端 8000（`vite.config`）；构建产物 dist 由后端托管。

## 7. 常见改动指南
- 加接口：api/xxx.py + schemas + services；记得跑 verify；涉及注释/文档同步。
- 加表/列：models/*.py + db.py 幂等迁移函数（init_db 注册）；改完生成 DATABASE.md。
- 改平台字段：先看 platform_sync 与 tikhub `_real_*` 解析函数。
- 改生成上下文：generation.py + prompt_service + ai_prompts 页面（版本化，不要写死进系统提示词之外的代码）。
