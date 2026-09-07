# 变更记录

## [M98 / R-115] 2026-09-07 — AI 分析 JSON 解析健壮化
- _parse_json 支持代码围栏/推理前后缀，并扫描第一个合法 JSON 对象；content 为空时回退 reasoning_content。


## [M97 / R-114] 2026-09-07 — 对标页「AI分析」结果切页保留
- AI分析结果落 app_kv（ba:{owner}:{key}）；/top、/prepare 返回 analysis，前端 load 回填，切页不丢。


## [M96 / R-113] 2026-09-07 — 转写来源与模型入库（per-transcript）
- transcripts 增加 asr_provider / asr_model 并在转写时落库；迁移回填历史（09-07 前 aliyun 且模型为空；之后 siliconflow 模型 Qwen/Qwen3-ASR-1.7B）。
- 编辑页「语音转文字」按每条素材实际来源与模型显示；阿里云模型未知显示为空。
- 修复 test_parse_link 网络依赖，离线确定性通过。


## [M95 / R-112] 2026-09-07 — 三处线上修复
- 素材库云端卡合并本地素材的 is_ad/ad_price：已标记广告的转本地素材在卡片上正确显示「广告」。
- 通知面板改为 pointerdown 判定外部关闭（选文字不误关），每条通知新增「复制」按钮。
- 新增 GET /api/settings/asr；编辑页「语音转文字」按当前 ASR 模式显示真实来源（硅基流动/阿里云/模拟）。


## [M94 / R-111] 2026-09-07 — 账号主页链接 + 素材卡平台标签跳转
- 博主管理每个账号行新增「主页 ↗」（优先 home_link，缺省按平台+ID 构造主页地址，新标签页打开）。
- 云端作品序列化新增 page_url（复用 build_platform_page_url）；素材库卡片平台名在可跳转时渲染为链接，点击打开对应平台作品页（不触发展开卡片）。


## [M93 / R-110] 2026-09-07 — 博主页同步按钮防重复入队
- CreatorsView 同步按钮在对应博主已有 running 任务时进入 loading/disabled（runningCreators 派生自 activeJobs），杜绝同步进行中重复点击再次入队；触发成功后先 pollJobs 再释放点击锁，缩小竞态窗口。


## [R-108 补充2] 2026-09-07 — 默认模型切回 Qwen/Qwen3-ASR-1.7B（官方定价页标注免费）
- 官方定价页确认 Qwen/Qwen3-ASR-1.7B 当前免费（¥0/分钟，实测可用无 402）；默认模型由 SenseVoiceSmall 切回 Qwen3-ASR-1.7B（config/.env/.env.example）。
- SenseVoice 事件标记清理保留（对 Qwen3 输出无影响）。

## [R-108 补充] 2026-09-07 — 硅基流动 ASR 换免费模型 SenseVoiceSmall
- 默认模型 `Qwen/Qwen3-ASR-1.7B` → `FunAudioLLM/SenseVoiceSmall`（硅基流动免费，实测真实出稿，不再受余额限制）；`.env`/`.env.example`/config 默认同步。
- 顺带清理 SenseVoice 输出的事件标记（🎼、情绪表情、`<|...|>` 标签），转写稿更干净。

## [M92 / R-109] 2026-09-07 — 对标博主统一每日同步（06:00/17:00，15 条+下载转写）
- 每日平台同步改 06:00/17:00（`ECHO_PLATFORM_SYNC_TIMES` 默认值 + .env），`run_daily_sync_all` 编排：主博主 + 全部对标博主统一同步，每账号最新 15 条 + 下载视频 + 自动转写。
- 取消原独立 06:00 自动「重新对标」定时（R-105）；每轮同步完成后自动触发一次「重新对标」（`refetch=False` 不重复拉取 TikHub，只重算 Top3/补缺转写）；对标页手动「重新对标」保留并改为重捞最新 15 条（10→15，含 /top 与 prepare 候选）。
- 前端：对标账号按钮「每周同步」→「同步」且手动同步改 daily 口径；删除无用 freqOptions「每周（对标）」；新建对标账号 sync_frequency 统一 daily；mock 对标识别改按 creator.kind（兼容历史 weekly）。
- 测试：新增 run_daily_sync_all 编排/无主博主、rerun refetch 语义用例；门禁全绿。

## [M91 / R-108] 2026-09-07 — ASR 接入硅基流动（.env 切换阿里云/硅基流动）
- config：`ECHO_ASR_MODE` 合法值扩为 `mock|aliyun|siliconflow`（R-068 白名单护栏不变）；新增 `ECHO_SILICONFLOW_API_KEY/BASE_URL/ASR_MODEL`（默认 `Qwen/Qwen3-ASR-1.7B`）。
- 新增 `services/siliconflow_asr.py`：`POST {base}/audio/transcriptions` 直传音频转写（multipart file+model，无需 OSS 中转）；视频先抽 16k 单声道 wav（复用 media_tools），纯音频直传；平台限制单文件 ≤50MB / ≤1 小时（新增 `media_tools.probe_duration_seconds` 探测），超限明确报错并走现有失败通知、不自动切换其它服务商。
- `transcription.py` 路由增加 siliconflow；所有转写入口（手动/每日同步/对标补齐，均经 `import_video_task`）随 `.env` 切换生效（改后重启）。
- Key 只写本地 `.env`（gitignored），`.env.example` 只加占位模板。
- 测试：新增 `test_siliconflow_asr.py` 8 项（配置缺失/直传/抽轨清理/空结果/HTTP/网络错误/超限/时长超限/路由），门禁全绿（97 项）。

## [M90 / R-107] 2026-09-06 — 素材库不显示禁用账号数据
- /api/videos 排除绑定到禁用账号作品的本地素材（platform_post_id 或 post.local_video_id 命中）；启用账号与未绑定素材不受影响。

## [M89 / R-106] 2026-09-06 — 对标页修复（软广排除 + 空文案顶替）
- /top：有文案优先占位，无文案/空转写按分补位，重跑后空项被下一条顶上。
- 对标广告判断改独立严格审核（软广/商单/卖课/引流/推自家小程序等），命中落库排除并顺延；绑定已标广告本地视频的帖也视为广告。

## [M88 / R-105] 2026-09-06 — 定时每天06:00自动「重新对标」
- scheduler 注册每日 06:00 任务（每日生成 07:00 前 1 小时，固定时间）：无主博主/无对标/已有重新对标任务在跑则静默跳过，否则后台执行（不阻塞调度）。
- worker 收敛为 services.benchmark.rerun_worker，路由与定时共用；新增守卫单测。

## [M87 / R-104] 2026-09-06 — 「再次对标」改「重新对标」
- 仅展示文案：按钮与提示、通知标题统一改为「重新对标」；逻辑不变。

## [M86 / R-103] 2026-09-06 — 再次对标修复（进度恢复 + 广告不进对标）
- 切页回来自动恢复「再次对标」进度条与轮询（R-088 同款）；卸载停止旧轮询。
- 对标账号广告：转写补齐/再次对标拿到文案后用 AI 自动识别商单/广告并落库标记，Top3 顺延排除；LLM 不可用不误杀。

## [M85 / R-102] 2026-09-06 — 博主对标「再次对标」一键重跑
- 对标页顶部加「再次对标」按钮：后台任务逐个重跑当前主博主下所有对标——重捞各对标最新 10 条（跳过已禁用账号）→ 自动补 Top3 缺文案转写（无文案顺延）→ 完成后自动刷新 Top3；带进度提示与完成/失败通知（/benchmark）。
- 后端：POST /api/benchmark/rerun（task_id）+ services.benchmark.rerun_benchmarks + tasks 增加 benchmark_rerun 类型。
- 测试：rerun 汇总/空对标报错/单对标失败不阻断（mock 离线）。
## [M5] 2026-09-01 — 人设学习闭环 + 改稿差异分析 + 反馈 + AI 对话全工具 + 打磨
- 人设增量建议：新视频（非广告）导入后自动建议扩充（suggested，待作者确认）；广告视频全程隔离
- 改稿差异分析：工作台保存改写后异步分析"作者把 AI 稿改成了什么"→ 人设建议（含依据）
- 反馈闭环：草稿 👍 采用/👎 不用 → 标记 status=used；近期好评选题进入生成上下文（M5 起）
- AI 对话增强：新增指标汇总/今日选题/复盘报告/赛道雷达/搜草稿/生成草稿（写操作需作者明确同意）工具
- 前端打磨：草稿深链接（每日选题直达工作台）、反馈按钮、选题链接修复
- 测试：新增改稿差异判断（共 17 项离线可跑）

