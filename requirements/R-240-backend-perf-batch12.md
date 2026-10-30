# R-240：后端性能优化（批次 1+2：接口慢点消除 + 可并行任务并行化）

- **日期**：2026-10-30
- **提出渠道**：对话（作者原话，原样记录）：「后端代码接口感觉很慢，而且有很多异步任务能并行的地方没有并行，你把后端代码全部阅读一下，看看怎么优化」
- **状态**：✅ 已完成（2026-10-30，`scripts/verify.sh` 全绿 + 8000 端口 GET 复测；实测收益见开发设计 §9）
- **开发设计**：`development-design/R-240-backend-perf-batch12.md`
- **审计依据**：`.tmp/audit/SUMMARY.md` 总报告 + `api.md` / `infra.md` / `sync.md` / `ai-services.md` 四份分工审计（全部结论带 `file:line` 证据与本机实测）
- **范围确认**（2026-10-30 作者选项）：批次 1（P0 快赢）+ 批次 2（P1 并行编排与请求路径）一起做；批次 3（P2 结构性/契约类）不在本次范围
- **依赖**：无新增第三方依赖；无数据库表结构变更；无 Alembic revision

## 1. 需求背景

作者反馈两件事：①接口感觉慢；②很多异步任务本可并行却串行。

四名审计员只读通读 `backend/app` 全部模块（149 文件 / 28,853 行）+ 本机只读实测，确认「慢」不是数据库/硬件瓶颈（本地 PG、DB 实测占用仅 1~8 连接、`/health` 基线 1.1ms），而是三类可修问题叠加：

1. **列表/汇总 GET 的 N+1 与全量加载**：`GET /api/benchmark/top` 447ms / 810 条 SQL；`GET /api/works` 210ms / 1.64MB；`GET /api/library` 141ms 且是「假分页」（每次翻页全量重建 613 卡，耗时与 limit 无关）；`GET /api/persona/style` 76ms / 218 条 SQL；`GET /api/douyin-review/references` 112ms / 22 条 SQL；`GET /api/opportunities/ledger` / `attribution` 冷启动 593ms / 225ms。
2. **后台长任务的串行编排（本可并行）**：提示词金样本评测 5 样本 × 2 版本 = 10 次独立 LLM 全串行；每日流水线与提示词自测各 3 篇独立草稿串行生成；对标准备逐候选串行（含媒体补齐与逐条广告判定 LLM）；重新对标逐对标博主串行；日更媒体补齐每博主仅 2 worker 且单卡「下载→ASR→LLM 校对/打标」串行（实测日更 30min）；转写失败无退避（17 条 failed 每天重试，吃掉 20~35% 媒体容量）；日更尾部串行补采同行播放量。
3. **LLM 客户端与超时放大**：`llm.py` 每次调用新建 `httpx.Client`（一篇稿 12~13 次调用，白扔 1.3~3.9s 握手且受系统代理抖动影响）；600s 单次上限 × 重试/降级 3 次 = 单次逻辑调用最坏 1800s，chat 的 120s deadline 只检查轮次边界、不约束进行中的调用；每次 AI 调用前 21 条 `app_kv` 单查；生成上下文每次重复构建（实测 108 条 SQL / 38~47ms，随语料线性增长）。

## 2. 想要实现的目标

### 2.1 核心目标（可量化验收）

| 类别 | 目标 | 验收指标（本机，更新前后各测 3 次） |
|---|---|---|
| 读接口 | 消除 N+1 / 全量加载 / 假分页重复计算 | `benchmark/top` 447ms→≤60ms；`works` 210ms→≤60ms（缓存命中 <10ms）；`library` 141ms→≤50ms（缓存命中 <10ms）；`persona/style` 76→≤25ms；`douyin-review/references` 112→≤40ms；`opportunities` 冷启动 593/225ms→≤150/60ms（并加预热/防击穿） |
| 可并行任务 | 独立 LLM/媒体任务并行 | 提示词评测 10 次 LLM 串行→并发（墙钟 5~10×）；每日流水线/提示词自测 3 篇草稿并发（≈3×）；对标准备广告判定 4→1 次 LLM；重新对标按博主并发（2~4×）；日更媒体全局池 + 卡内 LLM 后处理并行 + 转写失败退避（日更墙钟 30min→15~20min 目标，需压测） |
| LLM 基础 | 客户端复用 + 超时预算 | 每篇生成省 1.3~3.9s；每次 AI 调用 KV 查询 21→≤3；交互类最坏墙钟 1800s→≤270s；chat 单次调用受 deadline 约束 |
| 可观测 | 请求耗时/慢 SQL 可观测 | 新增约 30 行中间件：`X-Response-Time` 响应头 + >500ms `log.warning` + 每请求 SQL 条数（dev 采样），作为全部验收的度量工具 |

