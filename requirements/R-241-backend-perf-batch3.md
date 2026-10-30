# R-241：后端性能优化收尾（批次 3：结构性优化与复核遗留项）

- **日期**：2026-10-30
- **提出渠道**：对话（作者原话，原样记录）：「把剩下的优化做完」
- **状态**：✅ 已完成（2026-10-30，`scripts/verify.sh` 全绿 + 8000 端口冒烟；实测收益见开发设计 §9）
- **开发设计**：`development-design/R-241-backend-perf-batch3.md`
- **依据**：`.tmp/audit/SUMMARY.md` 批次 3（L1~L9）+ `.tmp/audit/REVIEW.md` 复核遗留项；R-240（批次 1+2）已完成并合并
- **范围确认**：作者在 R-240 复核后要求把批次 3 与复核遗留的 P2/P3 优化全部做完（不改前端、不改接口字段契约）
- **依赖**：R-240（已完成）；本需求含数据库变更（2 列 + 1 索引，Alembic revision）与 `docs/DATABASE.md` 同步

## 1. 需求背景

R-240 已完成批次 1+2（读接口批量预取/缓存、可并行任务并行化、LLM 客户端复用与超时预算、转写退避、请求耗时中间件），实测读接口从 447/141/210ms 降到 ~30/10/9ms，生成链路与日更任务预计大幅提速。

但审计总报告的**批次 3（结构性/契约类，P2）**与 R-240 四路复核发现的**遗留项**尚未处理，具体表现为：

1. **卡片缓存仍有 20s 陈旧窗口与过期重建开销**：视频标题/标签等原地编辑、同日统计原地更新不会改变版本键（`videos` 无 `updated_at`、`platform_post_stats` 无 `updated_at`），只能靠 TTL 兜底；缓存过期瞬间并发会重复重建；`stats_count` 用全表 COUNT 导致任一 creator 新统计让所有缓存失效。
2. **ai/chat 流仍占线程与 DB 连接**：`POST /api/chat/stream` 用同步生成器，整条流占 1 个 anyio 线程；`ChatService.reply` 全程不 commit，1 个 DB 连接常驻到回答结束。
3. **后台任务线程无全局上限、部分入口无去重**：`start_task` 每任务一线程；双击/重试会并发跑重复任务（如两条完整双模型讨论），任务风暴时打满 DB 池/供应商配额。`background_tasks.status` 无索引，前端 10s 轮询走全表扫。
4. **写放大/观测噪音**：预算 `_charge` 每次请求多次 SQL+commit 且持有全局锁；B 站补全进度每一批都强制 commit+publish（「补全」在强制刷新词里）；每个 TikHub 媒体卡 `make_client()` 都新建 httpx.Client（无连接复用）；封面/头像/搜索每次新建连接。
5. **剩余 N+1/串行点**：内容机会 weekly/attribution/ledger 逐视频查询（实测 456/440 查询）；提示词优化语料 `learning_material` 逐视频 `_platform_breakdown`（565 查询）；站内素材检索 `retrieve_station` 300 视频懒加载（380 查询）且在联网检索返回后才串行执行；证据选文/DeepSeek Fetch 无缓存。
6. **剩余可并行/可观测点**：模型兼容性自检 2 槽×3 探针全串行；人设 `merge_full` 分块合并串行；热点抓取逐平台串行、逐条存在性查询；聊天工具无单工具墙钟、`get_content_opportunities` 三分支串行；重新对标进度缺中间态。

## 2. 想要实现的目标

### 2.1 核心目标（可量化验收）