## [M4] 2026-09-01 — 指标自动归档 + 复盘 ABCD + 赛道雷达 + 备份
- MetricsSnapshot/ReviewReport 模型；(video_id, date) 幂等 upsert
- 指标三通道：手动录入 / 批量导入 / cookie 抓取（best-effort，mock 不造假数据）
- 复盘服务：A 报表（按视频/赛道/平台）+ B 归因 + C 建议 + D 赛道方向（DeepSeek 优先，启发式兜底）；赛道雷达按互动率排序
- 数据保留：热点快照 30 天自动清理；指标全留
- 备份：scripts/backup.sh（SQLite 官方热备份 + docs/requirements 快照，保留 10 份）；每日 02:30 自动备份
- 定时任务：每日指标+留存（推送时间后 1 小时）
- API：/api/metrics（录入/导入/抓取/汇总/序列）+ /api/review（生成/报告/雷达）
- 前端看板升级：指标录入/批量导入/赛道雷达/复盘 ABCD/明细表
- 测试：新增指标规范化/互动率/留存/复盘启发式 4 项（共 16 项离线可跑）

## [M3] 2026-09-01 — 每日热点挖掘 + 自动生成 + QQ 邮件推送 + 手动触发
- 热点挖掘适配器：mock（开发/测试）+ 抖音/B站/小红书真实抓取（降级设计，单平台失败不影响整体）
- 热点入库去重（平台+标题+日期）；HotTopic/TopicCandidate/PipelineRun 模型
- 匹配打分：DeepSeek 优先，无密钥关键词兜底（纯逻辑可测）
- 生成服务：DeepSeek 三件套（标题/封面字/脚本）+ 平台外壳；风格样本本地 TF-IDF（字符二元组中文分词）；无密钥 mock 稿
- 每日流水线：抓热点→匹配→生成≥3→入库→QQ 邮件（HTML+工作台链接）；幂等（当天成功不重跑）；失败发告警邮件
- 定时任务：APScheduler 按 ECHO_DAILY_PUSH_TIME 注册；Web 手动触发 POST /api/pipeline/run
- 前端新增"每日选题"页：运行流水线/刷新热点/查看候选与草稿链接
- 测试：新增 TF-IDF/关键词匹配/邮件 HTML/幂等 4 项纯逻辑测试（共 12 项离线可跑）

## [M2] 2026-09-01 — Web 界面（Vue3 SPA）+ 脚本工作台 + 需求管理 + 时间线 + AI 对话
- 前端 Vue3 + Vite SPA（响应式，手机浏览器可用）：素材库/时间线/脚本工作台/AI 对话/人设档案/需求管理/看板
- 访问令牌登录页 + 路由守卫 + API 封装（X-Access-Token）
- 后端新增：Draft（脚本草稿，AI 原稿留底供改稿差异分析）、ChatMessage（对话历史）模型
- 草稿 API：创建/列表/编辑保存（工作台改写）
- 需求管理 API：读改写 requirements/ 文件（事实源），状态机变更、Web 新建归档 R-xxx
- AI 对话 API：DeepSeek 函数调用，只读工具（搜素材/查详情/查人设/查需求），写操作不执行（权限边界）
- FastAPI 托管前端构建产物（dist 存在时挂载）
- 测试：新增需求文件解析/编号 2 项纯逻辑测试（共 8 项离线可跑）

## [M1] 2026-09-01 — 内容库 + 转写 + 人设初始化（后端）
- 后端 FastAPI 骨架：config（.env 前缀 ECHO_）/ db（SQLite + SQLAlchemy）/ models / schemas / api / services
- 视频导入双通道：`POST /api/videos/upload`（Web 上传）+ `data/inbox/` 文件夹自动监听
- ASR 适配器：`asr_mode=mock`（开发/测试，确定性假转写）与 `aliyun`（FileTrans REST + HMAC 签名，需 NAS 联调）
- 转写 AI 校对：`correct_transcript`（结合原始文案修正行业词，无密钥安全降级）
- AI 预打标签：`PersonaService.suggest_video_tags`（主赛道/是否广告/自定义标签），`tags_confirmed` 待作者确认
- 人设初始化：`persona_init_task`（全量历史转写稿 → tags + redlines，新版本，待作者确认）
- 后台任务：DB 任务表 + 线程池（`start_task`），`/api/tasks` 查询状态
- 健康检查 `/health` + 访问令牌中间件 + CORS
- 脚本 `scripts/transcribe_all.py`：批量登记历史视频并触发转写
- 测试：`tests/test_core.py`（纯逻辑，离线可跑）+ `tests/test_services.py`（mock 外部依赖）

## [M0] 2026-09-01 — 项目脚手架 + 自描述体系 + 需求归档
- AGENTS.md / docs（PRD、ARCHITECTURE、WORKFLOW、DECISIONS、milestones）/ requirements（R-001~R-014）
- scripts/verify.sh 质量门禁；Dockerfile / docker-compose / .env.example / README / update.sh

## [M6] 2026-09-03 — 体验升级：视觉重构 + 素材库多选/封面 + AI 对话会话化 + Markdown 写作（R-015~R-018）
- R-015 全站视觉重构：Naive UI（按需自动导入）+ 纸感文艺设计系统；主页=时间线+热点选题；ECHO 置于菜单栏左上；移动端底部菜单；精简页面说明文案
- R-016 素材库：封面上传/移除（data/covers + /covers 静态）；platform/main_topic 单值 → platforms/main_topics 多选（JSON，轻量迁移回填并删旧列，statistics/review/chat/ingest 全链路适配）；编辑全量回显 + 增量保存（不误伤字段）；转写稿/校对稿可改（ASR 原始只读，导入任务兼容半成品稿）
- R-017 AI 对话 ChatGPT 化：会话 CRUD + 存量消息归默认会话 + 会话内历史；SSE 流式接口（打字机式下发）；Markdown 渲染 + 复制；AI 服务失败统一降级为可读文案
- R-018 Markdown 写作：工作台工具栏（加粗/斜体/H2/引用/列表/分隔线/链接）+ 插图上传（data/uploads + /uploads 静态）+ 预览；chat/草稿共用 markdown-it
- 门禁修复：锁定 ruff 规则集 E4/E7/E9/F（ruff 新版默认集漂移导致 HEAD 亦报错）；mypy/pytest 修复

## [M7] 2026-09-03 — 通知中心（R-019）
- 右上角铃铛通知栏：异步长任务（素材转写/人设初始化/每日流水线/改稿差异/AI 文案生成）完成或失败自动提醒；红点未读数 + 下拉列表 + 新完成 toast
- 点击通知跳转对应界面并标记已读；支持全部已读 / 清空；通知入库保留最近 50 条
- AI 热点生成草稿改为后台异步（POST /api/drafts/generate-async），完成后通知直达草稿，页面不再阻塞

## [M8] 2026-09-03 — 全量风格学习（R-020）
- 新增"作者风格画像"统计（core/style_profile.py）：口头禅/常用短句/句长/反问·感叹占比/标志性语气词，由库内全部非广告素材实时生成并注入生成 prompt
- 风格样本检索升级：去重 + 表现加权（播放/赞藏评）+ 时间衰减（近的优先），top-k 原文更"像作者且值得模仿"
- 草稿卡 1-5 星打分（R-020 验收入口），打分进入反馈/选题学习
- 广告素材全程隔离，不进入风格画像与样本学习