### 2.2 明确不做

- 不改数据库表结构、不加 Alembic revision、不动 `docs/DATABASE.md` 表清单。
- 不整体改 `async def` / 不引入 Redis/MQ/新第三方库；继续沿用「同步 def + anyio 线程池 + threading 后台任务 + `sync_pool.gather`」架构。
- 不并行化业务真依赖：双模型讨论的「评审→修订」「第 N 轮→N+1 轮」保持串行（R-023/R-139 产品定义）。
- 不改任何接口的请求/响应字段契约（前端零改动）；不删除/改名现有路由。
- 批次 3（P2）不做：library SQL 真分页、works 游标/字段瘦身、chat 流改 async、`background_tasks.status` 索引 migration、`start_task` 全局并发上限/去重、budget 计费合并、B 站进度防抖、统一 `core/http.py`、topic_mining 并发、model_health 并行、persona merge 并行、chat 工具墙钟等（保留在审计报告中作为后续需求）。
- 不调整 TikHub 令牌桶/重试参数、不盲目调大同步并发（避免上游 429/400）。

## 3. 页面数据来源（本次不改数据来源，只改读取方式）

| 页面/功能 | 数据来源（现状） | 本次变化 |
|---|---|---|
| 对标页首屏（`GET /api/benchmark/top`） | `creators` / `platform_posts` / `videos` / `transcripts` / `platform_post_stats` / `app_kv`（分析结果） | 查询方式改批量预取，数据与排序口径不变 |
| 素材库（`GET /api/library`） | `platform_posts`+`creator_accounts`+`works`+`videos`+`platform_post_stats` | 增加「卡片快照」短 TTL 进程内缓存（同一份数据），失效由数据版本键 + 同步完成事件兜底 |
| 博主管理页（`GET /api/works`） | 同上 | 同上（缓存复用） |
| 人设页（`GET /api/persona/style`、`/phrases/suggest`） | `videos`+`transcripts`+`metrics_snapshots`+`persona_tags`+`app_kv` | 改批量预取，输出内容不变 |
| 视频复盘页（`GET /api/douyin-review/references`、`/videos`、复盘分析任务） | `platform_posts`+`platform_post_stats`+`douyin_post_metrics`+`video_reviews` | 改批量预取，排序/过滤口径不变 |
| 首页（`GET /api/opportunities/ledger`、`/covered`、`/attribution`） | `drafts`+`metrics_snapshots`+`platform_posts`+`topic_ideas`+`feedback` | 保留 120s/300s TTL 缓存，增加单飞锁 + 后台预热 |
| 生成/讨论/回炉（后台任务） | `persona_tags`+`videos/transcripts`+`drafts`+`draft_versions`+外部 LLM/联网搜索 | 生成上下文静态部分缓存（键含素材版本+人设版本）；LLM 客户端复用 |
| 每日同步（后台任务） | TikHub / ASR Provider / 本地媒体文件 | 媒体并发改进程级全局池；转写失败退避；同行播放量补采移出主链路 |
| 提示词页（评测/自测后台任务） | `ai_prompts`+`prompt_evals`+`feedback`+`drafts`+LLM | 独立 LLM 调用并发 |

## 4. 功能需求（后端行为，不新增页面/按钮）

### 4.1 接口性能（无 UI 变化，响应内容不变）

1. `GET /api/benchmark/top`：返回结构不变（`benchmarks[].items[]` 字段不变），内部批量预取，耗时不随对标数/作品数线性放大。
2. `GET /api/library`、`GET /api/works`：分页/筛选语义与返回字段不变；`next_cursor`/`has_more`/`total`/`filtered_total`/`facets` 语义不变；同一数据版本 20s 内重复请求走缓存（毫秒级）。
3. `GET /api/persona/style`、`GET /api/persona/phrases/suggest`：字段不变，查询数从 O(素材数) 降为常数级。
4. `GET /api/douyin-review/references`、`GET /api/douyin-review/videos`：字段与排序不变，最新 review 改一次批量取。
5. `GET /api/opportunities/ledger|covered|attribution`：字段不变；缓存过期后不再让第一个请求同步等全量重算（单飞 + scheduler 预热）。
6. 每个 HTTP 响应新增 `X-Response-Time: <ms>` 头（附加信息，不影响既有契约）；>500ms 请求写一条 warning 日志（含方法/路径/状态/耗时/SQL 条数）。