| 类别 | 目标 | 验收 |
|---|---|---|
| 卡片缓存 | 数据变更**精确失效**（≤1 个请求周期内可见，不再依赖 20s TTL 盲区）；过期并发只重建一次；`by-post` 不再全量重建 | 编辑视频标题/标签后下一次 GET 立即新值；6 并发过期只构建 1 次；`/api/works/by-post/{id}` 204ms→<10ms；`stats` 版本按 creator 作用域 |
| chat 流 | 流式回答不再占用 anyio 线程；DB 连接不在整个回答期间常驻 | 流期间 `/api/chat/stream` 不占 worker token；`ChatService` 每次 LLM 调用前 commit；SSE 事件格式/顺序/错误语义不变 |
| 后台任务 | 全局并发上限 + 同 kind+payload 自动去重；任务轮询走索引 | 双击生成只产生 1 个任务；并发任务数 ≤ `ECHO_MAX_PARALLEL_TASKS`（默认 8）；`/api/tasks` 查询走 `(status, created_at)` 索引 |
| 写放大 | 预算计费单条原子 UPDATE；B 站进度防抖生效；外部 HTTP 共享客户端 | 每次 `_charge` 1 条 UPDATE+1 commit；B 站每轮 commit 次数从 ~150 降到个位数；TikHub/资产/搜索复用连接（单卡不再新建 Client） |
| 剩余 N+1 | opportunity/learning_material/station_evidence 批量预取；站内检索与联网检索并发；证据选文/Fetch 缓存 | weekly_pack 456→≤20 SQL、attribution 440→≤10、learning_material 565→≤10、retrieve_station 380→≤10；生成链路首次少一次串行 DB 段（-0.3~1s）；同选题重跑命中证据缓存（-1 次 LLM、-2~45s） |
| 并行化收尾 | 自检/人设合并/热点抓取/聊天工具并发与超时 | 模型自检 1~4min→30~90s；人设合并 3~4×；热点 45s→~15s；单工具超时 ≤30s（超时跳过让模型收尾）；问题机会三分支并发 |
| 契约 | 前端零改动、接口字段/错误码不变；仅新增 2 个 DB 列 + 1 个索引 | OpenAPI schema 不变；`verify.sh` 全绿 |

### 2.2 明确不做

- 不新增前端页面/字段，不改任何接口请求/响应契约（`/api/works` 不加游标、`/api/library` 分页参数不变）。
- **不做 library 的 SQL UNION 真分页 / works 字段瘦身/游标**（批次 3 原 L1 的契约类部分）：改为「DB 列精确版本键 + 缓存单飞 + 查询列瘦身」达成同等目标（数据变更即失效、命中即毫秒级），避免接口契约变更与 R-179 语义漂移风险；若未来数据量级显著增长再单独立项。
- 不引入 Redis/MQ/新第三方依赖；不改异步框架（chat 流改 async 生成器属点状改造）。
- 不做批次 3 之外的项（如 pg_stat_statements、全文检索等）。

## 3. 页面数据来源（本次不改数据源，只改读取/失效方式）

| 页面/功能 | 数据来源 | 本次变化 |
|---|---|---|
| 素材库（`GET /api/library`） | `platform_posts`/`creator_accounts`/`works`/`videos`/`platform_post_stats` | 版本键加入 `videos.updated_at`、`platform_post_stats.updated_at`；缓存单飞；查询列瘦身 |
| 博主管理（`GET /api/works`、`/by-post`） | 同上 | 同上 + by-post 直查绑定帖 |
| 复盘/博主页（`GET /api/platform/creator-summary`） | `creators`/`creator_accounts`/`creator_account_snapshots`/`platform_posts`/`platform_post_stats` | 3 层 N+1 改批量 SQL，输出不变 |
| AI 对话（`POST /api/chat/stream`） | `chat_*`/`agent_actions`/工具数据 + LLM | 流改 async；ChatService 每轮 commit |
| 首页内容机会（`/api/opportunities/*`） | `drafts`/`metrics_snapshots`/`platform_posts`/`topic_ideas`/`feedback` | weekly/attribution/ledger 批量预取；三分支并发 |
| 提示词优化（后台任务） | `videos`/`transcripts`/`platform_post_stats`/`feedback`/`drafts` | `learning_material` 批量预取 |
| 生成/洗稿（后台任务） | 站内素材 + 联网检索 + LLM | 站内检索与联网检索并发；证据选文/Fetch 缓存 |
| 热点刷新（后台任务） | 各热点源 HTTP + `hot_topics` | 平台并发抓取 + 批量去重入库 |
| 模型自检（后台任务） | `app_kv` + LLM | 探针并行 + 探针级超时 |
| 人设初始化/重建（后台任务） | `videos`/`transcripts` + LLM | 合并分块并行 |
| 每日同步（后台任务） | TikHub/ASR/本地文件 | 预算原子计费、B 站进度防抖、HTTP 连接复用 |