## [M9] 2026-09-03 — AI 提示词版本管理（R-021）
- 新增"AI 提示词"菜单（tab 页）：生成/人设初始化/视频预打标/人设增量/复盘/改稿差异/AI 对话/转写校对 8 类
- 查看与编辑当前启用版；手动编辑保存=另存新版本并启用（旧版归档）
- AI 自动优化：基于当前启用版 + 最新素材产出候选新版（不直接启用），页面提示待启用，可一键启用；历史版本可预览与回滚启用
- 上传新视频（import_video 完成）后自动为"生成脚本"提示词产出候选并右上角通知
- 提示词默认值仍保留代码常量作为首次 seed/兜底

## [M10] 2026-09-03 — 生成质量护栏（R-022）
- 自动优化节流：每累计 3 条新素材才产 1 个候选（防过拟合单条）；失败下次再试
- 候选启用前 diff：候选卡片展示与当前启用版的逐行增删（前端行级 diff）
- 高低分反馈回流：1-2 分与 4-5 分/采用稿进入 AI 优化上下文；高分成稿作为黄金样本以更高权重参与风格样本召回
- 金样本自测：启用新版"生成脚本"提示词后，用作者认可稿的选题自动生成一轮并右上角通知去打分（先提示，暂不强制）
- 设计声明（D-023）：AI=学习引擎，提示词=方向盘；版本永不自动启用

## [M10 补充] 2026-09-03 — 人设档案可编辑/删除（R-002 增强）
- 已确认人设标签支持编辑（标签/描述/类别）与删除（弹框 + 二次确认）
- 修复手动添加人设标签 500（schema 默认 source 与 kwargs 重复）

## [M11] 2026-09-04 — 双模型讨论生成（R-023）
- 接入 Kimi（Moonshot，OpenAI 兼容）：ECHO_KIMI_API_KEY/BASE_URL/MODEL 可配任意模型；DeepSeek 模型名同样 env 可配
- 生成流程升级：初稿（生成方）→ 评审方按人设/素材挑刺 → 生成方修订，共 5 轮 → 定稿
- 讨论逐条入库 draft_discussions 留痕；草稿弹框新增「讨论」tab，聊天式查看每轮初稿/评审/修订
- 生成模型策略可切换：固定 DeepSeek / 固定 Kimi / 随机 / 轮流（页面选择器 + ECHO_GENERATION_MODEL）
- 任一方失败自动降级单模型并完成；未配 Kimi 时自动用 DeepSeek

## [M12] 2026-09-04 — 脚本工作流三 tab + 素材关联 + 热点扩充（R-024/R-025）
- 脚本工作台分 草稿/待制作(采用)/废稿(不采用) 三 tab；不采用移入废稿、采用进待制作、废稿可恢复为草稿；1-5 星打分保留
- 素材双向关联：草稿弹框可选关联视频；素材编辑弹框显示该视频已关联脚本并可点击跳转
- 热点：mock 池 4 → 28 条（三平台、多赛道）；主页支持平台筛选 + 换一批 + 单次展示 15 条

## [M13] 2026-09-05 — 规划：平台数据/博主管理/选题池/写稿增强（R-027~R-030，未动业务代码）
- 需求登记并澄清定稿：TikHub 数据源、多主博主+对标、选题池三路（热点/主评论/对标评论）、8 项写稿体验增强（requirements/R-027~R-030，状态已确认）
- PRD 更新：§3.1/§3.3/§3.4/§3.5/§3.6 + 新增 §3.10（博主与对标）/§3.11（平台数据同步）/§3.12（写稿增强）；§4 数据流与 §5 选型表、§6 数据模型、§7 验收同步
- DECISIONS 新增 D-026~D-030；里程碑新增 M13 任务拆分
- 待作者确认实施计划后开工；首个动作 = 备份并清库（仅数据库，保留本地文件）

## [M13 一期] 2026-09-05 — 平台数据/博主管理主体（R-027/R-028/R-029 核心，mock 模式）
- 清库（仅数据库，备份 backups/20260905_112605；本地视频/封面保留）→ 空库由作者手动创建首个主博主
- 数据模型（R-027/R-029）：creators / creator_accounts / creator_account_snapshots / platform_posts / platform_post_stats / sync_jobs；videos 增 creator_id/platform_post_id；drafts/persona_tags 增 creator_id；选题灵感 topic_ideas
- TikHub 适配器（mock 确定性数据优先，real REST 骨架含余额/主页/作品/单条/评论）；视频不下载、封面本地（mock 生成占位 SVG、real 下载）；每日请求预算默认 2000 可配（Kv 覆盖），超限自动停并通知
- 同步能力：首次全量（主 50/对标 20）、每日 07:30/18:00 两轮 top10、单条"同步数据"、素材发布链接绑定、云端作品→本地素材（转素材）
- 博主管理：多主博主 + 对标 + 账号配置（主页链接自动解析 ID/增强字段 JSON/频率开关）+ 切换整套随动（确认弹框）；persona/draft/video/生成学习按当前主博主隔离（D-028）
- 选题池（R-028）：每日同步采集主/对标评论区 → 评论灵感池（人工挑选生成，不自动推送）；主页新增来源标签（平台/对标）时间线展示云端作品
- 前端：新增"博主"页（CRUD/切换/账号/同步/云端作品/预算/我 vs 对标汇总）；素材库发布链接 + 同步数据按钮；时间线来源标签；主页评论灵感池
- 质量门禁 verify.sh 通过；后端 32 项 pytest 全绿（新增 6 项平台测试）
- 未完成（下期）：R-030 写稿体验 8 项、复盘页正式"我 vs 对标"对比卡、real TikHub 实机联调

## [M13 R-030 一期] 2026-09-05 — 写稿体验增强（①②③⑤⑦ + 复盘对比卡）
- 选题→角度→草稿：POST /api/drafts/angles（LLM 3 角度，无密钥启发式兜底）；主页热点/评论灵感先选角度再生成
- 分节反馈：feedback 增 hook/pace/ending/style_score 四维；脚本工作台卡片可点选"好/中/差"后统一"记反馈"
- 像我金句库：/api/persona/phrases/suggest 从高表现素材抽短句 → 人设页一键收为锚点（category=phrase）→ 生成强注入（短句语气）
- 对标风格参考：主博主下的对标备注注入生成上下文（仅参考，不污染主博主语料）
- 生成前体检 + 一键回炉：/api/drafts/{id}/check（红线/钩子/结尾/篇幅）与 /rework（异步重写并替换回原草稿）
- 复盘"我 vs 对标"对比卡：数据看板（复盘页）顶部展示主/对标粉丝/作品/中位播放（/api/platform/creator-summary）
- .env / .env.example 补 ECHO_TIKHUB_API_KEY/BASE_URL/MODE/DAILY_BUDGET/PLATFORM_SYNC_TIMES（作者 key 已写入 .env，模式默认 mock）

## [M13 二期] 2026-09-05 — 跨平台作品合并 + R-030 ④⑥ 收尾
- R-031 作品合并：works 表 + platform_posts/videos.work_id；同步后同创作者同标题自动合并；素材库「云端作品」面板（自动合并展示各平台播放/赞/藏/评 + 手动合并/拆分 + 分平台同步）；转素材自动继承 work
- R-030④：生成时注入"近期表现最好草稿的共性（标题/开头/结尾引导）"
- R-030⑥：话题缺口 /api/topics/gaps（近 28 天发布话题覆盖 + 评论区在问数），主页展示补位建议

## [M14 / R-032] 2026-09-05 — 阿里云 ASR 真实接入
- FileTrans 4.0 改用官方推荐 `aliyun-python-sdk-core` CommonRequest RPC POP（SubmitTask/GetTaskResult），替换原占位手写 HMAC REST 客户端；真实调用通过（官方示例音频返回「北京的天气。」）
- 新增 `services/aliyun_oss.py`：视频临时上传 OSS（bucket `981126981126` / oss-cn-shanghai）→ 预签名 URL → 识别完成后删除临时对象
- config 新增 `ECHO_ALIYUN_OSS_BUCKET/REGION`、`ECHO_ALIYUN_ASR_REGION`、轮询间隔/超时；`.env` 配 `ECHO_ASR_MODE=aliyun` 启用真实转写（开发/测试默认 mock）
- 测试：新增 5 项 R-032 编排单测（当前共 43 项通过）；ruff/mypy/前端构建全绿
- 阻塞：该 AccessKey 对 OSS bucket 无权限（`AccessDenied: The bucket you access does not belong to you`），待作者授权后完成 E2E 冒烟
- **完成（同日）**：作者授予 OSS 权限后 E2E 实调通过（上传→转写回填「北京的天气。」→ 自动删除临时对象，复查无残留）；R-032 标记 ✅ 已完成