### 4.2 后台任务并行化（行为可见性不变）

1. 提示词金样本评测：候选版/当前版、5 个样本的独立 LLM 调用并发（并发数默认 3，`.env` 可调），输出评分与留痕内容不变、顺序不变。
2. 每日流水线生成、提示词启用后自测：多篇互相独立的草稿生成并发（默认 2 并发），每篇仍是一次完整双模型讨论；进度/通知/失败语义不变。
3. 对标准备：候选广告判定合并为 1 次批量 LLM（4 条一起判），媒体补齐并发（复用媒体全局池）；「前3+最新」排序与顺延语义不变。
4. 重新对标：各对标博主并发（复用 `sync_pool.gather` + 独立 Session），进度百分比按完成数上报；单博主失败不阻断其它。
5. 日更媒体补齐：媒体消费改进程级全局池（默认 6，`ECHO_SYNC_MEDIA_CONCURRENCY` 语义改为「全局媒体并发数」），轻量卡优先不变；单卡内「LLM 校对」与「预打标」两个互不依赖的调用改并发（各自独立 Session）；转写失败写 `app_kv` 计次/下次可重试时间，≥3 次跳过并发通知（避免每天重复失败）。
6. 日更尾部：同行播放量补采从主链路移出为独立后台任务（失败不影响同步结论），任务内部低并发（3）+ 保留全局令牌桶，不删除既有 0.25s 降速保护。
7. 同步按钮（`POST /api/platform/works/{id}/sync`、`/posts/{id}/sync`、`/videos/{id}/sync`）：多平台作品/多绑定帖的 stats+comments 独立请求并行（写库回主线程），响应结构与错误语义不变。
8. 遗留同步 LLM 接口：`POST /api/drafts/generate`、`POST /api/inspiration/{id}/develop`、`POST /api/platform/topic-pool/{id}/generate` 本次不改契约（避免前端改动），但给其 LLM 调用加短超时预算（如 ideas 30s），并把「后续改后台任务」写入遗留清单；`/api/drafts/generate-async` 已是正确路径。

### 4.3 空数据/失败表现（不变）

- 无数据/无消费者场景返回空结构（沿用现状）；批量预取后空集合归一为 `{}`/`[]`，不得抛 KeyError。
- 并行子任务失败：沿用现状「单条失败不阻断整批」；新增的并发运行器必须收集异常并记录日志，绝不能因单个 LLM 失败让已生成内容丢失。
- 缓存失效失败/版本查询失败：降级为直算（fail-open 到现有逻辑），不影响正确性。
- 媒体/转写失败：保留「失败」终态与通知；新增退避后仍可手动重试（手动同步路径不受退避限制）。

## 5. 用户故事

1. 作为作者，我打开对标页，首屏应该在几十毫秒内出现（当前 447ms/810 条 SQL），页面内容与排序不变。
2. 作为作者，我在素材库连续滚动/切筛选时，每一页都应该快速返回（当前每页 141ms 全量重算），不会越滚越卡。
3. 作为作者，我打开博主管理页时，作品列表不再一次拉 1.64MB/210ms。
4. 作为作者，我点「优化提示词/金样本评测」后，后台任务应明显更快完成（10 次串行 LLM → 并发），进度与结果展示不变。
5. 作为作者，我点「生成」同时有多篇（每日流水线/提示词自测）时，几篇应并行生成，而不是一篇等完再等下一篇。
6. 作为作者，我点「重新对标/对标准备」时，多个对标博主应并行处理，任务耗时 2~4× 缩短，单个失败不影响其余。
7. 作为作者，每日同步的媒体补齐应更快结束（30min → 15~20min 目标），失败转写不再每天重复消耗时间，同行播放量补采不再拖住同步完成。
8. 作为作者，我点单卡「同步数据」时，多平台的指标/评论请求应并行，等待从 3~8s 降到 1~2s。
9. 作为作者，我点击生成后每篇稿件的等待不会因为 LLM 客户端反复建连、配置反复查库而无谓变长；最坏情况不会再「卡 30 分钟」。
10. 作为开发者，我能从响应头/日志里直接看到慢接口与慢 SQL，用于后续持续优化。