## 4. 功能需求（后端行为，不新增页面/按钮）

### 4.1 接口行为（字段/契约不变）

1. 列表/详情读接口：返回字段、排序、分页游标、facets、错误语义全部不变；数据编辑后下一次请求即可见（不再有 20s 陈旧盲区）；缓存过期并发不重复构建。
2. `/api/chat/stream`：SSE 事件类型（step/reply/error/done/start）、顺序、错误文案不变；流期间不再占用请求线程池线程，DB 连接不再全程占用。
3. `/api/tasks`：查询命中新索引；`limit` 上限 clamp（默认行为不变）；返回字段不变。
4. 后台任务：同 kind+payload 的重复触发（双击/重试）在运行中自动去重（返回已有 task_id，行为与现有 `find_running_task` 入口一致）；全局并发不超过配置上限，超出任务保持 pending 排队（不丢任务、可见进行中）。
5. 预算接口/降级通知：`_charge` 语义不变（超预算抛 `BudgetExceeded`，计费次数不变），只减少事务/锁持有。
6. 所有写路径的数据更新语义不变；新增 `updated_at` 列由 ORM 自动维护（创建/更新时刷新），旧数据回填迁移时间。
7. `GET /api/works/by-post/{post_id}`：返回同结构，只查该 work 的成员，不再全量重建。
8. `GET /api/platform/creator-summary`：输出字段/口径不变，查询数 703→≤10。
9. 空数据/失败表现：沿用现状；批量预取/并发子任务单条失败不阻断整批；缓存版本查询失败 fail-open 直算；async 流异常仍以 SSE `error` 事件收尾。

### 4.2 后台任务行为

1. 模型兼容性自检：2 槽×3 探针并行（并发 ≤3），每探针 60~90s 超时；结果结构与通知不变。
2. 人设合并：分块合并并行（≤4），轮间 barrier 保留；结果与串行一致。
3. 热点刷新：平台并发抓取（每源独立 try/except）、入库前批量查重后一次 commit；结果集与去重口径不变。
4. 聊天工具：每个工具调用有单次墙钟（默认 30s，超时返回可读跳过原因让模型收尾）；`get_content_opportunities` 三分支并发（各自独立只读 Session），输出结构不变。
5. 重新对标：进度增加「计算前3+最新」中间态（不改变返回结构）。
6. 生成/洗稿：站内素材检索与联网检索并行；证据缓存命中时跳过选文 LLM 与正文补齐（输出与未命中路径一致，仅省时）；生成上下文/讨论轮次逻辑不变。
7. 日更/同步：预算计费原子化、B 站进度合并写、HTTP 连接复用；失败/预算取消/单条不阻断语义不变。

## 5. 用户故事

1. 作为作者，我编辑素材标题/标签后，回到素材库立刻看到新值（不再等 20 秒）。
2. 作为作者，我素材库快速翻页/切筛选时不再周期性卡一下（缓存过期只重建一次，且只读命中毫秒级）。
3. 作为作者，我在 AI 对话里连续提问时，其它接口不会被聊天流拖慢（不再占线程/连接）。
4. 作为作者，我双击「生成/重新对标/评测」按钮不会跑两份任务，顶栏任务队列也不会被大量重复任务淹没。
5. 作为作者，我打开首页内容机会、提示词优化、模型自检、人设重建时，等待时间比现在更短，结果与之前一致。
6. 作为作者，我点单卡「同步数据」/日更同步时，多平台与封面下载更快，预算计数与同步结果不变。
7. 作为开发者，我能从日志里看到慢请求与任务排队情况，后续持续优化有数据可依。