## [M15 / R-033] 2026-09-05 — 抽音轨 + 手动触发转写（编辑页按钮）
- 上传前用 ffmpeg（imageio-ffmpeg）把视频抽成 16k 单声道 wav 再传 OSS（纯音频直接传）；识别完删除 OSS 临时对象与本地临时 wav（上传体积 MB 级、规避 .mov 兼容风险）
- 上传 / inbox 监听只入库，不再自动转写；新增 `POST /api/videos/{id}/transcribe` 手动触发（已转写会拒绝重复）
- 素材编辑弹窗新增「语音转文字」按钮：点击启动后台任务并轮询，完成后自动展示只读转写稿，右上角通知可跳转
- 修复存量 bug：`tasks.py::_maybe_optimize_prompt` 导入路径错误导致转写成功后任务被误标「失败」并弹失败通知
- 测试：45 项通过；真实链路冒烟：3 秒 mp4 → 抽音轨 → 阿里云返回「北京的天气。」→ 任务 done、完成通知正常

## [M16 / R-034] 2026-09-05 — 素材库交互收尾
- 云端卡片「打开本地」按钮改为「语音转文字」，点击直达本地编辑弹窗触发转写
- 修复点击本地素材卡片页面闪动：移除标题重复 @click（冒泡导致 openItem 双触发）+ goLocal 免整页重载
- 编辑弹窗字段顺序：语音转文字入口 → ASR 转写（只读）→ 原始文案文本框

## [M17 / R-035] 2026-09-05 — 编辑页体验
- 封面上传/移除不再关闭编辑弹窗，只更新封面并后台静默刷新（新增 loadQuiet/loadWorksQuiet，去 loading 闪屏）
- 顶部上传视频成功→静默刷新并直接打开该素材编辑弹窗；云端转本地保存→静默刷新后打开编辑（去掉中间闪屏）
- 素材详情新增 platform_links（按 work 聚合三平台帖子）；编辑页展示抖音/B站/小红书作品链接（B站 bvid/av、抖音 aweme_id/原始 share_url、小红书 note_id），点击新窗口打开
- 新增 core/platform_links.py + 3 条离线单测（当前 18 项纯逻辑 + pytest 全绿）

## [M18 / R-036] 2026-09-05 — 编辑页三平台链接 + 按链接同步
- 去掉编辑页单条「发布链接」，改为抖音/B站/小红书三行链接输入（已绑定自动带出）
- 新增 POST /api/platform/videos/{id}/bind-links：解析并绑定各平台作品（local_video_id），错误逐项提示；保存时只绑定有改动的链接，避免重复建作品
- 「同步数据」升级为按素材绑定的全部平台逐个拉取：写各平台作品统计 + 当天本地指标快照（多平台聚合）；编辑弹窗内也提供「同步数据」按钮
- 素材详情 platform_links 支持 local_video_id 绑定；parse_post_id 支持 B站 av→aid 解析
- 测试 46 项通过；接口冒烟：非法链接 400、空链接 200、详情含 platform_links

## [M19 / R-037] 2026-09-05 — 本地素材评论 tab
- 本地素材编辑弹窗改为「编辑信息 / 评论数据」两个 tab（与云端素材评论 tab 一致）
- 评论数据 tab：按素材绑定的平台（抖音/B站/小红书）展示评论，「加载评论」实时调第三方并去重落库，之后直接读本地
- 素材详情 platform_links 增加 post_id（platform_posts.id）供评论 tab 使用

## [M20 / R-038] 2026-09-05 — 语音转文字统一放编辑页
- 云端卡片冗余「语音转文字」按钮移除；云端弹窗新增「保存并语音转文字」：选视频后一键转本地素材并自动开始后台转写（未选视频时禁用并提示）
- 本地素材编辑弹窗保留「语音转文字」按钮

## [M21 / R-039] 2026-09-05 — 博主页加载慢优化
- GET /api/platform/budget 默认只读本地预算（毫秒级）；余额改为 ?refresh_balance=true 显式拉取（页面未展示余额，不再为它卡整页）
- 博主页前端 creators/current/budget/summary 并行请求（Promise.all）
- 实测 budget 0.8s → ~1ms

## [M22 / R-040] 2026-09-05 — 全站接口批量性能优化
- 逐个实测所有页面首屏接口：多数已毫秒级；优化两处 N+1
- /api/works：预取账号/作品/统计，0.34s → ~0.07s
- /api/platform/posts：批量预取账号与最新统计，0.11s → ~0.06s
- 全部 46 项测试 + ruff/mypy/前端构建通过

## [M23 / R-041] 2026-09-05 — 素材库首屏渲染
- 新增 initLoad：本地素材与云端作品并行拉取、到齐后统一渲染一次，避免“先显示一条再补齐”

## [M24 / R-042] 2026-09-05 — 时间线倒叙
- 时间线最新在前（左）、越右越旧：排序倒叙 + 横轴反转（月份/事件/今天标记统一反推）
- 收紧两端留白（未来 +6 天、旧端 -3 天），不再滑到“没有内容/时间”的空尾

## [M25 / R-043] 2026-09-05 — 时间线全量 + 顺序修复
- 时间线事件 key 唯一化（v{id}/c{id}），修复本地/云端 id 撞号导致的渲染乱序
- 首页时间线云端数据改全量拉取（limit 2000，覆盖 2024 年老作品），不再“滑到后面没内容”
- 核查确认：1169 条云端作品全部有真实 publish_time（2024-03 ~ 2026-09）

## [M26 / R-044] 2026-09-05 — 时间线不再显示未来视频
- 时间线只显示“今天及以前”的发布时间：本地素材的“计划发布时间”在未来时不提前显示（到发布当天自动进入时间线）；云端未来时间兜底过滤
- 复核：最新素材（豆包 09-04）在数据源排序第一条；历史“顺序乱”为 id 撞号渲染 bug，已随 R-043 修复

## [M27 / R-045] 2026-09-05 — 时间线顺序修复
- 根因：同一天多条以当天为中心 ±94px 错开，相邻两天很近时旧卡片向左溢出到新日期前，把最新素材挤后
- 修复：严格“最新→最旧”顺序排布，同日多条按序排开、只往右推；真实数据验证第一条=豆包(09-04)、日期倒序、left 严格递增

## [M28 / R-046] 2026-09-05 — 时间线点击跳转修复
- 时间线点击云端作品不再跳博主页：Home 跳 #/videos?post={id}，素材库支持 post= 深链并打开该云端作品弹窗；已转本地的直接打开本地编辑

## [M29 / R-047] 2026-09-05 — 素材库点赞筛选
- 工具栏新增点赞 ≥/≤ 数值筛选（与查询按钮联动，多平台任一命中）

## [M30 / R-048] 2026-09-05 — 筛选栏/上传 UX
- 复核：上传本地视频成功即自动打开该素材编辑页（含按 id 拉详情兜底）
- 素材库筛选栏：占位/提示小字(11px)、去掉“点赞”文字标签、“≤/≥”数值框互换位置（≤ 左 ≥ 右，占位符自带符号）

## [M31 / R-049] 2026-09-05 — 素材卡片固定布局
- 云端卡片平台指标区固定三行（抖音/B站/小红书占位），缺失平台留空位，发布时间/按钮不上移
- 发布时间字号与点赞/收藏/评论一致（8px），颜色/省略一致

## [M32 / R-050] 2026-09-05 — 卡片去空白/按钮调小
- 素材卡片网格 align-items:start，去掉“等高拉伸 + 按钮贴底”造成的长空白；按钮回到内容正下方
- 卡片操作按钮（同步数据/确认标签/拆分/删除）由 small 调为 tiny

## [M33 / R-051] 2026-09-05 — 卡片缺失平台灰字占位
- 缺失平台行由“隐藏空行”改为浅灰“平台名 —”占位：不留空白、位置固定不上移

## [M34 / R-052] 2026-09-05 — 卡片统一骨架
- 本地素材卡片也渲染三行平台占位（—），与云端卡片骨架一致，同一行高度对齐

## [M35 / R-053] 2026-09-05 — 卡片同排等高
- 网格恢复等高拉伸 + 卡片 height:100%，同一行卡片外框等高
- 按钮行贴底、标签区限制 1~2 行高度

## [M36 / R-054] 2026-09-05 — 占位行同结构
- 占位行改为与真实行相同的五列结构（播放/赞/藏/评 —），本地与云端占位行统一

## [M37 / R-055] 2026-09-05 — 占位字号修复
- 占位格弃用全局 muted(12.5px)，改用继承 8px 的浅灰 .ph，占位平台名同色；与数据行字号一致

## [M38 / R-056] 2026-09-05 — 标签不隐藏
- 去掉标签区 max-height/overflow:hidden（云端行内联 overflow 同步去掉），标签多行完整展示、卡片自然增高

## [M39 / R-057] 2026-09-05 — 深度学习增强
- 新增 AI 腔禁用词清单（默认内置 + 可编辑）并注入生成 prompt
- 人设档案页新增「表达风格」面板：自动统计画像 + 禁词增删保存（GET/PUT /api/persona/style）
- 调度器新增每周日 03:20 风格重建：全量画像 + 表现最好素材 → 产出生成提示词候选并通知
- 复核查明：高互动加权检索/黄金样本/风格画像此前已实现并在生成中生效

## [M40 / R-058] 2026-09-05 — 视频/封面按标题命名
- 上传视频/封面、同步封面、编辑保存标题后，文件统一命名为「标题-视频 / 标题-封面」（安全清洗 + 重名 -2/-3）
- 删除素材时一并删除本地封面文件

## [M41 / R-059] 2026-09-05 — 文档体系
- docs/PRODUCT.md：全部功能产品手册（模块+流程+验收主线）
- docs/ARCHITECTURE.md：重写为详细架构（技术栈/进程/模块/ER/配置/部署）
- docs/DESIGN.md：开发设计（API/异步/定时/ASR/同步/生成算法/讨论/复盘/护栏）
- 全部含 Mermaid 流程图

## [M42 / R-060] 2026-09-05 — 文档体系 v2
- docs/API.md：90 接口完整参数/字段（OpenAPI 自动生成）
- docs/DATABASE.md：26 表完整字段/索引/外键（模型自动生成）
- docs/QUICKSTART.md 小白上手、docs/GLOSSARY.md 术语、docs/FAQ.md 排查
- README 文档导航更新

## [M43 / R-061 批次 A] 2026-09-05 — 代码体检清理
- 删除死代码 core/signature.py 与其测试（旧 FileTrans HMAC 已弃用）
- 下线无前端使用的 POST /api/platform/videos/{id}/bind-link（保留 bind-links 多平台版）
- 幂等补索引：platform_posts(local_video_id/publish_time)、videos(platform_post_id)、notifications(created_at)
- 新增每日 04:00 清理：通知90天/后台任务30天/同步记录60天/平台统计400天
- 逻辑与 UI 零变化；46 测试通过

## [M43 / R-061 批次 B 一期] 2026-09-05 — 性能与收敛
- 生成风格画像文本加入进程内缓存（素材数量/字数变化才重算，输出一致）
- 作品最新统计预取收敛为 works_service.latest_stats_map（works 列表与 platform 帖子列表复用，消除重复实现）
- 文档同步：重新生成 API.md（旧 bind-link 已下线）；ARCHITECTURE/DESIGN 定时任务补 04:00 清理；DATABASE 补运行时索引附录

## [M43 / R-061 批次 B 二期] 2026-09-05 — 检索缓存与收敛
- TF-IDF 风格样本检索索引进程内缓存（素材/指标/反馈/草稿版本变化才重建，结果一致）
- _post_item/post_item 合并为统一序列化 works_service.post_item（works 列表与 platform 帖子列表共用，返回为字段并集，既有前端不受影响）
- 未启用的 cookie 指标抓取不再每日空跑（仅保留留存清理）
- 新增 tasks.push_notification 统一通知写入（每周重建等改用它）

## [M43 / R-061 批次 C 一期] 2026-09-05 — 后端大文件拆分
- tikhub.py 拆出 services/platform/link_utils.py（链接解析纯逻辑，旧导入 re-export 兼容）
- platform_sync.py 拆出 services/platform_assets.py（图片识别/HEIC 转换/封面头像下载命名）
- 纯搬移，行为不变；46 测试通过

## [M44 / R-062] 2026-09-05 — 数据源适配器
- 新增 services/platform/base.py：DataSource 统一接口 + PostData/ProfileData 契约 + make_source/register_platform_source
- platform_sync 与 platform API 全部改走 make_source(platform)：默认 TikHub，可按整体或单平台注册替换
- 契约测试（test_core 19 项 / pytest 47 项通过）

## [M43 / R-061 批次 C 二期部分] 2026-09-05 — 预算模块 + 评论子组件
- platform_sync 拆出 services/platform/budget.py（额度/预算/计费，行为不变）
- 新增前端 MediaComments.vue 评论子组件并接入素材编辑页「评论数据」Tab（UI 不变）

## [M43 / R-061 C 继续] 2026-09-05 — 前端 composables 统一（第一块）
- 新增 src/composables/media.js（fetchVideos/fetchWorks）
- VideosView 5 处素材/作品拉取改走封装（load/loadQuiet/loadWorks/loadWorksQuiet/initLoad）

## [M43 / R-061 C 继续] 2026-09-05 — PlatformStats 子组件
- 新增 PlatformStats.vue：平台指标三行（含灰字占位）统一组件
- VideosView 本地/云端卡片平台区改用它，移除重复标记与 platOf/platOrder

## [M43 / R-061 C 继续] 2026-09-05 — 通用格式化工具抽 lib/format.js
- 新增 src/lib/format.js（platformName/fmtNum/fmt/parseTs/tsLocal/arrKey）
- VideosView 删除本地重复实现改从共享模块导入（同名引用，行为不变）

## [M43 / R-061 C 继续] 2026-09-05 — CreatorsView 复用 lib/format
- CreatorsView 删除本地 platformName/fmt/fmtNum，改从 src/lib/format 导入（行为不变）

## [M43 / R-061 C 继续] 2026-09-05 — composables 覆盖 Home/Dashboard/Drafts
- HomeView/DashboardView/DraftsView 素材拉取改走 fetchVideos（消除重复）

## [M43 / R-061 C 继续] 2026-09-05 — 时间线模型抽 lib/timeline.js
- HomeView 时间线计算整体抽为纯函数 buildTimelineModel（lib/timeline.js），HomeView 仅一行调用

## [M43 / R-061 C 继续] 2026-09-05 — MaterialCard 子组件（模板抽出，事件由 props 传入）
- 新增 MaterialCard.vue：素材卡片整块模板（本地/云端）抽出，点击/同步/确认/删除/拆分等事件由父页 props 注入

## [fix] 2026-09-05 — 云端“转素材”500 修复
- 原因：无文件本地素材 filename='' 撞 videos.filename 唯一约束
- 修复：占位名改 `__cloud__{post_id}`（works.to-local 同规则）；前端按占位名不显示转写按钮、标题显示素材标题

## [M43 / R-061 C 收尾] 2026-09-05 — C 组件化主要完成
- VideosView 14 组件 + CreatorsView 6 组件 + composables/lib 覆盖；后端拆分与适配器已完成
- 顺带修复：云端“转素材”500（空 filename 撞唯一约束 → __cloud__ 占位名）
- 剩余：D（schema 收敛，需备份迁移）及零散清理

## [M43 / R-061 D-1] 2026-09-05 — 绑定关系 schema 收敛（已备份迁移）
- 迁移前备份：backups/echo_pre_R061D_*.db
- 去重同 (local_video_id, platform) 重复绑定；videos.platform_post_id 指向作品反向补绑
- 新增唯一部分索引 ux_platform_posts_local_platform（防未来重复）

## [M43 / R-061 收口] 2026-09-05 — 文档同步收口
- 状态更新：A/B/C/D-1 完成；D-2（tags 表）/D-3（raw 归档）评估后暂缓
- DATABASE 附录：ux_platform_posts_local_platform 唯一部分索引 + __cloud__ 占位命名约定
- DESIGN/PRD/milestones/需求索引同步

## [fix] 2026-09-05 — 平台发布时间时区修复（时间线与发布时间对不上）
- 根因：平台时间戳用 utcfromtimestamp 存成 UTC，界面按北京时间展示导致凌晨发布差一天
- 修复：tikhub._ts 改为 fromtimestamp(Asia/Shanghai) 存储；存量一次性 +8h 迁移（platform_posts.publish_time + 平台转本地的 videos.published_at，已备份 echo_pre_tzfix_*.db）

## [feat] 2026-09-05 — 素材视频文件管理
- 新增接口：POST/DELETE /api/videos/{id}/video（给素材上传/替换/删除本地视频文件）
- 编辑弹窗新增「本地视频文件」控制（上传/替换/删除）；卡片对“未上传视频”素材显示「上传视频」入口

## [chore] 2026-09-05 — 历史封面批量改名「标题-封面」
- 1169 个存量平台封面按作品标题改为 `标题-封面.{ext}`（清理 #话题等仅按标题截断），并同步更新 platform_posts/videos/works 的 cover_path 引用
- 备份：backups/echo_pre_cover_rename_*.db

## [feat] 2026-09-05 — 命名规则调整：平台前缀 + 去 #话题
- 媒体命名统一 `{平台}-{主标题}-视频/封面`（标题去除 #话题等标签）
- 覆盖：同步封面、上传/替换/删除视频、标题修改改名、封面同步（media_naming.media_stem）
- 存量：平台封面/本地封面/视频批量重命名并同步 DB 引用（多次备份；旧视频原文件移至 backups/legacy_videos）
- 说明：一次清理脚本曾误删 videos/ 中未被数据库引用的原始视频文件，已从 /Users/yeah/document/chenP 恢复同名源文件

## [feat] 2026-09-05 — 合并素材编辑一致性
- 改标题或平台后保存：本地视频/封面自动按「平台-主标题-视频/封面」改名（含绑定平台后）
- 编辑本地素材保存：同步到绑定/合并的各平台帖子（标题/广告/价格/发布时间一致）
- 详情接口：本地缺发布时间/广告/价格时用绑定平台数据兜底返回（卡片与编辑弹窗一致）

## [docs] 2026-09-05 — 决策 D-011
- 记录：命名规则（平台前缀+去#话题）、合并/拆分共用文件不复制、编辑写回绑定平台帖子

## [M45 / R-063] 2026-09-05 — 时间线按“合并后作品”去重
- 首页时间线云端数据源：逐条平台帖 → 合并后作品（/api/works）：同一作品三平台合并为一条，未合并单条各自一条，与素材库合并状态一致
- 合并作品取最先发布的平台时间作为时间线日期；点击跳转：已转本地→本地编辑，未转→素材库对应作品
- 本地素材已绑定云端作品/合并作品的（由 works.posts[].local_video_id 反查集合）不再重复展示
- 陈旧漏合数据（早期 douyin 单条）需素材库点「自动合并」后收敛（与素材库同源）

## [chore] 2026-09-06 — 导航菜单顺序调整
- 「博主」菜单移到导航最末位（主页/素材库/脚本工作台/AI 对话/人设档案/数据看板/需求管理/AI 提示词/博主）

## [fix] 2026-09-06 — 素材库深链不弹窗
- 根因：?edit= / ?post= 只在组件挂载时解析一次，已在素材库页再改 URL 不会触发
- 修复：改响应式监听 route.query.edit/post（数据就绪后自动打开对应弹窗），打开后清掉 query 以便再次点击同一素材也能触发

## [fix] 2026-09-06 — AI 文案生成完成但脚本工作台看不到
- 根因：双模型讨论生成的占位草稿未写 creator_id（NULL），而工作台按当前主博主过滤，导致生成的文案查不到
- 修复：generate-async 建占位稿时写 creator_id；debate 后台任务兜底补归属；存量 NULL 草稿归属当前主博主（已备份 echo_pre_draft_creator_*.db）

## [M46 / R-064] 2026-09-06 — 提示词优化改用全量素材（按点赞率加权）
- 新增 learning_material：人设 + 语言画像 + 全部 ASR 转写文案按「点赞率/互动/时间衰减」加权取前 16 条
- 页面手动优化 / 导入后自动优化（每 3 条触发）/ 每周风格重建 三个入口统一走全量语料，不再只看最新视频
- 优化系统提示词明确“点赞率高的文案权重更高”

## [M47 / R-065] 2026-09-06 — 主页抓取更新抓到 0 条修复（热点改走 TikHub）
- 原因：real 模式抓抖音/B站/小红书公开接口全失败（反爬/500）→ 0 条
- 修复：real 模式优先走 TikHub 热搜（抖音热搜榜/B站热搜榜/小红书搜索联想词），无 key 退回公开接口
- 顺手修复 .env 该行注释黏连（ECHO_HOT_SOURCE_MODE=real#... → 分行）
- 实测一次抓取：抖音 51 + B站 50 + 小红书 60 = 161 条

## [M48 / R-066] 2026-09-06 — 系统时间统一为北京时间
- 原因：通知/任务/草稿等时间列用 datetime.utcnow 存 UTC，展示差 8 小时
- 新增 core/timeutil（now/today/tz，默认 Asia/Shanghai，ECHO_TIMEZONE 可覆盖）；全部模型与写时间点改用统一 now
- db.py 一次性迁移：历史 UTC 时间列 +8h → 北京时间（幂等，app_tz_migrated_v1，先于新写入执行）
- 验证：通知 03:18 → 11:18（北京），与当前一致

## [M49 / R-067] 2026-09-06 — 素材库卡片「同步数据」修复：三平台全同步 + 评论点赞 Top50
- 根因 1：云端合并卡（同一作品三平台合并）的「同步数据」只同步 cloudPosts[0]（第一个平台），其余平台不更新，提示也只报单个平台
- 修复：新增 POST /api/platform/works/{work_id}/sync（合并作品下全部平台帖逐个同步，单平台失败不中断）；卡片按钮按 work/post 分流
- 根因 2：本地已绑定素材卡同步后不刷新、且同步链路从不拉评论；评论接口不返回点赞数无法按 Top50 筛选
- 修复：本地卡 sync 后前端静默刷新；sync_local_video_metrics / sync_single_post / sync_work_posts 统一拉各平台评论（点赞 Top50）入库
- 评论结构化：DataSource.fetch_comments 返回 CommentData(text/likes/user_nick)；TikHub mock 确定性造数（可 ≥50 条）、real 解析抖音 digg_count / 小红书 like_count / B站 like
- platform_post_comments 增加 likes 列（轻量幂等迁移）；评论读取按点赞降序返回 Top50（text/likes/user_nick）；评论数据 tab 展示点赞数与昵称
- 自测：verify.sh 全绿（51 后端测试）；HTTP 冒烟通过（本地绑定三平台 + 云端合并卡均返回 3 平台、每平台 50 条评论按点赞降序、幂等不重复入库）

## [M50 / R-068] 2026-09-06 — 修复：模式配置注释黏连导致同步静默走 mock、假数据覆盖真实指标
- 现象：作者反馈最新视频抖音点赞应 5726，系统显示 10965，怀疑累加
- 根因（非累加）：.env `ECHO_TIKHUB_MODE=real# mock | real` 注释黏连 → tikhub_mode='real# mock | real' ≠ 'real' → TikHub 客户端静默按 mock 写假数据（10965/6303/3165 恰为该作品 ID 的 mock 确定性值）
- 修复：.env 改为 ECHO_TIKHUB_MODE=real；config.py 新增 normalize_mode（剥离行尾注释黏连/空白；非法值启动即抛错，杜绝再次静默假数据覆盖）；tikhub/hot_source/asr 三模式统一生效
- 数据恢复：重启后真实重拉今日 178 条快照（0 条残留假数据）；目标视频抖音 ≈5730（作者查看 5726，自然涨跌）；B站触发单轮 backfill（最多 150 条，耗时约 10 分钟）；小红书首轮读超时后单独重试成功
- 测试：新增模式规范化测试，共 52 项；verify.sh 全绿

## [M51 / R-069] 2026-09-06 — 修复：卡片「同步数据」按钮 loading 数字 id 撞车（点 A 误触发 B）
- 现象：点《很多岗位苦…》同步，旁边《用豆包agent…》的同步按钮也进入 loading/像被触发
- 根因：前者为合并作品卡（work_id=1），后者为单条云端卡（post id=1），R-067 后 loading 改按纯数字 item.id 判断 → 两张卡 id 同为 1 同时高亮；后端请求仍只发给被点卡片，未发错
- 修复：素材库「同步中」状态改按卡片唯一 key（w1/p1/v1…）判断，本地卡/云端卡统一；MaterialCard 与 VideosView 同步调整
- 自测：前端 lint/build 通过，verify.sh 全绿

## [M52 / R-070] 2026-09-06 — 同步前10条改前20条 + 前20条/全量同步加实时进度条
- 同步范围：run_sync daily 默认 topN 10 → 20（博主页按钮文案、每日 07:30/18:00 自动同步、单账号同步统一生效）
- 进度：sync_jobs 新增 progress_done/progress_total/progress_note（幂等迁移）；同步中按作品条数原子累加，note 实时显示“抖音：已同步 x/20 条 / B站：补全中 x/150”等
- GET /api/platform/jobs 增加 creator_id/account_id/进度字段
- 前端：博主管理页新增 SyncProgressBar，点「同步前20条」「全量同步」后 1 秒轮询，在对应博主卡片下显示实时进度；全量拉列表阶段（总数未知）显示流动动画“进行中”
- 测试：新增同步进度记录测试（53 项）；verify.sh 全绿

## [M53 / R-071] 2026-09-06 — 全量重写项目文档（API/DATABASE 自动生成 + 各文档按代码校准）
- docs/API.md：改由 FastAPI OpenAPI 自动生成（92 路由，含方法/路径/标签/参数/请求体/返回），不再手写过期内容
- docs/DATABASE.md：改由 SQLAlchemy 模型元数据自动生成（26 表 schema + 索引/唯一/外键/关系）+ 人工注释
- 按代码重写/校准：AGENTS.md、README.md、PRD、PRODUCT、ARCHITECTURE（定时任务以 scheduler.py 为准）、DESIGN（代码级地图）、milestones（M0–M52 + 待排期）、WORKFLOW、DECISIONS（整理 D-001~D-037）、QUICKSTART、GLOSSARY、FAQ
- 修正关键事实：数据目录由 .env 指向 echo_resource（非仓库 data/）、模式全部 real/aliyun、top20、评论 Top50、同步进度条、测试数 53、R-061 未用 Alembic 等
- 自测：verify.sh 全绿

## [M54 / R-072] 2026-09-06 — 主页灵感池人设相关化
- 展示：灵感池「全部/只看评论/只看热榜」标签；「全部」每批 8 条=评论与热榜各半交替，评论不再被热榜淹没；换一批轮换起点
- 人设相关度（纯本地零成本）：core/ideas.py 关键词命中打分（含赛道扩展词/#话题/红线词）；services/ideas_service.py 组装当前主博主人设画像
  - /api/topics/hot 返回 score/matched/redlined，命中红线词剔除；未建人设不误标
  - /api/platform/topic-pool 返回 likes/score/matched，按点赞降序
- 评论进池：平台同步对最近 10 条作品评论 Top50 尝试进池（按天去重）；topic_ideas 增 likes 列（幂等迁移 + 重复同步回填）
- 前端：评论行显示点赞与「相关」，热榜显示「低相关」排后
- 测试：新增相关度纯逻辑与画像标注测试（55 项）；verify.sh 全绿

## [M55 / R-073] 2026-09-06 — 每日流水线三槽生成（评论区 + 热榜 + AI 建议，均符合人设）
- 候选来源：评论槽（近 7 天评论灵感，人设命中优先）＋ 热榜槽（今日热榜人设打分命中优先，红线剔除）＋ AI 槽（LLM 依人设/热榜/评论高频/赛道缺口建议；无 key 启发式兜底）
- 候选去重、不足补足、无源退回原匹配；TopicCandidate 增 slot 列（comment|hot|ai，幂等迁移）留痕
- 每篇仍走完整生成上下文（人设/红线/风格样本/金句/对标）
- 测试：新增三槽组合测试（56 项）；verify.sh 全绿

## [M56 / R-074] 2026-09-06 — 去掉博主账号「同步频率」选择
- 账号弹窗去掉「同步频率」下拉、账号行去掉「每日/每周/手动」标签（该字段本不参与自动调度，留着误导）
- 自动同步 = 只看「启用自动同步」勾选；内部仍按主博主=daily / 对标=weekly 存默认值，不动表与后端逻辑
- 自测：前端 lint/build 通过，verify.sh 全绿

## [M57 / R-075] 2026-09-06 — 博主管理页顶部去掉「各博主粉丝/作品」汇总列表
- 仅前端：顶部第一个卡片不再展示各博主（我/对标）的粉丝/作品汇总行（下面每个博主自己的卡片已有详情）
- creator-summary 接口保留，页面不再调用展示；后端与数据不动
- 自测：前端 lint/build 通过，verify.sh 全绿

## [M58 / R-076] 2026-09-06 — 素材库加博主筛选框
- GET /api/videos 增加 creator_id 参数（默认当前主博主）；/api/works 复用已有 creator_id
- 素材库工具栏新增「博主」下拉：默认当前主博主，可切其它主博主/对标；切换后清空筛选并按该博主重载本地素材+云端作品
- 仅查看过滤，不切换全局主博主、不动数据
- 自测：verify.sh 全绿；接口按 creator_id 冒烟通过


## [M59 / R-077] 2026-09-06 — 素材卡「同步数据」补齐视频+转写
- 三个「同步数据」端点同步后自动预判：已有本地视频+转写则跳过；否则投递后台任务下载低清视频（缺）→ 自动 ASR 转写（缺）。
- 新增 services/media_ensure.py、services/media_downloader.py；tasks 增加「素材媒体补齐」通知；前端提示+轮询刷新。
- 抖音/小红书真实下载冒烟通过；B站 TikHub 播放流端点 404 暂不可用（代码预留）。顺带修复小红书单条详情统计解析。

## [M60 / R-078] 2026-09-06 — B站 yt-dlp 直连下载兜底
- B站素材卡「同步数据」补齐媒体：TikHub 播放流接口 404 时回落 yt-dlp 直连下载 480P 视频 + m4a 音轨，ffmpeg 合并 mp4（含音轨）后自动转写；瞬时风控重试一次。
- 新增依赖 yt-dlp（backend/requirements.txt）；复用 imageio-ffmpeg（标准名软链目录）。
- 真实作品 BV1Df421m7xF 实测下载成功（14.9MB mp4 含 Video+Audio）；verify.sh 全绿（67 项）。

## [M61 / R-079] 2026-09-06 — 素材库悬浮按钮改「多选」（批量删除/合并/同步）
- 悬浮「合并」→「多选」：云端+本地卡均可勾选；操作条提供 合并所选（云端≥2）/ 同步所选 / 删除所选 / 取消。
- 批量同步 = 逐张执行卡片「同步数据」（含 R-077 媒体补齐），汇总结果；批量删除沿用确认弹窗（本地连文件删）。
- 卡片【同步数据】按钮文案统一改【同步】（MaterialCard + CloudPostTile）。
- 纯前端改动；verify.sh 全绿。

## [M62 / R-080] 2026-09-06 — 卡片同步覆盖进度动画
- 单卡/批量同步时，整卡叠加透明蓝覆盖层自下而上慢慢覆盖；顶缘进度线；媒体补齐后台阶段缓慢推进至完成再补满淡出。
- 统一 runCardSync 入口（单卡+批量复用），与媒体补齐轮询合并；纯前端，verify.sh 全绿。

## [M63 / R-081] 2026-09-06 — 卡片同步进度后端实时推送 + 覆盖层阶段文字
- background_tasks 增加 note（阶段说明）；/api/tasks 支持 status/kind 过滤；platform_media 任务实时回写进度与文字（下载中/转写中等）。
- 前端覆盖层：请求阶段显示「数据/评论同步中…」，后台任务阶段显示后端推送的阶段文字+百分比；切页回来/跨页触发每 6s 扫描自动恢复覆盖层。
- 自测 verify.sh 全绿；API.md/DATABASE.md 同步。

## [M64 / R-082] 2026-09-06 — 同步自动下载素材归属修复（不跨博主）
- media_ensure._create_video 归属改为素材所属博主（work→账号→兜底）；新增 _fix_video_creator_binding 幂等迁移修复存量错挂。
- 效果：跨博主同步下载不再“跳到另一个博主素材库”；云端卡同步按钮正常保留；对标内容归属对标（D-028）。
- 新增测试；verify.sh 全绿。

## [M65 / R-083] 2026-09-06 — AI 预打标签自动确认
- import_video_task 打标成功后自动 tags_confirmed=True；存量已转写已打标素材回填确认；前端无标签不显示确认按钮。
- 新增测试；verify.sh 全绿。

## [M66 / R-084] 2026-09-06 — 素材库筛选条件记忆
- 素材库筛选（博主/平台/标签/状态/广告/视频/关键词/点赞区间）自动存 localStorage，切页/刷新后恢复。
- 切换博主仍会清空其它筛选（R-076 语义）；纯前端，verify.sh 全绿。

## [M67 / R-085] 2026-09-06 — 博主页同步按钮调整 + daily 带视频
- 全量同步按钮移到「同步前10条」之前；「同步前20条」文案改「同步前10条」（daily top_n 20→10，含每日自动）。
- run_sync 支持 with_media：daily（手动+07:30/18:00 自动）同步后对前10条下载视频+自动转写，并入通知；全量/每周仍不下载。
- 博主页【云端作品】文案改【作品】。
- verify.sh 全绿（新增测试）。

## [M68 / R-086] 2026-09-06 — daily 同步前15条
- run_sync daily 默认 top_n 10→15；博主页按钮「同步前10条」→「同步前15条」；每日自动同15条并带视频下载+转写。

## [M69 / R-087] 2026-09-06 — SSE 事件推送一期
- 后端新增进程内事件总线 + GET /api/events（SSE，15s 心跳）；task.update（进度/完成/失败）与 notification.new 实时广播。
- 前端 lib/eventbus + lib/sse（fetch 流带鉴权、5s 自动重连）；通知铃与素材卡进度改事件驱动，原轮询降为兜底。
- 采用 SSE（单向推送），未引入 WebSocket。verify.sh 全绿。

## [M70 / R-088] 2026-09-06 — 博主页同步进度可恢复 + 卡片级同步进度
- CreatorsView onMounted 启动任务轮询：切页回来恢复同步进度条。
- 新增 run_media_seq：博主页前15/每日自动的视频补齐逐条注册为 platform_media 任务并广播 task.update，素材库卡片显示覆盖进度并可恢复；全量/每周仍无媒体。
- verify.sh 全绿。

## [M71 / R-089] 2026-09-06 — 素材卡认领后端任务 + 进度不回退
- TaskOut 与 task.update 事件带 payload；素材卡按 work/post/video 认领任务（切页回来/博主页触发的媒体任务可显示）。
- 覆盖层进度单调不回退；同卡不重复覆盖。
- verify.sh 全绿。

## [M72 / R-090] 2026-09-06 — 通知深链跨博主打开素材编辑
- 素材库筛选到其它博主时，点击转写失败/补齐等通知也能打开对应素材编辑（按 id 拉取，不受筛选限制）。
- 纯前端，verify.sh 全绿。

## [M73 / R-091] 2026-09-06 — 博主页同步开始即素材库卡片动画
- SyncJob 创建/进度/完成广播 sync.job；素材库对当前博主运行中的同步任务让已有云端卡立即进入覆盖动画（显示当前阶段文字），独立媒体任务接管单卡进度，结束/切博主清理。
- verify.sh 全绿。

## [M74 / R-092] 2026-09-06 — 同步文案整体化 + 素材卡动画不闪没
- run_sync 收尾写整体说明；素材库运行中进度最高 98%，单平台“xx：完成”转“部分平台已完成…”；轮询空窗不再误清动画。
- 清理 _log_job 重复死代码；verify.sh 全绿。

## [M75 / R-093] 2026-09-06 — 逐素材同步队列（素材库卡片实时状态）
- daily 带媒体同步：账号分页对每条作品立即注册 card_sync 并广播排队，素材卡立刻动画；队列顺序做评论/数据 → 下载/转写；单条失败隔离。
- 取消 R-091 整片 job 覆盖层（不再“部分平台已完成/整片闪没”）；/api/tasks 支持 kind 逗号过滤。
- verify.sh 全绿（新增 card_sync 队列测试）。

## [M76 / R-094] 2026-09-06 — 下载超时兜底 + 转写失败通知 + 合并卡单平台下载
- 下载器整体 8 分钟超时兜底；转写“识别结果为空”标记 asr_status=failed 并给出可读原因；逐素材队列每条失败必 push 通知。
- 合并作品只下载一个平台视频（优先级抖音→小红书→B站），队列对同 work 去重跳过。
- verify.sh 全绿。

## [M77 / R-095] 2026-09-06 — 素材库点封面播放视频
- 视频目录静态挂载 /media/videos（含 Vite 代理）；点卡片封面弹播放器播放本地视频（无文件回退原逻辑）；点其它区域仍进编辑/详情。

## [M78 / R-096] 2026-09-06 — 封面播放图标 + 纯音频进度轨
- 素材卡封面有本地文件时显示播放小图标；播放器按 ffmpeg 探测结果：视频→video，纯音频→仅音频进度轨。

## [M79 / R-097] 2026-09-06 — 移除数据看板 + 博主对标（Top3/可讲/洗稿）
- 移除数据看板：前端菜单/路由/页面 + 后端 /api/metrics、/api/review 路由删除。
- 新增「博主对标」：对标最新10条互动分Top3；转写补齐（无文案自动顺延）；AI“我能不能讲”；能讲则按人设洗稿并存脚本草稿。
- 对标素材仍不进主博主人设语料（D-028）。verify.sh 全绿。

## [M80 / R-098] 2026-09-06 — 菜单改名 + 博主一键设/取消对标
- 「博主」→「博主管理」；非当前博主卡片加“对标博主”开关，打开转 benchmark（parent=当前主博主），对标行可恢复为独立主博主。

## [M81 / R-099] 2026-09-06 — 对标只取ASR文案 + 广告不对标
- benchmark candidates 过滤 is_ad；_unit_text 只用 ASR 转写稿（去掉 desc/title 兜底）。

## [M82 / R-100] 2026-09-06 — 对标文案/广告修复
- GET/top 带出已有 ASR 文案；按规范化标题过滤同款跨平台广告（防漏标）。

## [M83 / R-101] 2026-09-06 — 账号启用/禁用开关
- 账号行加开关；禁用后自动同步跳过，素材库/对标只取启用账号。

## [M84 / R-101] 2026-09-06 — 账号启用/禁用修复（补后端 /enabled 接口）
- 修复：R-101 首发只加了前端开关，后端 POST /api/creators/accounts/{id}/enabled 未实现，点击报 Method Not Allowed；补齐该接口并加回归测试。

