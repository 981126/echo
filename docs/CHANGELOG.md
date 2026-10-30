# 变更记录

## [R-239] 2026-10-30 — 账号级创作者 Cookie 与数据源策略（含 R-238 合并）✅

- 视频复盘去掉 Cookie 配置入口，只保留账号创作者数据只读状态与「去博主管理配置」引导。
- 博主管理「编辑账号」新增抖音创作者数据区块：启用开关 + Cookie（不回显）+ 状态/最近成功 + 保存并验证；账号行显示可用/未配置/已关闭/已失效徽标。
- 新增 `GET/PUT /api/creators/accounts/{id}/douyin-credential`，移除 `/api/douyin-review/credentials`（路由总数不变）；保存/仅切开关均可用，校验失败返回可读原因且不回显 Cookie。
- 账号级数据源策略：开关关闭/未配置 Cookie → 公开接口；开启且 Cookie 有效 → 创作者中心（作品列表/指标，评论/媒体仍公开）；开启但 Cookie 失效 → 停止该账号所有第三方调用、发一次通知并标记失效，直到更新 Cookie；B 站/小红书不变。
- 平台同步、素材库同步、单帖同步、视频复盘刷新、评论加载、媒体补齐全部接入统一策略；失效账号零第三方请求。
- 合并 R-238：素材库卡片显示真实播放（`plays_known/plays_source`）；公开接口 0 不覆盖创作者真实播放（来源优先级合并）；首次自动回填（426 条作品 / 约 12 次请求，417 条匹配入库）；每日两轮同步后自动保鲜；`metrics_snapshots` 改为从 DB 最新统计聚合。
- 表结构：`douyin_creator_credentials` 新增 `enabled` 列 + Alembic revision `r239douyincred`；DATABASE/API/FAQ/QUICKSTART 同步。
- 验证：`scripts/verify.sh` 全绿；真实接口冒烟（创作者/公开切换、失效停采+通知、恢复、历史回填、素材库真实播放、页面点检）。

## [R-237] 2026-10-29 — 抖音视频复盘、涨粉与下一步主题（✅ 2026-10-30 真实接口联调完成）

- 新增「视频复盘」：自己的视频比较、原因与证据、涨粉与主页分析、1 个首选 + 2 个备选主题、首选后续 3 条、3 个新话题、主题采用和修改后检查；只支持抖音。
- 数据链路：TikHub 创作者数据手动更新 + 每日两轮快照，公开低粉榜/搜索与专用播放统计补全；原始 JSON、按天指标、复盘、证据、推荐和作者修改全部留痕。
- 判断逻辑：同发布天数中位数/百分位和有效样本门槛；同行只认手动对标，爆款需同时满足前 25% 和至少 2 倍；主题按真实涨粉、观众需求、作者适合度、公开证据和新鲜度排序，无依据时不硬推。
- 页面：指标卡、当前/平时条形图、观看趋势折线、来源/搜索/评论问题/主题涨粉/修改前后图，图表与数据表同源；手机与桌面点检通过，后台任务切页/刷新可恢复。
- 安全：Cookie 使用 Fernet 加密入库，密钥只在 `ECHO_DOUYIN_COOKIE_KEY`，不回显、不进日志/任务/AI 输入。
- 新增 7 张表（现 38 张）、14 个操作（现 161 个）及 Alembic revision；新增后端和前端测试。
- 验证：`scripts/verify.sh` 全绿；有效样本边界、低粉标签/链接/播放补全通过。
- **真实接口联调（2026-10-30）**：本机登录抖音创作者中心取得 Cookie 后，用真实 TikHub + DeepSeek 跑通全链路——创作者私有字段（播放/点赞/评论/收藏/转发、2 秒跳出率、5 秒完播率、完播率、平均播放时长、主页访问量、吸粉量、流量来源、搜索词、观看/跳出趋势）、1 首选 + 2 备选 + 3 后续 + 3 新话题、真实 LLM 文字整理、同行爆款与低粉爆款均验证；负向验证 Cookie 失效报错且不写空数据/不覆盖旧结果、页面失败不丢上次成功复盘。
- **联调修复**：creator/v2 HTTP 200 业务错误码识别（`status_code=8 用户未登录`）、真实字段映射（`view_count/bounce_rate_2s/completion_rate_5s/avg_view_second/homepage_visit_count/subscribe_count`）、流量来源与搜索词改独立接口、低粉榜 `data.data.objs` + 蛇形字段/毫秒时长解析、同行播放量 `fetch_video_statistics` 补采（6 小时复用）、partial 复盘复用、`/credentials` 500、失败回退上一次成功复盘与 charts 结构兜底、吸粉量改为该视频带来的新增关注。
- **限制**：平台不返回自己的「封面点击率」，页面显示暂无数据、不估算；Cookie 过期需在页面重新保存。

## [R-236] 2026-10-27 — Alembic 版本化迁移 ✅

- 移除每日定时及部署阶段的自动备份入口、脚本、测试与现行文档。
- 删除 initdb/create_all 初始化路径；`db.py` 只负责连接与会话。
- Alembic 统一管理 31 张业务表、索引、8 个分析视图和默认提示词；空库自动 upgrade，完整旧库校验后 baseline，不完整旧库拒绝接管。
- 测试覆盖空库、重复迁移、旧库 baseline 和异常旧库拒绝；部署与开发文档同步。

## [R-235] 2026-10-21 — SQLite 全面迁移 PostgreSQL：连接串 / 方言改写 / 测试库 / 部署备份 ✅

> 作者：我已经将数据迁移到pgsql（yeah981.cn:15981/echo_dev），将项目中的 sqlite 代码改为 pgsql，移除 sqlite 相关代码。

- **连接（fail-closed）**：新增 `ECHO_DATABASE_URL`（只从 .env 读、无默认，缺失启动报错；驱动写法 `postgresql+psycopg://`）；`config.py` 删除 `db_path/ECHO_DB_PATH` 派生；`db.py` 改 psycopg v3 引擎（pool_pre_ping/recycle），WAL/busy_timeout 等 SQLite 专用配置全删。
- **历史迁移全删**：`db.py` 里 ~25 个幂等 `_migrate_*` 与一次性数据修复（UTC+8、回填、去重…）全部删除，`init_db` 只留 create_all + 索引 + 绑定唯一部分索引 + 提示词 seed + 分析视图；`schema_guard.py`（R-144）与 `schema_migrations` 表/模型随迁移记账一起下线，main.py 启动流程简化。
- **方言改写**：`chat_sql.py` 从 sqlite3 只读连接改为 SQLAlchemy 引擎 + 服务端 `default_transaction_read_only` + `statement_timeout` 双保险；`scheduler.py` 清理 SQL 的 `datetime('now','-N days')` 改为 Python 侧算好截止点参数化传入。
- **测试**：66 个测试文件全部改为 `conftest.fresh_engine()`（共享引擎 + 每测试 `TRUNCATE ... CASCADE` 清全表，保持空库语义）；conftest 加**库名安全闸门**——目标库不是 `echo_test` 直接拒绝启动；新增 `scripts/init_test_db.sh` 从 echo_dev 复制结构+数据到 echo_test；删除 `test_r144_schema_guard.py` 与 `fixtures/schema_baseline.sql`。
- **部署**：`scripts/backup.sh` 由 SQLite 热备改 `pg_dump --format=custom`（连通性预检 + 空 dump 校验）；`deploy.sh` 去掉 echo.db 检查、结构自检改为「模型表 vs 实际库」比对；`release.sh` 打包校验去掉 echo.db；`docker-compose.yml` 去掉 `ECHO_DB_PATH`（数据库不在卷里，容器直连 NAS 宿主机 PG）。
- **文档**：ARCHITECTURE/DATABASE/QUICKSTART/OPS-PARALLEL/AGENTS.md 同步（OPS-PARALLEL §2.3/§4.2 改为「每 worktree 独立 PG 库」，SQLite 流程收进历史折叠块）。
- **验证**：pytest 全量绿（1 个 pg_dump 用例本机无 PG 客户端跳过）；后端连 echo_dev 冒烟待 verify 后执行。

## [R-234] 2026-10-18 — NAS 一键部署脚本：git 快进 → 备份 → 构建 → 上线 → 健康/结构自检 ✅

> 作者：我需要一个脚本，在 nas 执行后会自动拉取本项目 git 最新代码，然后前后端打包成 docker 部署。

- **`scripts/deploy.sh`（新）**：预检 `.env`/Docker → `git fetch` + `merge --ff-only origin/main`（已跟踪工作区脏则中止，不 stash/reset）→ 容器内 `scripts/backup.sh` → `docker compose build`（前端 Node 多阶段 + 后端 Python 单镜像）→ `up -d` → 容器 healthcheck 轮询（默认 180s）→ 库结构自检；日志写 `data/logs/deploy-*.log` 并保留 30 份。
- **首次/失败策略**：首次没有 `echo.db` 自动跳过备份；构建失败保留旧容器；健康检查失败打印日志并非零退出，上一版镜像保留为 `echo:previous`（不自动回滚数据库，迁移只向前）。
- **`scripts/update.sh`**：降为兼容入口，`exec` 到 `deploy.sh`；`SKIP_PULL=1` 继续有效。解包/非 git 部署用 `--no-pull`。
- **`docker-compose.yml`**：加 `image: echo:local` 稳定 tag；容器内固定 `ECHO_DATA_DIR=/app/data`、`ECHO_DB_PATH=/app/data/echo.db`（避免搬 `.env` 时把 macOS 路径带进来）；宿主卷改 `${ECHO_HOST_DATA_DIR:-./data}:/app/data`。
- **修正**：`.env` 默认的 `./data` / `./data/echo.db` 在容器 `WORKDIR=/app` 下等价 `/app/data`，不再误报路径告警；只有真正像宿主机路径（如 `/Users/...`）才提示改用 `ECHO_HOST_DATA_DIR`。`--dry-run` 现在只预检/打印，不会 fetch/merge、构建或重启。
- **验证**：`bash -n` + `--help` + 临时仓库/假 Docker 干跑（首次、脏工作区、缺 `.env`、构建失败、unhealthy、非 git 解包）；`scripts/verify.sh` 全绿；**NAS 实机首次构建/启动待作者执行**（本机 Docker daemon 未运行）。

## [R-233] 2026-10-18 — 脚本生成联网参考双源化：豆包 + DeepSeek 搜索 / 正文 / 去营销 / 生成方按人设选文 ✅

> 作者：脚本生成网上抓取素材新增 deepseek 搜索，豆包和 deepseek 同时 search，Fetch 正文，排除营销内容，由脚本生成方根据当前主博主人设选定某几篇作为参考参与生成。

- **双源并行**：新增 `deepseek_search.py`（Search `need_content=true` 直接拿正文 + Fetch 补抓；4 QPS 限速/429 重试/1h 缓存/失败静默）；`evidence.gather_online` 线程池同时打豆包与 DeepSeek，单路挂掉不影响另一路。
- **合并与过滤**：URL 去追踪参数去重 + 标题近重去重；剔除 GitHub 代码页/文件下载页；营销规则（站点黑名单、转化话术、课程招生、电商域）命中即剔并记原因；相关度过滤沿用 R-227。
- **正文补齐**：DeepSeek Search 自带正文优先；豆包 `Content` 与 `Summary` 等长或缺正文时调 Fetch（最多 4 篇、并发 3、15s 超时、25s 总预算），失败退回摘要；按相关度抽段截到 2000 字。
- **生成方选文**：用生成方槽位模型带「人设标签/红线/语言风格 + 选题 + 候选摘要」选 2–3 篇并给理由；45s 超时/解析失败自动按相关度兜底（实测真实选文约 24s）；只把选中正文注入初稿与每轮讨论，`sources` 只对已选清单解析。
- **留痕与展示**：`web_search_logs` 豆包/DeepSeek 各一行（`source` 区分、`results` 含 kept/rejected 原因、`used` 双行回写）；`Draft.quality.references` 只存轻量元数据（正文在留痕里，避免草稿列表被 10KB 级 JSON 拖慢）；依据面板默认展示「生成方按人设选了 N 篇 + 理由 + provider」，可展开全部候选。
- **降级**：无 DeepSeek key/开关关闭 → 只跑豆包；选文失败 → 自动兜底；两路都不可用 → 证据块为空，生成照旧。
- **自测**：`scripts/verify.sh` 全绿（32 表 / 147 路由）；新增 `test_r233_deepseek_refs.py`（双源/去重/营销/正文/选文/超时/双行留痕/单路降级）；真实冒烟选中 2 篇知乎并给出具体理由；1 轮全链路生成成功。

## [R-173/R-227] 2026-10-15 — 讨论进行中正文置灰只读 + 中间浮出「模型在干嘛」动画 ✅

> 作者：AI 讨论的时候，编辑 Markdown 文本框置灰不可编辑，中间展示动画「什么模型正在干嘛」。

- 编辑 tab 的正文区：`debate.state==='running'` 时整体 `pointer-events-none + opacity-50`（只读、不可编辑），中间浮出一张卡片动画（`ThinkingDots` + `{讨论/生成/洗稿}进行中` + 当前 `note`（含模型名/阶段）+ 第 x/y 轮），随步骤实时更新；讨论完成自动淡出。纯前端改动。

## [R-227 修复] 2026-10-15 — 讨论页实时显示依据 + 修复 AI 草稿误报「本地未同步内容」✅

> 作者：① AI 双模型讨论的稿子每次点进去都提示「有没有同步到服务器的本地内容」；② 讨论**开始前**豆包就搜完了，讨论页应该马上能看到观点和参考。

- **② 依据尽早可见**：`debate._merge_quality()` 让 `run_debate`/`run_rewrite_debate` 把**联网搜索词 / 来源 / 站内素材**在「出发前」就先写进 `Draft.quality`，初稿一出再补写 `outline/outlines/sources`——不必等整轮讨论跑完。前端抽屉在讨论进行中每轮轮询 `/api/drafts/{id}`，把 `quality` 实时喂给「论点 / 引用来源」面板（`liveQuality`）。
- **① 误报本地副本**：根因是 AI 正在写这篇草稿时，抽屉的自动保存把编辑器内容 PATCH 回去、保存失败就在该草稿留下「本地未同步副本」。修复：
  - 讨论进行中（`debate.state==='running'`）**不自动保存**（后端在写，完成后由轮询回填 + `markSaved`）；
  - 打开草稿时若 AI 在跑，本地副本一律不提示；若**服务端 `updated_at` 晚于副本时间**（副本已过期）→ 静默丢弃，不弹提示。
- **自测**：`scripts/verify.sh` 全绿。

## [R-112 修复] 2026-10-15 — 素材抽屉「商务广告 / 广告价格 / 实际发布」保存不生效 ✅

> 作者：「素材库抽屉里面的商务广告勾选按钮 点击保存没有生效」

- **根因**：`PATCH /api/videos/{id}` 保存后调用 `_sync_local_to_posts()`，其中一段**从绑定平台帖反向回填** video 的 `is_ad`/`ad_price`/`published_at`，把用户的手动「取消勾选 / 清空」立即覆盖；`get_video` 读时也做同样 OR，导致抽屉重开又显示旧值。
- **修复**：`_sync_local_to_posts` 改为只做「本地 → 平台帖」**单向推送**，不再反向回填（空值展示兜底由 `get_video` 处理）。前端「商务广告」`label` 加 `htmlFor` 关联，点文字也能切换。
- **影响范围**：`is_ad`、`ad_price`、`published_at` 三个字段现在以**本地素材值为准**；标题/状态/计划发布/标签/文案/平台链接原本正常。
- **自测**：`scripts/verify.sh` 全绿；新增 `test_video_update_ad.py`（取消勾选/清空价格/清空实际发布不被回填）。

## [M228 / R-227] 2026-10-15 — 第 2 步：站内真实素材检索（作者素材 + 对标参考）✅ 已完成

> 作者确认：事例层用 ASR 稿 + 脚本工作台「完成」的**作者侧**稿；对标素材也取，但只作创作参考。

- **做了什么**：新增 `backend/app/services/station_evidence.py`
  - **事例层（作者）**：主博主非广告视频的 ASR 转写（`corrected_text` 优先）+ `status='done'` 的**作者侧**稿（`AUTHOR_SOURCES`，无 AI 版本才算）；句/段级切片（≤400 字）。
  - **参考层（对标）**：对标博主非广告视频转写，标注「他人，非你经历」，**不进入人设学习/提示词优化（守 D-028）**。
  - 按选题相关度（中文 bigram 重叠）取名 3–5 条 + 对标 2–3 条（不做表现加权）；排除广告/空转写；文本去重。
  - `run_debate` / `run_rewrite_debate` 把站内素材块与联网证据块合并注入；`GENERATION_SYSTEM`/`REWRITE_SYSTEM` 规定**优先用「站内素材·你的」**，对标禁止写成自己的经历；`Draft.quality.station` 存作者/对标元数据，`EvidencePanel` 展示「你的素材 / 对标参考」。
- **自测**：`scripts/verify.sh` 全绿（32 表 / 147 路由）；新增 `retrieve_station` 用例；真实冒烟：选题「面试反问…」命中作者口播片段 + 对标（陈同学在上海等）。

## [M228 / R-227] 2026-10-15 — 联网检索 Query 智能构造 + 全入口接入 + 来源展示 ✅ 已完成

> 作者：「豆包引用来源会搜出毫不相关的东西」「提交给豆包搜索的原文问题也需要展示出来，放到论点、引用来源同一个框顶部」

- **根因**：洗稿直接用**对标源视频标题**当 query（如「最烦这类人」），口语化无实体、且未开 QueryRewrite、无相关性过滤 → 搜出泛文；且没有一个入口把「更具体的文本」带进来。
- **做了什么**：
  - `web_search`：开豆包 `QueryControl.QueryRewrite`（口语→搜索式）、可配 `time_range`。
  - `evidence`：`build_search_query(topic, material)`＝选题 + 该入口最具体文本（截断 100 字）；`filter_relevant()` 按关键词（含中文 bigram）重叠度过滤，全不相关则返回空；**只发起了搜索就写留痕并回传 query（即使 0 结果）**。
  - **各入口 query 源**：洗稿=对标源正文；灵感随手记=随手记原文；灵感池评论=评论原文+作品标题；热点=标题；灵感机会（观众提问/每周包/缺口）=样本/理由；纯标题回退「标题+QueryRewrite」。
  - `run_debate(..., query_source=)` 统一接证据：`draft_flow.start_generation` / `api/drafts.generate-async` / `api/inspiration.develop_note` 透传；`home.tsx` 各卡片带上上下文。
  - 生成契约（`GENERATION_SYSTEM`）与洗稿对齐：2-4 条论点 + 具体支撑 + 有证据必须引用 + 禁编造；评审/修订加内容维度；`outlines/sources/online_sources/search_queries` 落 `Draft.quality`。
  - 前端 `EvidencePanel`：**顶部显示「豆包搜索词：…」**（留痕）；「引用来源」**默认只显示已引用**，可「查看全部检索到的 N 条」展开。
- **明确不做（本次）**：站内真实素材检索（作者 ASR/定稿 + 对标参考）仍排下一步；不引向量库。
- **自测**：`scripts/verify.sh` 全绿；新增 `build_search_query`/`filter_relevant` 用例与 `EvidencePanel`（搜索词/只看已引用）用例；真实冒烟：query＝「面试别当老实人… + 源正文」，返回「面试反问话术 / 无薪试岗违法 / 社保」等相关结果。

## [M228 / R-227] 2026-10-15 — 洗稿先行「证据支撑」内容质量（联网事实 + 论点/事例 + 来源留痕）✅ 已完成（第 1 步）

> 作者：「在灵感池生成、灵感随手记、洗稿这几个功能生成文案，生成的内容质量都不高，因为没有论点，没有真实的事例，所以观众像是听了整篇废话，没有有用的东西」「有没有可能联网去搜索一些事实事例」

- **根因**：生成/洗稿管线以「像作者」为唯一目标——提示词只有一句软要求、评审词只查风格/AI 腔、没有真实事实检索层、契约也没有论点/事例字段，模型只能凭空编或复述素材。
- **做了什么**：
  - 新增 `backend/app/services/web_search.py`：豆包搜索薄客户端（读 `ECHO_WEB_SEARCH_API_KEY`，1h 缓存、15s 超时、失败静默）。
  - 新增 `backend/app/services/evidence.py`：按选题联网检索 → 证据清单注入 prompt；写 `web_search_logs` 留痕；`resolve_used()` 校验引用编号（越界=编造来源，剔除）。
  - 新增表 `web_search_logs`（`backend/app/models/web_search.py`，`create_all` 自动建）；同步 `docs/DATABASE.md`（32 张表）。
  - `benchmark.REWRITE_SYSTEM`：硬要求「1 主张 + ≥1 具体事例/数据、有证据必须引用、禁编造」+ JSON 契约 `outline/sources`；`_rewrite_user` 注入证据并补传 topic（`author_style_context(db, title)`）。
  - `debate.run_rewrite_debate`：注入证据清单；评审词加内容维度「有没有主张/具体事例/是否与证据一致/有无空话」；`outline/sources/online_sources/search_queries` 落 `Draft.quality`；回写留痕 `used`。
  - 前端：草稿抽屉 + 洗稿对照弹窗展示「论点 / 引用来源（含链接）」，可核对留痕；正文不插 URL/编号（来源区按顺序对应）。
  - `tests/conftest.py` 关闭联网（fail-closed，避免测试打真实外部世界）。
- **作者确认的边界**：对标素材只参与创作参考、不进入人设学习/提示词优化（守 D-028）；站内事例层（第 2 步）用作者 ASR + 作者侧定稿；排除广告/空转写；按选题相关度取。
- **明确不做（本次）**：不动 DeepSeek/Kimi 调用链、不引向量库；站内素材检索与灵感池/随手记推广排第 2/3 步。
- **补丁（同日）**：契约由「一句话 outline」改为**多条 `outlines`（2-4 条，每条带支撑 claim/support）**；抽出共享组件 `frontend_v2/src/components/evidence-panel.tsx`——草稿抽屉与洗稿弹窗的「论点 / 引用来源」改为**两个可点击切换的标签**（来源里已引用的排前并标「已引用」，未引用置灰），**右侧独立小箭头可收起/展开**。
- **自测**：`scripts/verify.sh` 全绿；新增 `test_r227_evidence_rewrite.py`（含 `_parse_outlines` 多条/兼容用例）。

## [M227 / R-226] 2026-10-15 — 素材卡片标题去话题 + 三平台标签合并去重 ✅ 已完成

> 作者：「1.标题去掉标签 2.卡片点赞下方的标签，需要将三个平台的话题合并去重」

- **根因**：抖音同步把含 `#话题` 的整条文案当标题存入（`platform/tikhub.py`），跨平台合并时又取「最长成员标题」，于是卡片名带着 `#找工作 #求职…`；而抖音 top15 同步口径不写 `tags` 字段，话题只留在标题里，卡片下方标签因此常为空。
- **做了什么**：
  - 新增 `backend/app/services/text_tags.py`：`extract_hashtags`（提取并过滤纯平台词）+ `strip_hashtags`（去 `#话题`、含全角 ＃、规整空格），`platform/tikhub.py:_tags_of` 改为复用。
  - 标题清洗：`platform_sync._ensure_post` 写入时、`works_service` 自动/手动合并、`api/works.py`/`api/platform.py`/`media_ensure`/`benchmark` 建素材时统一去话题；`library_service` 卡片标题再兜底去一次（去完为空回落文件名/简介）。
  - 标签合并：`library_service._cloud_cards` 聚合三平台已存 `tags` + 从标题/简介补提 `#话题` + 绑定本地素材标签，忽略大小写去重，成员按 抖音→小红书→B站 排序（卡片仍显示前 3 + “+N”）。
  - `backend/app/services/title_cleanup.py` + `main.py` 启动钩子：Kv 幂等一次性清洗历史 `platform_posts.title`/`works.title`/`videos.title`（去完为空则保留原值；平台原文仍在 `desc`/`raw`）。
- **明确不做**：不新增表、不改 API 契约；不删平台原始文案。
- **自测**：`scripts/verify.sh` 全绿；新增 `test_r226_title_tags.py`。

## [M224 / R-222] 2026-10-15 — B站账号同步整账号回滚修复 ✅ 已完成

> 现象：B站账号 `sync_status=failed`，报 `'NoneType' object does not support item assignment`，0 条作品入库，B站帖不参与自动合并。

- **根因**：并发补全作品指标时循环变量 `for pd, stats, error in ...` 与外层累计字典 `stats` 重名；末条补全为 `None` 时覆盖外层 `stats`，随后 `stats["posts"] += 1` 抛异常 → 整个账号 rollback。B站列表常缺 like 字段，必然进入该分支。
- **做了什么**：`platform_sync.sync_account` 循环变量改名 `fetched_stats`；新增 `test_r222_sync_stats_shadow.py` 回归。
- **自测**：真实重同步 B站账号后导入 15 条、`sync_status=done`，目标帖绑定回 work。

## [M226 / R-225] 2026-10-15 — 素材库抽屉平台勾选由绑定作品决定 ✅ 已完成

> 作者：「素材库里面明明一个视频发了多个平台，而且卡片也展示了多个平台，但抽屉里面平台却没有勾上，是为什么」

- **根因**：卡片平台（云端合并卡）实时从绑定的 `PlatformPost` 成员推导，抽屉平台勾选却读取 `Video.platforms` 数据库列；该列只在创建/绑定/手动保存时写，合并/同步时不会重算，导致抽屉勾不上或与卡片不一致。
- **做了什么**：
  - `backend/app/api/videos.py:get_video`：存在 `_bound_platform_posts` 时，用成员平台集合覆盖 `out.platforms`，与卡片同源。
  - `backend/app/services/works_service.py`：新增 `recompute_video_platforms()`，在 `auto_merge_creator` / `merge_manual` / `split_work` 时持久化刷新 `Video.platforms`。
  - `backend/app/api/platform.py:post_to_material`：取帖子所属 work 的全部成员平台，而非仅单平台。
  - `frontend_v2/src/pages/videos/edit-drawer.tsx`：已绑定平台作品（`platform_links.length > 0`）时，平台勾选框 `disabled` 并显示提示；未绑定本地素材保持可编辑。
- **明确不做**：不删 `Video.platforms` 列；不改变未绑定本地素材的平台可编辑性；不做平台自动解绑。
- **自测**：`scripts/verify.sh` 全绿；新增 `test_r225_video_platforms_from_bound_works.py`。

## [M224 / R-222] 2026-10-10 — 同步再提速：账号内并行 + 批量写库 + 消除 N+1 ✅ 已完成

> 作者：「页面不卡，不过我觉得后台请求有点慢，最慢的其实是同步数据」；当前 12 个账号 daily 前 15 条约 20+ min，要求不引入 Redis/MQ、不砍 B站 150 条历史指标补全。

- **根因**：不是 TikHub 10 req/s 限速不够，而是**请求结构太串行 + 写库太碎**。单账号内作品/评论/B站补全逐个执行；每条作品 `_ensure_post`、每条评论 `_upsert_comments`、每次进度 `_job_progress` 都单独 `commit`；循环内反复查询 `PlatformPost`/`PlatformPostComment`/`TopicIdea` 造成 N+1；账号级并发硬编码 3，与配置不匹配。
- **做了什么**：
  - `config.py`：新增 `ECHO_SYNC_ACCOUNT_CONCURRENCY`（默认 3）、`ECHO_SYNC_POST_CONCURRENCY`（默认 5）、`ECHO_SYNC_DOWNLOAD_CONCURRENCY`（默认 4）、`ECHO_SYNC_COMMIT_BATCH_SIZE`（默认 20）、`ECHO_SYNC_PROGRESS_DEBOUNCE_SECONDS`（默认 2.0）。
  - `services/platform/tikhub.py`：`_TokenBucket.acquire(n)` 支持批量令牌；`TikHubClient` 复用 `httpx.Client` 减少 TCP/TLS 握手；对应测试改为 mock `httpx.Client.get`。
  - `services/platform_sync.py`：
    - `sync_account` 预加载该账号已有 `PlatformPost` 字典；列表未带 stats 的作品先走 `_fetch_post_stats_parallel` 并发补全；
    - `_ensure_post` / `_write_stat` / `_upsert_comments` / `pool_ideas_from_comments` 支持 `commit=False` 批量模式 + `existing` 预加载字典；
    - 作品/统计按 `sync_commit_batch_size` 分批 `commit`，封面下载拆为 `_ensure_covers_batch` 在事务外批量处理；
    - `_collect_comments` 对最近 10 条作品走 `_fetch_comments_parallel` 并发抓取，预加载当天 `TopicIdea` 去重；
    - `_backfill_bili_stats` 预加载最新指标消除 N+1，150 条详情并发抓取后批量写入；
    - `_job_progress` 同 job_id 进度累计 + 防抖 flush（2s / 阶段关键词 / 完成），降低 SQLite 写锁竞争；
    - `run_sync` 账号并发数改读 `ECHO_SYNC_ACCOUNT_CONCURRENCY`。
  - `services/media_downloader.py`：B站 dash 视频/音频流并行下载。
- **明确不做**：不引入 Redis/MQ/RQ；不迁移 SQLite → PostgreSQL；不减少 B站 150 条历史指标补全；媒体并发 `ECHO_SYNC_MEDIA_CONCURRENCY` 保持 2（N150 CPU 限制）。
- **自测**：`scripts/verify.sh` 全绿（ruff + mypy + pytest 484 例 + 前端 lint/tsc/build + 文档一致性 31 表/146 路由）；后端 pytest 连续跑 3 轮全绿。

## [M225 / R-223] 2026-10-10 — 同步所有博主 `database is locked` 修复 ✅ 已完成

> 作者：「同步所有博主抱错 `(sqlite3.OperationalError) database is locked [SQL: UPDATE creator_accounts SET sync_status=...]`，内层异常是 `UPDATE app_kv ... tikhub_budget_used:2026-10-09`」

- **根因**：不是锁等待时间不够（WAL 已开、`busy_timeout=30s`），而是 **`_ensure_post()` 与 `_upsert_profile_snapshot()` 在 SQLite 写事务里做同步网络 I/O**（下载封面图/头像，timeout 8s），导致写锁被该 Session 长时间持有。并发同步多个博主/账号时，一个线程持锁下载图片，其他线程的 `_charge()` 要写 `app_kv` 表更新 TikHub 预算计数，等待写锁超过 30s 即报 locked。
- **做了什么**：
  - `services/platform_sync.py::_ensure_post()`：先 `commit` 提交作品与统计信息释放写锁；再在事务外调用 `_cover_path_for()` 下载封面、生成缩略图；最后用独立短事务把 `cover_path` 写回 `PlatformPost`。
  - `services/platform_sync.py::_upsert_profile_snapshot()`：先 `commit` 提交 profile 快照与昵称变更释放写锁；再在事务外调用 `_ensure_account_avatar()` 下载头像；最后用独立短事务把 `avatar_path` 写回 `CreatorAccount`。
  - `services/platform_assets.py`：`_cover_path_for()` 去掉未使用的 `db` 参数；`_ensure_account_avatar()` 改为纯下载函数、返回 `str | None`，不再接收 `db` 也不再内部 `commit`。
  - `services/platform_sync.py::_fetch_comments_parallel()` / `_fetch_post_stats_parallel()`：修复 inner thread 直接访问主 Session ORM 对象导致的 `ObjectDeletedError`（flaky，pytest 输出捕获下必现）；主线程预先把 `platform`/`platform_post_id`/`raw` 等 primitive 字段传入，inner thread 只读这些字段，返回后按 `platform_post_id` 映射回原始对象。
- **明确不做**：不动 WAL / busy_timeout / 连接池配置；不动 TikHub 限速与重试逻辑；不改并发度；不迁移数据库。
- **自测**：`scripts/verify.sh` 全绿（ruff + mypy + pytest 484 例 + 前端 lint/tsc/build + 文档一致性 31 表/146 路由）；后端重启 `/health` 正常；真实触发「同步所有博主」日志中无 `database is locked`（本轮 12 博主中 8 成功，4 个因启动前服务重启被历史遗留标记为「任务中断」）。

## [M223 / R-221] 2026-09-30 — 垃圾邮件根因：pytest 在用真实 SMTP 发夹具稿 ✅ 已完成（测试隔离，业务代码零改动）

> 作者：「服务一直在发垃圾邮件，这是bug吧，下面是邮件内容 echo · 今日选题与脚本 / 1. 选题B / 平台：douyin · 匹配度：60 · 【今日最佳 · 热榜】理由 / 封面字：（无） / B 的口播稿正文」

- **根因**：不是服务在发——是**测试在发**。邮件正文与 `tests/test_r208_daily_best.py` 的夹具逐字一致；该用例调用 `pl.push_daily_best()` → `notify.send_daily_best` → `_send`，而 `tests/conftest.py` 只隔离了数据目录/API Key，**没隔离 SMTP**，`app/config.py` 的 `env_file=(".env","../.env")` 让 pytest（CWD=`backend`）读到仓库根 `.env` 的真实 QQ 邮箱配置 → 真的 login + sendmail；每跑一次 `scripts/verify.sh`（pytest 全套）就多一封。反证：真实库 `pipeline_runs` 只有历史 1 条、`notifications` 从无 `daily_best`、`app_kv` 无 `daily_best_pushed:*` → 运行中的服务从未触发该推送。
- **做了什么**（`tests/conftest.py`）：
  - **fail-closed**：导入 app 前清空 `ECHO_SMTP_USER/ECHO_SMTP_AUTH_CODE/ECHO_MAIL_TO`（环境变量优先于 `.env`）→ `mail_config_problem()` 必然返回「未配置」，默认配置下任何用例都发不出信。
  - **兜底闸门**（autouse）：`notify.smtplib.SMTP_SSL` 装 tripwire，抛 `RealMailAttempted(BaseException)`——故意不继承 `Exception`，`_send` 的 `except Exception`（R-141）吞不掉，谁补回配置真发信就当场炸穿用例。
  - `test_r208_daily_best.py` 发信改 spy 断言推送内容（标题/正文/理由/封面字），不再依赖环境真实 SMTP；新增 `tests/test_r221_mail_isolation.py` 三条锁定（默认配置 `_send` 返回 False／配置合法被闸门拦下／夹具稿在测试环境只写站内通知）。
- **明确不做**：不动 `notify.py` 与流水线语义（邮件仍是次要通道、失败不判 failed）；不动 `send_daily_digest` 的「force 重跑再发一封」语义（UI 不传 `force`，要改属新需求）。
- **自测**：`scripts/verify.sh` 全绿；邮件相关 4 个测试文件 25 例全过、零外发（修复前用假 SMTP 捕获到原用例真实外发报文，修复后闸门无一被触发）。

## [M222 / R-220] 2026-09-30 — 素材库切页同步遮罩必现：未认领池 + 卡片到位补挂 ✅ 已完成（前端 only，后端零改动）

> 作者：「博主管理点击同步后，切换到素材库有时候，素材卡片会展示同步动画，有时候不会，我知道他在同步，是因为查询任务接太慢了还是什么原因」

- **根因**：不是任务接口慢——`/api/tasks` 很快，**输给了更慢的 `/api/library`**。卡片同步遮罩（`use-card-tasks.ts`）的切页恢复只有 mount 时一次扫描：冷缓存时扫描先回、卡片列表为空，card_sync 按 `post_id` 匹配不到卡片被**静默丢弃且永不重试**；热缓存才有动画。叠加：跨页 SSE 丢失（订阅随页卸载、无回放）、恢复查询只筛 running、翻页新增卡片不补认领。
- **做了什么**（`use-card-tasks.ts`）：
  - **未认领池**（taskId→TaskRow）：恢复扫描与 SSE 未知非终态任务统一入池，不再静默丢弃；终态/已被认领出池。
  - **自动补挂**：cards 每次变化（首帧到位/翻页加载）对池重新 `cardKeyForPayload`，命中即挂遮罩 + 5s 轮询并出池（`claimPool` 纯函数，可单测）。
  - 恢复查询改 `status=pending,running`（`/api/tasks` 已支持多值，后端零改动）；命中但卡片已被其它任务接管 → 留池待重试。
- **明确不做**：服务端 SSE 回放（超范围）；「作品列表未拉完前素材库无卡片可显示」的空窗由顶栏「进行中 N」负责（数据依赖非 bug）；后端零改动。
- **自测**：`scripts/verify.sh` 全绿；vitest `use-card-tasks.test.ts` 7 例全过；headless `r220-library-mask-race.mjs` 5 项全绿——复现竞速（/api/tasks 立即回、/api/library 延迟 800ms），卡片到位后遮罩必现、5s 轮询保持、落定 opacity 1、无页面报错。

## [M221 / R-219] 2026-09-30 — 博主管理同步进度可见性：完成条延迟消失 + 跳过者可见提示 ✅ 已完成

> 作者：「为什么博主管理页面 同步按钮在转圈说明正在同步，但是有些博主下面的进度条没有了、」

- **根因**：进度条唯一存活条件 = 该博主有 `status=running` 的 SyncJob（4s 轮询），而 sync-all 线程池**并发**消费、各博主独立完成即从 running 列表除名 → 先完成者进度条瞬间消失，与整批「还在转圈」矛盾；被 skip 的博主（已在运行/无启用账号）从不建 job，天生没条。
- **做了什么**：
  - **完成不瞬删**：done 停留约 8s 绿条「同步完成」+ 进度 100%；failed 停留约 60s 红条含失败原因摘要；超阈值 `jobFor` 返回 null → AnimatePresence 淡出（收口 opacity 1→0）；历史旧记录（超阈值）打开页面不误显示。
  - **时区修正**：后端时间为无尾缀北京时间（`core/timeutil`），前端 `jobAgeMs` 对无时区尾缀时间串补 `+08:00` 再比较，避免浏览器异时区导致条永不/立即消失。
  - **心跳**：仅当存在窗口期内的 done/failed 条时开 1s 重渲染心跳（每渲染重算、条淡完自动停），空闲零开销。
  - **排队条保持**：入队预置「排队中…」running job（R-163 已有）不回退。
  - **跳过者可见**：`enqueue_all_top15_sync` 的 `skipped` 改结构化 `[{creator_id, name, reason}]`；sync-all 响应落本地 state，博主卡片下渲染灰色虚线提示条「本轮同步跳过：原因」（软入场）；该博主开跑 / 手动重试 / 切换主博主 / 下次 sync-all 覆盖时移除；toast 文案适配。
  - **数据源**：前端 jobsQ 改拉 `/api/platform/jobs?limit=50` 全状态（接口契约不变），`runningCreators` 只统计 running。
- **改动**：后端 `platform_sync.py`（skipped 结构化）、`api/platform.py`（400 detail 拼接适配）；前端 `creators/types.ts`（+SyncSkipped）、`sync-progress-bar.tsx`（done/failed/SyncSkippedBar 三形态）、`creators/index.tsx`（jobs 全状态 + 延迟淡出 + 跳过条）。
- **明确不做**：批次范围不变（仍只当前主博主+对标，R-162 口径）；单博主懒建 job 不动；`/api/platform/jobs` 契约不变。
- **自测**：`scripts/verify.sh` 全绿（ruff + mypy + pytest + 前端 lint/tsc/build + 文档一致性 31 表/146 路由）；`test_r162_sync_all_queue.py` skipped 结构化断言通过。

## [M217 / R-217] 2026-09-30 — 品牌文案精简：登录页去标语 + 界面去「回声」汉字 ✅ 已完成（纯前端，后端零改动）

> 作者：「登陆页的【让 AI 越来越懂你的人设】、【回声】去掉，包括登陆后左上角 【回声】汉字也去掉」

- **做了什么**：界面品牌标识统一为 **`echo` + 图标**，界面上不再出现中文「回声」。
  - 登录页标题 `echo 回声` → **`echo`**；**整行删除标语「让 AI 越来越懂你的人设」**。
  - 登录后左上角（侧栏）`echo 回声` → **`echo`**。
  - 浏览器标签页 `echo · 回声` → **`echo`**。
- **新增/改动**：改 `frontend_v2/src/pages/login.tsx`（标题文案 + 删标语 `<motion.p>`）、
  `frontend_v2/src/components/layout/sidebar.tsx`（品牌文案）、`frontend_v2/index.html`（`<title>`）；
  新点检脚本 `frontend_v2/r217-brand-text.mjs`。**后端零改动**（无新接口/新表/新定时任务/无 LLM 成本）。
- **关键决策（反问结论）**：① 作者确认**只删「回声」两字**，`echo` 与图标 `Waves` 保留（不是整块品牌区删掉）；
  ② 浏览器标签页**一并改**为 `echo`；③ **邮件主题/正文里的品牌文案不动**（`【echo】今日选题与脚本…` / `【echo】今日最佳…` / 失败告警），
  故 `backend/app/services/notify.py` 未改；④ 不动图标/配色/间距/登录鉴权逻辑，不改其它页面文案。
- **动效（R-175）**：删标语后其余入场动画**保持原样**（图标 spring、`h1` 淡入、表单 `y:12`），未引入任何从 `opacity:0` 起步的新动画；未改布局参数。
- **自测**：`scripts/verify.sh` **全绿**（ruff + mypy + pytest + 前端 lint/tsc/build + 文档一致性 31 表/146 路由）；
  headless `r217-brand-text.mjs` 对 **dev(3000) 与生产 dist(8000) 各跑一次全绿**——标签页标题、`h1` 恰为 `echo`、登录页与侧栏均无「回声」/无标语、图标保留、
  **入场确在动（opacity 取值 31–32 种）且落定 `opacity 1 / transform none`**、侧栏折叠不受影响（收起后 64px、品牌字样隐藏，展开回来）；截图肉眼复核通过。
- **明确不做**：不改邮件品牌文案、不改图标与配色、不排查其它页面文案。
- **已知留口**：登录页卡片下方仍有 `echo v2 · 全新界面预览`（`login.tsx:110`）——作者本次未提及，**按要求未动**。

## [M214 / R-214 + R-215] 2026-09-29 — 提词器 + 内置网页录像 ✅ 已完成（全屏提词页里直接录 1080p 口播，后端零改动）

> 作者：「我想要个提词器，让我能很清楚的看着字录视频，眼睛不用乱飘」→「先别做，提词器还需要一个视频录像功能，可以让我直接录视频」→「把没做的需求做了」。

- **做了什么**：草稿抽屉「口播脚本」标题行新增【提词器】（点击时先 `ensureSaved()` 补存当前改动，进页面前保证提词的就是眼前这版）→
  顶层路由 `#/prompter/:draftId` **不进 `AppShell`**（真正全屏、无导航/顶栏，`Esc` 回草稿列表）。同一页里：纯黑暖白大字号提词 + 匀速滚动 + 分段高亮 + 镜像，
  并且可以直接开摄像头录像（`getUserMedia` 取 Ace Pro UVC 1080p + 内置麦），录完内联回放 →【重录】/【下载】/【存入素材库】。
- **新增/改动**：新 `frontend_v2/src/pages/prompter/`（`prompter-text.ts` 纯逻辑 + `recorder.ts` 纯逻辑 + `index.tsx` 页面 + 两个单测共 40 例）；
  改 `src/App.tsx`（顶层路由）、`src/pages/drafts/edit-drawer.tsx`（入口按钮 + 先补存）；新点检脚本 `frontend_v2/r214-prompter.mjs`。**后端零改动**（只读 `GET /api/drafts/{id}` + 既有 `POST /api/videos/upload`）。
- **关键设计（实施时定的）**：
  - **读字基准线 = 屏幕上沿往下「一个行高」**（不是屏幕高度百分比）：首行贴屏幕上沿后作者读的就是最上面那行；固定百分比会出现「一进页面高亮第 3 段、第一段永远轮不到」且换视口/字号就失效。
    现口径下「进页面=第 1 段、滚到底=最后一段、段随滚动单调前进」在任意字号/视口都成立（单测锁死）。
  - **底部占位 = 视口高 − 基准线**，滚动上限再按「最后一段上沿 − 基准线」夹一次 → **停下 = 全部念完**（不是滚过一整屏空白）；稿子短到不用滚时不停表，由作者按空格停。
  - **踩坑**：Chromium 会把小数 `scrollTop` 取整，若每帧从 DOM 读回再累加，13.4px/s 的推进被永久抹成 0（表现：按了播放、计时在走、正文一动不动）。改浮点 ref 记账 + `Math.round` 变化时才写 DOM。
  - 空格语义：未开摄像头时=提词播放/暂停；开摄像头后空闲=开始录制、倒计时/录制中=停止（优先）；倒计时中 `-`/`+` 调秒数，其余时候调字号。
  - 格式协商 `mp4/avc1 → webm/vp9 → webm/vp8 → webm`，状态带**明示实际格式**；MP4 录后校验（读不出有限时长即判 Chrome 已知缺陷）→ **自动退回 WebM** 并提示重录。
  - 预览小窗打开时给正文留右侧 316px 空带（几何点检断言「预览左沿 ≥ 正文右沿」），不压正文。
  - 动效（R-175）：正文区**逐帧零动画**（段高亮只换字色）；控制条 3s 无操作淡出、鼠标/按键唤醒；倒计时数字/REC 红点呼吸/回放面板用 `softIn`，都不从 `opacity:0` 起步。
- **自测**：纯逻辑单测 40 例；headless `r214-prompter.mjs` 对 dev(3000) 与生产 dist(8000) **各跑一次全绿**（含 fake 媒体流「倒计时→录 3s→空格停止→回放时长 3.30s→下载文件名→入库打桩 + Node 直连后端真上传 108MB→DELETE 清理」、正文区 40 帧零动画、rAF 60.5fps、长稿滚动堆增长 0.0MB、抽屉入口直达）；`scripts/verify.sh` 全绿。
- **明确不做**（沿用登记结论）：语音跟读（R-216）、手机/粘贴任意文字入口、云转码/强制 MP4、分段重录拼接、多机位、美颜滤镜、提词页内改稿。**未做**：File System Access 边录边写（规格里是「可选」）。

## [M214 / R-215] 2026-09-29 — （原登记记录，保留）提词器内置网页录像 🔲 已登记（作者决定先不做，与 R-214 合并交付）

> 作者：「先别做，提词器还需要一个视频录像功能，可以让我直接录视频」

- **现状（已核实）**：① 后端**本就吃得下浏览器录像**——`backend/app/api/videos.py:28` 的 `VIDEO_EXTS` 已含 `.webm`，`POST /api/videos/upload` 直接可用，**后端零改动**；② Ace Pro **官方支持连接电脑作为 Webcam（UVC）**，浏览器 `getUserMedia` 免驱取流；③ `MediaRecorder` 在 Chrome 稳定产 **WebM(VP8/VP9+Opus)**，**MP4/h264 有产出损坏文件的已知缺陷** → 以 WebM 为可靠基线。
- **反问结论**：画质选 **1080p 够用、要浏览器直录最快路径**（已看过 Photo Booth 相机模式）；收音**先用笔记本内置麦**（保留设备选择）；文件**直入素材库 + 同时可下载**；控制**3s 倒计时 + 空格开始/停止 + 重录**；**与提词器同页**（不切页）；**后端零改动**；语音跟读顺延 **R-216**。
- **本期规格**：`getUserMedia({video:1920×1080@30, audio:内置麦})` → 3s 倒计时（Esc 跳过）→ `MediaRecorder` 1s `timeslice` 分片，块留内存（可选 File System Access 边录边写）；**格式协商 mp4→vp9→vp8→webm 并明示实际格式**（MP4 录后校验异常自动退回 WebM）；录制中提词自动匀速滚动 + REC 呼吸 + 时长累加，空格=停止（优先于播放/暂停）；录后内联回放 +【重录】/【下载】/【存入素材库】（`uploadFile('/api/videos/upload')`，入库后接既有转写，按 R-033 不自动转写）；超 5 分钟自动停。
- **明示限制**：WebM 在剪映/PR 里不如 MP4 顺（本期不做云转码）；内置麦有房间噪音；画质上限=UVC 输出 1080p。
- **明确不做**：分段重录拼接、多机位、美颜滤镜、云转码、自动发布、提词页内改稿。
- 详细规格与验收清单见 `requirements/R-215-prompter-recorder.md`。

## [M214 / R-214] 2026-09-29 — （原登记记录，保留）录音提词器（全屏提词页）🔲 已登记（作者决定先不做）

> 作者：「我想要个提词器，让我能很清楚的看着字录视频，眼睛不用乱飘」（附现场照片：镜头架在行李箱顶，稿子在镜头后方墙上显示器里，机身挡住文字）。

- **根因（照片 + 全仓检索）**：仓库内**无任何提词器代码**；现场问题是**镜头与提词屏不同向**（屏在镜头后约 1 米、偏高，被行李箱/机身遮挡）——看镜头看不到字、看字眼睛下垂 → 必然乱飘。作者确认可把笔记本摆到**镜头正下方**，因此方案按「笔记本全屏提词」设计。
- **反问结论**：稿子直接用草稿 `script`（一键进入）；**只读不回写**；控制项全选但**范围取「先做能立刻用的最小版」** → **语音跟读明确排 R-215**；本期**纯前端零云服务、后端零改动**（复用 `GET /api/drafts/{id}`）。
- **本期范围（M214）**：顶层路由 `#/prompter/:draftId`（不进 `AppShell`，无导航/顶栏）；纯黑底暖白大字号（默认约 56px/28–120）+ 行距 1.4–2.4，**首行贴屏幕上沿**；`rAF` 恒速滚动 + 快捷键（空格/↑↓/±/`[`/`]`/`M`/`R`/`Esc`）；按空行分段 + 当前段高亮（只换字色、无位移动画）；镜像 `scaleX(-1)`；已录时长 + 中文约 4 字/秒预估剩余；设置持久化 `localStorage`；控制条 3s 无操作淡出（正文区零动画，R-175）。
- **明确不做**：语音跟读（R-215）、手机/粘贴文字入口、提词页内改稿、任何后端改动。
- 详细规格与验收清单见 `requirements/R-214-teleprompter.md`。

## [M205 / R-213] 2026-09-29 — 断网兜底：草稿「本地暂存 + 自动重试 + 恢复提示」

> 作者：「如果我断网了呢，现在是检测改动就保存吗？」

- **修复前实测**（Playwright 拦住 `/api/drafts` 写请求）：断网后打字 → 状态位报失败；**停手 5s 0 次重试**；断网期间关抽屉 → 服务端没有、localStorage 也没有任何副本 → **内容真丢**；网络恢复后继续打字才自愈（每次发的是完整内容）。
- **改法**（纯前端，后端零改动）：
  - 新 `pages/drafts/local-copy.ts`：一份「还没同步到服务器」的 localStorage 副本（内容 + 时间 + 草稿 id），读写都不抛，脏数据读成 `null`。
  - `autosave.ts`：`schedule()` **先写本地副本再排防抖**；`pending`（最新未确认内容）在服务器确认落库且没有更新内容时才 `storage.clear()`；**失败分类**——`4xx` 直接 `'error'` 不重试，网络/5xx 转 `'offline'` 并按 `1s→2s→…→30s` 退避重试（重试读 `pending`，**抽屉关了也继续补存**）；新增 `retryNow()`（`window online` 立刻补）与 `flush()`；`dispose()` **不清副本**（刷新后仍可恢复）。
  - `edit-drawer.tsx`：打开抽屉读一次副本，**只在「副本 id 与当前稿匹配」时**在表单上方弹提示条（`data-testid="draft-local-copy"`，`softIn` 起步 0.85）——【恢复】回填、【丢弃】删副本，**不静默覆盖**服务端内容；状态位新增离线态「连不上服务器，已本地暂存（重试 N）」。
- **测试**：`autosave.test.ts` 扩到 18 例（新增：先落本地/成功才清/退避 1-2-4s/4xx 不重试/`retryNow` 立刻补/断网关抽屉后仍用「关那一刻」的内容补存/`dispose` 不清副本/改回服务器已有版本不留无用副本）；新 `local-copy.test.ts` 3 例（往返、清空、坏 JSON 与字段类型降级）。
- **自测**：verify 全绿；真实链路 `r213-offline.mjs` 全绿（断网打字 → `offline` + 副本 + 停手仍在退避重试 → 关抽屉不丢 → 刷新后提示条恢复内容 → 联网补存成功且副本清掉）；R-212 点检复跑无回归。

## [M204 / R-212] 2026-09-29 — 新建草稿实时保存（修「点到抽屉外面，写的东西全没了」）

> 作者：「我新建草稿打了一堆字，不小心点了其他地方导致抽屉关了，写的东西就没了，当我新建草稿做了任何变动都应该实时保存」

- **根因**：新建草稿的内容原先**只在内存里**——`pages/drafts/index.tsx#createDraft()` 只 `setEditState({...EMPTY_DRAFT})`（`draft=null`），整篇内容要等点【保存】才 `POST`；而抽屉的遮罩点击 / 右上角 X / Esc 都走 `onClose() → setEditState(null)`，服务端根本没有这条记录，内容随之丢弃且不可恢复。
- **改法**：新增 `pages/drafts/autosave.ts`（不含 React/DOM 的纯逻辑）+ 抽屉接线。
  - 只对「本次由【新建草稿】进入」的会话启用（会话内持续有效）；**打开已有草稿仍保持【保存】/【取消】语义不变**（按作者选择的最小范围）。
  - 任何一处变动（标题/封面字/正文/关联素材/标签/发布信息）→ 防抖 900ms 落库：首次 `POST /api/drafts`（沿用 R-154「全空不建稿」），拿到 id 后 `PATCH`；内容指纹相同不重复写。
  - **单飞 + 队列串行**：保存进行中又有改动则排队，当前这次完成后继续写最新内容——否则保存期间敲的字会被漏掉（回归用例已锁）。
  - **关抽屉瞬间补一次**：遮罩 / X / Esc /【关闭】都先 `closeOut()` 再关，防抖窗口里最后几个字也不丢。【保存】成功与讨论回填的服务端内容用 `markSaved()` 记账，避免重复 PATCH。
  - **空稿自动删除**：自动建出的稿若被清空 → 关闭时回调 `onDiscard(id)`，页面先乐观移除列表行再 `PATCH {status:'deleted'}`（与卡片【删除】同口径），不留「（无标题）」垃圾卡片。
  - 组件跨抽屉会话常驻挂载（R-205 的延迟卸载）→ 每次打开必须 `saver.reset()`，否则会复用上一轮的 id 把内容写到上一张稿上。
- **动效（R-175/R-202）**：底部常驻状态位 `data-testid="draft-autosave"`：`保存中…`（spinner）→ `已自动保存 HH:MM`（云勾）/ `自动保存失败，点【保存】重试`；用 `softIn`（`0.85→1` + y 3，**不从 opacity 0 起步**），收口 `opacity 1 / transform none`。自动保存会话里【取消】改称【关闭】（内容已保存，不存在"取消掉不存"）。
- **测试**：`autosave.test.ts` 11 例（空白不建稿 / 防抖合并成一次且落最后内容 / 建后改走 PATCH 不重复建 / **在飞期间继续输入不漏字** / 关抽屉立刻补存 / 清空后关闭丢弃 / `markSaved` 后不重复写 / `reset` 隔离上一轮 id）；`fmtTime` 复用。
- **自测**：verify 全绿（lint + tsc + vitest + build + 文档一致性 31 表/146 路由）；headless 真实链路：新建 → 打字 → 点遮罩关闭 → 重开内容还在；清空后关闭列表无空卡片；状态位动效无空白闪帧。

## [M198–M202 / R-208] 2026-09-29 — 自动化加固与系统瘦身（去审批化，聚焦「话题+文案」核心）

> 作者：「我不想经常上系统这里需要我审批那里需要我审批，我需要它提供符合我这个博主人设的话题，和大概的文案，这是最核心的」。

- **M198 人设建议高置信自动确认 ✅**：`persist_suggestions` 内对「非禁区层 + 命中素材 ≥3 篇 + 与作者已拒绝标签不冲突」的建议直接 `status=confirmed`（`confirm_strength=1`，区别于手动=3/人工确认=2），红线层永远人工、被拒过的不再自动确认；每次自动确认写站内通知（kind=`persona_auto_confirm`，附标签名，可一键回滚）。存量积压：新增 `persona_auto_confirm_backlog_task` + 启动时一次性触发（Kv `persona_auto_confirm_backlog_v1` 保证只跑一次），用逐篇提取结果重算频次后按同规则批量处理（内容缓存命中零 LLM）。人设页已确认项加「自动」徽标 + 「撤销」按钮。
- **M199 提示词优化后台全自动 ✅**：`maybe_notify_prompt_refresh`（只发提醒）→ `maybe_auto_optimize_prompt`（素材到量自动排队 `generation` 优化，样本不足静默跳过）；`prompt_eval_task` 评测后「候选 ≥ 当前版 ×1.10」自动启用 + 通知（附变更说明与「可回滚到 vN」），不更好则静默丢弃（候选转 rejected、不打扰），当前版无可比评分时保留候选待人工；删除 `weekly_prompt_hint` 定时任务。
- **M200 每日「今日最佳」推送 ✅**：流水线收尾新增 `push_daily_best`——AI 从当天已生成的稿子里按「人设契合 × 热度」选 1 篇（失败退回分数最高），站内通知（kind=`daily_best`，正文含选题理由 + **完整口播稿**）+ best-effort 邮件单篇推送（复用 digest 模板）；同一天 Kv 标记只推一次，推送失败不影响流水线。
- **M201 AI 设置瘦身 + 对话写操作白名单 ✅**：AI 设置页 10 tab 收为「基础」（模型/Key/生成方评审方/ASR/每日篇数/讨论轮次 + 保存）+「高级」（推理预算/兼容性自检/一键优化规则型/功能提示词改 Select 切换 + 版本评测）；AI 对话写操作 `agent_actions.propose` 新增 `SAFE_ACTIONS`（`generate_draft` / `rework_draft` / 可逆的 `set_draft_status`）**免确认自动执行**（审计照记 done + preview/result），删除等危险操作仍 `pending` 等确认；`TOOL_DATA_RULES` 与 dispatch 同步区分 executed/pending。
- **M202 遗留清理 + 老前端下线 ✅**：删除真死代码 `core/review.py`（复盘启发式兜底，仅测试引用）与 `core/metrics.normalize_snapshot`（无人调用）；老前端 `frontend/` 目录**删除**，`verify.sh` 去其构建、`main.py` 根路径改挂 `frontend_v2/dist`、vite `base` 改 `/`、Dockerfile/.dockerignore/AGENTS/README/QUICKSTART/ARCHITECTURE/API 同步。**核实澄清**：`metrics_snapshots` 并非死代码——它是平台数据聚合的性能缓存，生成权重/人设金句/提示词样本/赛道雷达在读它，原作者拍板保留。

## [M203 / R-209+R-210+R-211] 2026-09-29 — 回退留痕与版本链归因 + 纯手写标签 + 反馈体系重构

> 作者：「我手动创建了1篇草稿 点击了定稿，讨论出来的结果不如我原稿，于是我回退到了原稿，这个时候我点击采用、或者快速反馈好，他会认为是ai讨论出来的结果是好的吗，但实际我只是采用了原稿，如何让ai识别呢」

- **R-209 根因**：版本链不区分「谁改的」+ 回退不留痕（R-157）→ 差异分析把 AI 讨论的改动当成作者偏好学进人设建议；改稿样本 few-shot 把「讨论后」当「作者改后」且好评后 5 分排最前——归因彻底反了，且污染在讨论完成那一刻就发生。
- **R-209 改法**：① 版本 `source` 分**作者侧** `{manual, rollback}` / **AI 侧** `{ai_generate, ai_discuss, ai_rewrite}`；② 回退**留一版**（`source="rollback"`，note「回退到版本 #N」，**推翻 R-157**）；③ 差异分析 `analyzable` 门控（终版须作者侧、链须含 AI 侧）+ prompt 按 source 标注每版身份与归因规则；④ 改稿样本配对 = 「最后一个作者侧版本 ← 其前一版」（被回退的讨论稿变成最准的反面教材）；⑤ 回退跨过 AI 版时讨论运行头回填 `reverted: true` + 生成上下文注入「作者改回了自己的原稿」反面信号（`_reverted_lessons`，≤3 条）。
- **R-210 纯手写**：`pure_manual` 判定（source=manual 且无讨论记录且无 AI 侧版本；讨论过即使回退也不算）；列表接口批量判定（无 N+1）；卡片右上角「纯手写」标；纯手写链不做差异分析（手写稿只学正文）。
- **R-211 反馈体系重构**（作者：「打分、钩子、节奏、结尾、像我这些都去掉，改成一个文本框」「触发时机改成不采用、待制作点击完成」「纯人工写的点击不采用不触发学习」「历史评分弃用」）：
  - 前端删：星级打分、四维细分（钩子/节奏/结尾/像我）、快速反馈好/差；「记反馈」改为行内展开 textarea（预填已写评价，展开/收起有动效）。
  - 触发：`PATCH /drafts/{id}` 进 `done`（好）/ `archived`（差，纯手写豁免）→ 后台 `feedback_analysis` 任务：LLM 分析「正文 + 带归因版本链 + 评价文本」为什么好/差 → 心得落 `feedback.insight`（新列，幂等迁移）；卡片状态条「学习分析中」（`draft_status` kind=`feedback`，R-202 切页恢复）；失败留「中断」标记不阻塞状态流转。
  - 学习通道全部改 **status 驱动**（历史 rating/liked/四维分弃用）：黄金样本/结构模板/`feedback_context`/prompt_eval 高低分稿认可=done、否定=archived 非纯手写；`feedback_context` 每条附作者亲笔评价 + 复盘心得；废稿恢复后负向自然消失（status 即事实源）；`version_effect` 认可口径同步；`_dim_examples`（四维回流）删除。
- **排查顺手发现的死信号**（重构前事实）：快速反馈「差」（liked=False）没有任何学习通道消费；记反馈文字留言（comment）只存库没人读——本次一并激活。
- **测试**：新增 `test_r209/210/211` 三文件 25 例（回退留痕/reverted 回填/配对归因/反面信号/纯手写边界/触发节点/心得落库/status 驱动上下文）；更新 R-129/130/135/156/157 受口径影响的旧用例；前端 `draft-ai-status` 测试补「学习分析中断」用例。

## [M197 / R-207] 2026-09-29 — 硬自检只留红线；口癖/高频词覆盖率仅诊断

> 作者：「高频词、口癖覆盖率这类硬自检：可做诊断，但不该强制重写。否则会逼模型机械塞口头禅，变成模仿腔」。

- **问题**：`_self_check` 把「口癖覆盖率==0 / 用了 AI 腔词」也当硬问题，`run_debate` 只要 `issues` 非空就强制生成方**整篇重写一次** → 模型为过自检机械塞口头禅，产出「模仿腔」。
- **改**：`generation._self_check` 只保留**红线**为硬问题；新增 `style_diagnostics`（口癖/高频词覆盖率 + 命中/未命中 + AI 腔词命中）**只诊断**；`run_debate` 仅在命中红线时收口重写，重写提示去掉「必须模仿」块；`Draft.quality` 增 `diagnostics`。
- **提示词软化**：`author_style_context` 的「作者语言习惯（必须模仿）」→「自然贴近即可，不要硬塞口头禅/标志词」，范本措辞改为「体会语气、不要照搬词句」。
- **前端**：草稿**讨论 tab** 加「生成自检」区块（红线/像作者覆盖率 + 命中口癖绿标/未命中灰标 + AI 腔词）；草稿**卡片**加「像作者 NN%」微标（诊断）+「踩红线」告警（仅 `passed=false` 且非 mock）。
- **测试**：新增「无红线 → 不触发收口重写（计数 0）」「红线 → 重写 1 次」「AI 腔词/覆盖率 0 只进 diagnostics」用例；`scripts/verify.sh` 全绿。

## [M196 / R-206] 2026-09-29 — 抽屉「讨论（双模型留痕）」tab 动效修复

> 作者：「草稿页面的双模型讨论的动画很不错，为什么抽屉里面『讨论（双模型留痕）』tab 页里面的动画经常不动」。

- **根因（无头数值探针 `frontend_v2/r206-discuss-tab-motion.mjs` 实测三条独立原因）**：
  ① 列表外层 `AnimatePresence initial={false}` 把「切进 tab 时已经在的那批留痕」的入场动画吃掉了（110 帧有留痕、**0 帧在动**）；
  ② 讨论中新留痕的入场动画**播在屏幕外**——滚动区不跟随最新，`scrollTop` 恒 0、内容 3615px / 视口 494px，新行在可视区下方 3667~3730px（同 R-199 那类坑）；
  ③ 状态条 `key={state + note}` 让讨论每换一步就整条重挂，配上 `initial={{opacity:0, height:0}}` → 三点节点被替换、旧条高度收 0、新条从全透明长出（8s 4 次重挂、34 帧两条并存）。
- **修**：① 去 `initial={false}`，改首屏前 6 条 `delay = min(i,5)×0.03` 轻 stagger（仍从 `0.85 + y10` 起步）；
  ② `ui/scroll-area.tsx` 新增可选 `viewportRef`（真正的滚动元素是 Radix Viewport）；新增 `pages/drafts/discuss-follow.ts`（`isNearBottom` 24px 阈值 / `countNewRows` / `maxRowId` + 6 例单测）——贴底自动跟随，翻历史时浮出可点「N 条新留痕 ↓」（钉在滚动区右上角：`DrawerBody` 自身可滚，钉底部会被裁一半）；切进 tab 且讨论在跑时先 `behavior:'auto'` 落到底；
  ③ 状态条 `key` 只跟 `debate.state`，入场改 `opacity 0.85 / y-4`、去掉高度动画。
- **实现坑**：本项目 Radix `TabsContent` 比这一层晚一个 commit 才挂内容，`[tab]` 的 effect 里 `ref.current` 与 DOM 都还是 `null`（之后不再重跑）→ 滚动监听改用**回调 ref**。
- **实测**：探针全绿（入场 21 动画帧 / 首帧 0.85 / 落定 `1 none`；8s 内状态条 0 重挂、0 节点替换、0 双条；新留痕自动进可视区；翻历史 `scrollTop` 13 不被抢、提示「2 条新留痕 ↓」点击后落到底且提示消失）。
- **第二轮（作者反馈「还是一样的没有动画，从编辑 tab 手动切到讨论 tab 就没有动画」）**：
  ① **真凶之一**：作者用的是后端托管的 `/v2` 生产包，而页面加载的入口 `index-DN48QJlf.js` **在新 dist 里已不存在**——
  SPA 不会自己重新拉包，所以改动根本没生效（已重新 `vite build`）；
  ② **入场确实太轻**：第一版单条 `softIn`（0.85→1 + y 10，0.24s）逐帧截图确认「肉眼分辨不出」→ 改回标准列表令牌
  `listVariants` + `itemVariants`（0→1 + y 14，0.34s，stagger 0.045），与草稿页卡片墙同一套观感（40 个动画帧、32 帧在淡入；
  点下去 55ms 整列还在淡入、188ms 落定）；
  ③ 受控 `Tabs` 带来的行为差异：关闭抽屉时显式把 tab 复位回「编辑」。
### 第三轮：三点跳动「依旧没有动画」的真凶（同日）
- 作者：「【双模型讨论…正在评审第 2/3 轮…】前面那三个跳动小点 依旧没有动画」。
- **根因**：抽屉讨论 tab 的状态条外层是 `<AnimatePresence initial={false}>`，它把子组件 `initial` 置为 false；
  对 `ThinkingDots` 的**关键帧数组**（`opacity:[0.25,1,0.25]` + `y:[0,-2,0]`，`repeat: Infinity`）framer 只把样式停到
  第一帧就不再推进。`/v2` 生产包实测：**98 帧里 transform / opacity 各只有 1 种取值、`getAnimations()` 为空**
  （`opacity` 恒 0.25）；同一组件在草稿页卡片上（没有那层 Presence）有 87/109 帧在动。给点补显式 `initial` **兜不住**（实测仍冻）。
- **修**：① 去掉状态条那层 `initial={false}`（顺带让状态条自己的入场动画生效）；② `ThinkingDots` 改成**纯 CSS 关键帧**
  （`index.css` 的 `@keyframes thinking-dot` + `.thinking-dot`，参数与原 framer 版一致：0.9s / ease-in-out / 0.15s 错峰），
  「在跑」的唯一可见证据不再依赖调用方的 framer 上下文（R-202）。
- **实测**：`/v2` 上草稿页卡片 92 帧 / 抽屉 78 帧均有不同 transform+opacity；讨论 tab 探针仍全绿。


## [M195 / R-205] 2026-09-29 — 抽屉/移动端导航/通知弹层退出动画

> 作者：「现在抽屉没有退出动画，通知展开后退出也没有动画」。

- **根因（无头逐帧实测）**：① 抽屉消费方 `videos/edit-drawer.tsx`、`drafts/edit-drawer.tsx` 有 `if (!open) return null`，关闭时**先卸载**了 `<Drawer>`，退场动画没机会播；② 抽屉/移动端导航的退场依赖 framer `AnimatePresence`，本项目 React 19 + framer-motion v12 下其 exit 不触发；③ 通知弹层只有 `animate-in`、缺 `animate-out`。
- **修**：`Drawer` 与移动端导航改「受控 `animate` + 关闭后保留挂载、约 340ms 再卸载」；删掉两个 `edit-drawer` 的 `if (!open) return null`；通知弹层、全局「进行中」弹层、下拉/选择/多选补 `data-[state=closed]:animate-out fade-out-0 zoom-out-95`。
- **实测**：抽屉面板 `x 760→941→1151→1427` 右滑出屏后卸载；移动端导航 `x 0→-147→-276` 左滑出屏；通知 `opacity 1→0.65→0.15→0.01→卸载`（`animationName=exit`）。build + vitest 52 例 + verify 全绿。

## [M194 / R-204] 2026-09-29 — tab 选中态滑块过渡动画

> 作者：「tab页签切换，选中的tab页没有过度动画」。

- `frontend_v2/src/components/ui/tabs.tsx`：新增 `TabsCtx`（当前 value + 每个 Tabs 实例的 `useId`），`Tabs` 兼容受控/非受控；`TabsTrigger` 选中时渲染共享 `layoutId` 的 `motion.span` 滑块（spring stiffness 420/damping 34），在 tab 间平滑移动；去掉原来瞬间切换的 `data-[state=active]:bg-card/shadow-sm`，文案色过渡保留。
- 全站所有 `Tabs` 生效（AI 设置/脚本工作台/抽屉/主页灵感池等）。
- headless 实测：10 tab 切换滑块 `x 280 →（动画中 345）→ 457` 与选中项对齐、始终仅 1 个滑块、零 JS 报错。

## [M193 / R-203] 2026-09-29 — AI 设置 tab 栏改为自动换行

> 作者：「ai设置功能里面的tab页太多了，一页都放不下了，换行」。

- `frontend_v2/src/pages/prompts/index.tsx`：去掉包 tab 栏的横向 `ScrollArea`，`TabsList` 加 `h-auto w-full flex-wrap justify-start` → 放不下自动换行。
- headless 实测：10 个 tab 自动换 2 行，`scrollWidth == clientWidth`（无横向溢出），零 JS 报错；tab 切换入场动效不变。

## [M191/M192 / R-202] 2026-09-29 — 非实时结果必须有进行中动效（切页/刷新可恢复）

> 作者：「页面上很多功能调用接口都在后台计算，但我切换页面回来，发现前端没有动画了，但实际上还没执行完，会让人误解已经执行完了」。
> 「所有非实时返回的结果，该有的动画都需要有，保持动画美观流畅，不然容易误导用户」。

- **规范固化（先做）**：把该要求写进 `AGENTS.md`（工程标准 + 反问清单第10项）、`docs/DECISIONS.md D-042`；**不满足 = 功能不算完成**。
- **根因**：前端多数「进行中」用组件本地 `useState`，切页卸载即丢；部分页面（博主对标）挂载时查了 running 任务却 `void` 丢弃；同步长接口（内容机会/角度/转写补齐/单键优化）切页后结果还会丢。
- **方案**：`background_tasks` 为唯一事实源；前端全局 `ActiveWorkProvider`（挂载回扫 + SSE `task.update` 实时 + 10s 轮询兜底）+ 顶栏「进行中 N」指示器；8 个同步慢接口转后台任务，结果落 `task.result` 回填。
- **后端**：`core/task_meta.py`（`KIND_LABELS`/`target`，列表与通知共用）；`TaskOut` 增 `label/target`；`/api/tasks` 支持多状态（running+pending 按 created_at 正序）；SSE `task.update` 带 `kind/label/target`；`find_running_task` 同 scope 去重。转换：`benchmark_prepare`/`opportunity_clusters`/`opportunity_weekly`/`opportunity_gap`/`draft_angles`/`prompt_optimize`/`hot_refresh`/`publish_backfill`（快读接口保持同步）。
- **前端**：`hooks/use-active-work.tsx`（Provider + `useActiveWork/useActiveTask`）、`components/layout/active-work-indicator.tsx`（顶栏指示器，`softIn` 入场）、`hooks/use-task-scope.ts`（task_id 存 sessionStorage，切页/刷新恢复并回填结果）、`api/task.ts`；对标/AI设置/人设/灵感随手记接任务态；主页 4 个内容机会 + 抓取 + 回填改任务。
- **自测**：headless 实测点「观众提问榜」→按钮转圈+顶栏「进行中 1」→切到人设页仍「进行中 1」→回主页仍禁用→完成后指示器消失、按钮恢复、**结果自动回填**；整页刷新后指示器仍恢复。`scripts/verify.sh` 全绿（后端 445 例）。

## [M190 / R-201] 2026-09-29 — 主页「内容机会」移到「灵感池」上方

> 作者：「主页的内容机会放到灵感池上面」。

- `frontend_v2/src/pages/home.tsx`：把「内容机会」`<motion.section>` 整块移到「灵感池」之前（仅调整上下顺序，内容/接口/懒加载不变）；入场顺序沿用 `itemVariants`，首屏先见内容机会。
- verify 全绿；headless 点检卡片顺序正确、零 console 报错。

## [M189 / R-200] 2026-09-29 — 接入腾讯云 ASR（录音文件识别）

> 作者：「https://cloud.tencent.com/document/product/1093/52554 接入腾讯ASR」。

- **通道**：`ECHO_ASR_MODE` 扩为 `mock|aliyun|siliconflow|tencent`（白名单护栏不变，**保留四家、不换默认**）；新增 `services/tencent_asr.py` 走腾讯云录音文件识别 `CreateRecTask` + `DescribeTaskStatus`（官方模块化 SDK `tencentcloud-sdk-python-asr`，域名 `asr.tencentcloudapi.com`）。
- **提交方式（作者定）**：本地音频 **base64 直传**（`SourceType=1`）——自包含、不依赖阿里云 OSS/腾讯 COS；新增 `media_tools.extract_audio_compact` 把视频/超限音频抽/压成 16k 单声道 mp3（码率按目标 5MB **自适应** 16–32kbps，纯音频已达标则原样直传），超 5MB 明确报错走失败通知、**不自动切换其它服务商**（同 R-108 口径）。
- **引擎可选（作者定，默认大模型2.0）**：`16k_zh_en_2.0 | 16k_zh_en | 16k_zh`；`model_settings` 增 `ASR_TENCENT_MODELS` 与「切服务商不沿用上一家模型名」的 mode 感知默认/校验；`GET/PUT /api/settings/models` 的 `asr` 增加 `tencent_models`。
- **记录**：`ingest` 为腾讯落 `asr_provider=tencent`、`asr_model=引擎`（原来只有硅基流动落模型）；不新增表/列。
- **密钥**：`ECHO_TENCENT_ASR_SECRET_ID/SECRET_KEY/REGION/ENGINE_MODEL` 只放 `.env`（界面只选服务商）。
- **顺带修 bug**：设置页模型 API Key 保存无效——前端提交的是 `api_key`、后端 `SlotIn` 只认 `key`，且加载时恒置空 → Key 永远存不进 DB（静默回退 .env）。改为加载回显 `models.modelN.key`、提交 `key`。
- **前端**：AI 设置服务商增「腾讯云」，腾讯/硅基流动各自引擎下拉（切换带统一动效 `softIn`）；编辑页 ASR 来源显示「腾讯云」。
- **测试**：新增 `tests/test_tencent_asr.py` 15 例（缺密钥/提交参数与 base64/引擎覆盖/视频抽轨清理/轮询成功去时间戳/失败/超时/无分段回退/压缩直传与超限/路由/模型设置校验）；`scripts/verify.sh` 全绿（后端 441 例 + 前端 lint/vitest/build）。
- **真实联调（已通过）**：`.env` 配好 SecretId/SecretKey 后，本地合成 18s 中文口播 mp4 → `TencentAsr(16k_zh_en_2.0)` 全链路（抽/压音轨 → base64 直传 → 轮询）**16.1s 返回、78 字准确转写**；未改动作者 app_kv 默认，服务商在「AI 设置」自行切换。

## [M188 / R-199] 2026-09-28 — 素材库换批卡动画（真凶：popLayout 量不到卡片 ref）

> 作者①：「切换博主查询的时候……查询出来的结果卡片没有动画」。
> 作者②：「不对……老卡片清掉 这个有动画没了，保留之前的老动画」。
> 作者③：「能不能用【旧卡退场】动画，做个相反的新卡进场动画」。
> 作者④：「入场动画一点都不明显」。

- **真凶（第四轮定位）**：`AnimatePresence mode="popLayout"` 靠把 ref 挂到每个子元素、量出盒子后用
  `position: absolute !important` 把退场元素弹出文档流；`MaterialCard` 是 `memo(function …)` **没有 forwardRef** →
  framer 量到 0 → 退场卡**留在流里**占着前 5 行 → 新卡被挤到第 6–10 行（**屏幕外**）去播入场动画，等退场节点移除才「啪」地弹回可视区。
  实测：网格高度 2367 → **4565**（翻倍，页面跳）；修后 → 2196（稳定），新卡回到 `y≈297` 的可视区里播动画。
  ⇒ 从 R-179 起「换批入场」一直是屏幕外演出，前三轮反馈都不是参数问题。
- 修：`MaterialCard` 改 `forwardRef` 并透传到根 `motion.div`，外层保留 `memo`；加回归单测（断言 `ref.current` 是 HTMLElement）。
- 手感：进场 = 退场倒放（显影 + 长大）但**放慢 + 加过冲**：`fromScale 0.8`、`duration 0.5`、`ease 'backOut'`
  （中段冲过 1 再落回，整段都看得见）；错峰沿用退场的 35ms/张、逐格交接。
  退场保持换批前的原值（0.35s + 0.94 + index×0.035，单测锁死）。
  > 用 CDP screencast（真合成帧）回放定位到：spring 版入场 150ms 就落定、前面还有 ~200ms 空网格 → 人眼像「没有动画」。
  > 另确认代码里没有 `MotionConfig`/`reducedMotion`（framer 默认 `never`），排除系统「减弱动效」吃掉 transform。
- 顺带修真 bug：查询 key 原用未生效的 `filters.creatorId`，只切博主下拉会发一次无 `creator_id` 的空请求并把旧数据写进新 key 的缓存；现 key 只用 `applied`（= 请求参数）。
- 实测（真实数据，零 console 错误）：清场（退场卡 `ABS` + 淡出缩小）→ 屏内 0 张的一拍 → 新卡在可视区 `op 0.9/sc 0.95 → op 1.0/sc 1.03（回弹）→ sc 1.00` 落定。
- 单测 `lib/motion.test.ts` 5 例 + `material-card.test.tsx` 4 例（含 ref 回归）；`scripts/verify.sh` 全绿。

## [M187 / R-198] 2026-09-28 — 素材库筛选下拉默认态修正

> 作者：「素材库广告搜索条件里面为什么是默认『广告』二字，很容易误解啊……改成是否广告、发布状态」。

- 根因：筛选项的「全部」项文案被写成了字段名（`<SelectItem value="all">广告</SelectItem>`），而 Radix `SelectValue` 只要 `value` 非空就按正常前景色渲染选中项文字 → 默认（不筛选）态看起来跟真的筛了「仅广告」一样。
- 新增 `frontend_v2/src/components/ui/filter-value.tsx`：默认态＝字段名 + `text-muted-foreground`，选中具体值才恢复正常前景色与该值文案。
- 素材库工具栏 4 个下拉接入（博主/发布状态/有无视频/是否广告），文案统一为字段名，下拉内保留「全部」项取消筛选；动效不变。
- 单测 `components/ui/filter-value.test.tsx` 3 例；`frontend_v2` tsc/eslint/vitest（43 例）全绿；`scripts/verify.sh` 全绿。

## [M183~M186 / R-194~R-197] 2026-09-28 — 洗稿主链路/来源分层/立场提词/历史回填

> 采纳外部评审的三处修正 + 历史回填。

- **R-194 对标洗稿主链路**：`run_rewrite_debate` 改注入完整 `author_style_context`，初稿统一为「参考改写」契约（去掉“保留核心信息与结构”），评审/修订也带完整作者上下文。
- **R-195 内容机会有来源地合并**：聚类区分 mine/industry/external 三层（自己的观众 / 多对标共性 / 单对标外部），带来源博主数与权重；每日生成只用自己的评论、每周灵感包纳入对标。
- **R-196 匹配接入内容立场**：热点/评论相关度关键词增加 stance 层全文提词；红线剔除取 forbidden 层。
- **R-197 历史发布自动关联+回填**：`drafts.work_id` + 按标题相似度 ≥0.8 关联 works（preview/apply/revert，可撤销），表现可按作品聚合，让归因有历史数据。
- 测试 `tests/test_r194_r197_persona_rewrite_opportunity.py`；`scripts/verify.sh` 全绿（31 表 / 145 路由）。

## [M182 / R-193] 2026-09-28 — 时间线从主页移到博主管理页顶部

> 作者：主页的时间线移除，放到博主管理页面的最上面。

- 抽成复用组件 `components/timeline-card.tsx`（本地素材 + 云端作品发布轨迹，交互不变：点视频跳素材库编辑、点作品跳素材库）。
- 主页移除时间线卡片及相关查询/未用导入；博主管理页顶部渲染时间线。
- `scripts/verify.sh` 全绿。

## [M181 / R-192] 2026-09-28 — 内容机会进 AI 对话 + 选题归因 + 模型1 语义聚类

> 承接 R-185/R-187：把内容机会接进对话、接进历史表现、把聚类升级为语义。

- **AI 对话工具** `get_content_opportunities`：一次返回观众提问榜 / 每周灵感包 / 缺口选题。
- **选题归因**：按 `drafts.tags` 聚合已发布稿件表现 → `GET /api/opportunities/attribution`；命中「好标签」的每周灵感 **+15** 加权；主页「看表现归因」。
- **模型1 语义聚类**：`/api/opportunities/comments?use_llm=true`（默认）用模型1 把评论（≤60 条）归并成规范问题；硬超时 100s、缓存 6h、每周任务预热；失败/超时回退本地聚类（DeepSeek 无 `/embeddings`，故用 LLM 语义归并，不新增供应商）。
- 测试 `tests/test_r192_opportunities_in_chat_and_attr.py`；`scripts/verify.sh` 全绿（31 表 / 142 路由）。

## [M178~M180 / R-189~R-191] 2026-09-28 — 发布回填 + 聚类增强 + 账本 UI

> 承接 R-180~R-188 的收尾打磨。

- **R-189 发布后表现定时自动回填**：`drafts.performance` + `services/draft_performance.refresh_published_performance` + 每日 05:00 任务；草稿卡片显示播放/赞/藏/评。
- **R-190 评论聚类本地增强**：过滤纯赞美/无信息评论；相似度改 `max(bigram Jaccard, SequenceMatcher)`；`total_comments` 口径修正（真实总数 + scanned）。
- **R-191 选题账本 UI 化**：轻量 `GET /api/opportunities/covered` + 主页灵感条目标「可能已讲」。
- 测试 `tests/test_r189_publish_backfill.py` 等；`scripts/verify.sh` 全绿。

## [M177 / R-188] 2026-09-28 — 每周灵感补给定时推送

> 承接 R-185/R-187：让系统主动把灵感推给作者，而不是等作者来点。

- `services/opportunity.digest_message`：缺口 + 每周灵感包拼成可推送文案（缺口优先，纯逻辑可测）。
- `scheduler._weekly_ideas_job`：每周一 08:30 生成并推送站内通知（深链 `/home`）+ best-effort 邮件；失败写告警；无内容不打扰。
- 测试 `tests/test_r188_weekly_ideas.py`；`scripts/verify.sh` 全绿。

## [M176 / R-187] 2026-09-28 — 内容机会·缺口选题（AI 补位）

> 承接 R-185：统计路（评论/热榜）之外，补 AI「该讲但没讲过」这一路（R-030⑥）。

- `services/opportunity.gap_suggestions`：组装「已确认人设 + 最近已讲话题 + 近期热点」→ AI 产出选题（避开重复）+ 理由；AI 不可用返回空 + note，不报错。
- `GET /api/opportunities/gap`（120s 缓存）；主页「内容机会」卡新增「找缺口选题」按钮 + 列表一键生成。
- 测试 `tests/test_r187_gap.py`；`scripts/verify.sh` 全绿。

## [M175 / R-186] 2026-09-28 — 灵感随手记（移动端）

> 规划落地（内容经营闭环 R-180~R-186 收尾）：刷到灵感/亲身经历随手记，一键发展成选题草稿。

- 新表 `inspiration_notes`；`services/inspiration.refine_topic` 把随手记提炼成选题标题（LLM 不可用则原样返回）。
- API：`GET/POST /api/inspiration`、`POST /api/inspiration/{id}/develop`（提炼→入队生成）、`DELETE`。
- 前端新增「灵感随手记」页（响应式）+ 侧栏/路由/标题；一键生成后跳脚本工作台。
- 测试 `tests/test_r186_inspiration.py`；`scripts/verify.sh` 全绿（31 表 / 139 路由）。

## [M174 / R-185] 2026-09-28 — 内容机会引擎：评论聚类 + 每周灵感包 + 选题账本

> 规划落地（内容经营闭环 R-180~R-186）——直接回应「越做越没灵感」的初心。

- 新增 `services/opportunity.py`（纯本地统计，零 LLM）：评论清洗后近义聚簇（观众提问榜）、每周灵感包（需求×人设×热度×缺口、去重去已讲）、选题账本（已讲/可能已讲）。
- API：`GET /api/opportunities/comments | /weekly | /ledger`。
- 前端主页新增「内容机会」卡：观众提问榜 + 本周灵感包，均可一键生成。
- 测试 `tests/test_r185_opportunity.py`；`scripts/verify.sh` 全绿（135 路由）。

## [M173 / R-184] 2026-09-28 — 反馈闭环：发布回填 + 一键反馈

> 规划落地（内容经营闭环 R-180~R-186）。

- `drafts` 加 `publish_url/publish_platform/published_at` + `GET /api/drafts/{id}/performance`（关联素材时聚合各平台最新互动）。
- 前端：编辑抽屉加发布信息；卡片显示「已发布 · 平台」链接；卡片加快速反馈「好/差」；人设页风格范本区加选 5–10 条引导。
- 未做（后续）：发布后 24h 定时自动回填。
- 测试 `tests/test_r184_publish_backfill.py`；`scripts/verify.sh` 全绿。

## [M172 / R-183] 2026-09-28 — 生成提示词退回「方向盘」+ 创作模式 / AI 对话双模式

> 规划落地（内容经营闭环 R-180~R-186）。

- `generation` 提示词退回方向盘（删「先破后立/第一句必须钩子/全程断言」等写死句式，只留真实/具体/口语/禁 AI 腔 + 输出契约）；老库自动另存新版本并归档旧版。
- 新增创作模式（犀利干货/个人独白/热点评论/实验复盘）：贯穿 `generate(-async)` → `start_generation` → `run_debate` → `generation_user_message`；主页角度弹窗加模式选择。
- AI 对话拆双模式：`ops` 运营分析 / `create` 创作共创（允许发散、多方向、不急着套结构）；对话底部加切换。
- 测试 `tests/test_r183_generation_mode.py`；`scripts/verify.sh` 全绿。

## [M171 / R-182] 2026-09-28 — 人设档案四层重构（方案B 推倒重建）

> 作者：直接推倒重建。

- **模型**：`persona_tags` 加 `layer`（core_dna/stance/mode/forbidden）、`evidence`、`frequency`、`last_seen_at`、`confirm_strength`（`_migrate_persona_layer`）。
- **提示词**：`persona_merge`/`persona_updates` 升级为四层输出（老库自动另存新版本并归档旧版）；禁区只收「发布风险/法律合规/商业边界」。
- **管线**：`parse_layered_result` 四层解析 + 维度兜底；`annotate_profile_stats` 补频次/最近出现；`persist_suggestions` 写 layer/evidence；生成上下文按四层分组注入并优先核心 DNA。
- **重建**：`POST /api/persona/rebuild` + `persona_rebuild_task`（清空 → 全量重建为待确认 + `persona_check` 差异单）。
- **前端**：人设页已确认档案按四层分区（含层标签/证据/频次）、编辑加分层与证据、新增「推倒重建（四层）」按钮。
- **执行**：清空旧 163 条 → 收紧禁区后产出 29 条待确认（核心DNA 9／立场 10／模式 6／禁区 4），作者审核中；备份 `echo_pre_R182_rebuild_20260928_205102.db`。
- **验证**：`tests/test_r182_persona_rebuild.py` + `scripts/verify.sh` 全绿（30 表 / 131 路由）。

## [M170 / R-181] 2026-09-28 — 参考改写（洗稿）学习链路补齐

> 规划落地（内容经营闭环 R-180~R-186）：洗稿此前只有简化人设，补成与生成同源。

- `generation.py` 抽出共享 `author_style_context(db, topic="")`，`generation_user_message` 复用它（行为不变）。
- `benchmark.py`：`rewrite_script/rewrite_text` 改用完整人设+风格上下文；新增「参考改写」契约
  （只借选题与信息线索，不复用原文结构/核心比喻/句群，必须补作者自己的经历与判断）。
- `debate.py`：R-155 原文改写同步为「参考改写」契约 + 注入完整风格上下文。
- 验证：定向 pytest 全绿；`scripts/verify.sh` 全绿。

## [M169 / R-180] 2026-09-28 — 人设分析止血：只学当前主博主

> 规划落地（内容经营闭环 R-180~R-186）：对标博主素材也在跑人设，白烧 LLM 且堆积脏建议。

- `ingest.py`：`enqueue_persona_incremental` 只在 `cid == 当前主博主` 时入队；
  `persona_init_task/persona_incremental_task` 入口强制 `cid` 纠正回主博主。
- 清理：删除 1,807 条对标博主/无归属的 `suggested` 脏建议（清理前已备份）。
- 新增回归测试 `tests/test_r180_persona_owner_only.py`；`scripts/verify.sh` 全绿。

## [M168 / R-179] 2026-09-28 — 素材库加载提速：服务端统一分页 + 无感无限滚动 + 封面缩略图

> 作者：素材库页面还是加载太慢了，应该分页，每次加载20条，快划到底自动加载下一批数据，尽量让用户感觉没有加载的感觉。

- **实测根因（改前）**：首屏 1208ms；`GET /api/works` 一次拉 618 条 **1.57MB**（227ms，其中 `post_item` ×1172 = 211ms，
  `db.get(Creator)` **N+1 1172 次** + `json.loads(raw)` **×2344**）；首屏可见的 28 张封面就 **13.15MB**（原图直存：1766 张、
  均 191KB、p90 503KB、共 330MB）；DOM **24 262** 节点、616ms 主线程长任务。
- **服务端**：新增 `GET /api/library`——把「本地素材 + 云端作品合并去重后按日期倒序」这段口径从
  `frontend_v2/pages/videos/types.ts` 整体搬到 `services/library_service.py`（`buildCards`/`applyFiltersTo` 同语义，
  含 R-107 禁用账号排除），**游标分页**（`(date,kind,id)` 不透明串：滚动中后台同步插新条也不重复/漏条），
  筛选/搜索/计数（`total`/`filtered_total`/`facets.tags`）一并下推；`works_service.post_item` 批量预取 creator、
  `raw` 只解析一次（`core/platform_links` 拆出「已解析」入口），`/api/videos` 与 `/api/library` 共用可见性口径（`services/video_query.py`）。
- **封面缩略图**：`GET /covers/{name}?w=`（注册在静态挂载之前）用 **Pillow** 按需生成 + 落盘 `covers/thumbs/` + 原子写 +
  `Cache-Control`；上传封面/同步下载封面时顺手生成；启动后台线程预热历史封面（幂等，之后秒过）。1MB 原图 → 28KB（单张冷生成 34ms、命中 3ms）。
- **前端**：`useInfiniteQuery`（每批 20）+ `IntersectionObserver` **距底 600px 预取** + 骨架卡（尺寸同真卡、不跳版）+
  `keepPreviousData` 留住旧列表 + 底部细微加载条；返回态（滚动位置 + 已加载批次）保持；多选仍只作用已加载批次；
  新批次卡片 `softIn`（0.85→1 + 8px）淡入，不改布局。
- **实测（改后）**：首屏请求 **1.63MB → 42KB**（`/api/library` 27KB/20 条）、首屏封面 **13.15MB → 486KB**、
  DOM **24 262 → 1 085**、长任务 **616ms → 0**；滚到底自动加载（20 → 80 张）、滚动位置离开再回来保持在 4995、
  抽屉开关不跳位；**合并口径逐条对齐**：新接口分页走完 31 页 618 条与旧前端 `buildCards` 的顺序完全一致（无重复/漏条）。
- **验证**：pytest 新增 9 条（合并/筛选/游标稳定/缩略图/目录穿越防护）+ vitest 5 条（查询串/缩略图 URL）；
  `scripts/verify.sh` 全绿；服务保持运行。

## [M167 / R-178] 2026-09-28 — 讨论留痕显示并记录「真实模型 + 版本」（不再只写 model1/model2）

> 作者：讨论的模型不要展示成 model1、model2，展示成对应的模型和版本，并且要记录下来，不然我切模型了，都不知道之前用的什么模型。

- **现状（改前）**：留痕 `actor` 存的就是槽位名 `model1/model2`（表头直接显示它）；状态条文案里也拼槽位名；
  `Draft.quality.models` 其实有 `model1(deepseek/deepseek-flash)`，但**只在最后一次讨论写一次且会被别的流程覆盖**（草稿 37/38 已是 `{}`）；
  编辑 tab「本篇生成模型」读 `quality.gen_model/referee_model` —— 后端从没写过这两个 key，**一直是死代码**。
- **记录**：`draft_discussions` 加 `used_slot/vendor/model_id`（实际出结果的模型，取 `RoutedLLM.used_*`，与 R-142 同口径），
  按 AGENTS 手写幂等 `_migrate_discussion_model_fields`（加字段不靠 `create_all`）；每次讨论开头写一条 `kind='run'` 运行头
  （当时配置的生成方/评审方 + 轮次，结束时回填 `rounds_done/degraded`）→ 切模型后仍能回溯「那一次用的是谁」。
- **显示（四处全改）**：① 留痕表头 `生成方 [DeepSeek · deepseek-flash] 初稿 · 第0轮` ② 讨论 tab 顶部「本次讨论：生成方 X × 评审方 Y · 讨论 n/N 轮」
  ③ 草稿卡片/讨论 tab 状态条文案 `DeepSeek · deepseek-flash 正在评审第 1/3 轮…` ④ 编辑 tab「本篇生成模型」死代码修活（优先运行头、quality 兜底）。
  厂商名复用 `model_settings.VENDORS` 标签（单一事实源）；历史留痕显示「未记录模型（历史）」，**不按当前配置反推**。
- **动效**：模型标签/运行头摘要 0.85→1 淡入（新增 `softIn` 令牌，R-175 禁 0 起步）；顺手修掉自己引入的 hooks 顺序错误（`useMemo` 落到了 `if (!open) return null` 之后）。
- **验证**：真机冒烟（临时草稿跑 1 轮真实双模型讨论）状态条文案为 `Kimi（月之暗面） · kimi-k2.6 正在评审第 1/1 轮…`、6 条留痕全部带真实模型、运行头回填 1/1 轮；
  浏览器点检新留痕显示 `DeepSeek · deepseek-flash × Kimi（月之暗面） · kimi-k2.6`、老留痕显示「未记录模型（历史）」、控制台 0 报错；
  pytest 新增 5 条 + vitest 新增 6 条；`scripts/verify.sh` 全绿；服务保持运行。

## [M166 / R-177] 2026-09-28 — 脚本工作台「讨论」tab 滚动不了修复（ScrollArea 仅 max-h 约束时 Viewport 未定高）

> 作者：脚本工作室 讨论tab页 滚动不了。

- **根因（浏览器实测）**：讨论留痕列表是 `<ScrollArea className="max-h-[52vh]">`。Radix ScrollArea = `Root(overflow:hidden)`
  + `Viewport(overflow:scroll, h-full)`，**只给 Root max-h、没有显式 height** 时 Root 的 `height` 仍是 `auto` →
  Viewport 的 `h-full` 解析成 auto，高度=内容高度（草稿 #38 实测 **4215 / 4215**）→ 自己没有可滚余量；
  真正的高只有 Root 的 `max-height: 468px`，而 Root `overflow:hidden` → 超出内容被直接裁掉（`scrollTop` 恒为 0，
  滚轮无效）。显式高度的场景（`h-72`/`flex-1`）一直是好的。
- **修复**：`components/ui/scroll-area.tsx` 的 Viewport 加 `max-h-[inherit]`（继承 Root 上限 → 只有 max-h 时也能定高成为滚动容器，
  调用方仍只写 `max-h-*`，短列表不会被撑成固定高）。**同源场景一并修好**：标签多选（`max-h-64`）、通知列表（`max-h-[60vh]`）、提示词页（`max-h-72`/`max-h-56`）。
- **验证**：草稿 #38 讨论 tab Viewport 由 `4215/4215` 变 `468/4215`，滚轮 `0 → 600 → 1200`，滚到底 3747（=max），最后一条留痕可见；
  标签多选 `256/12960`、`scrollTop 0 → 300` 可滚且样式正常；新增 `scroll-area.test.tsx` 锁规则；`scripts/verify.sh` 全绿；服务保持运行。

## [M165 / R-176] 2026-09-28 — AI 对话发送 422「Input should be a valid dictionary or object to extract fields from」修复

> 作者：现在 ai 对话 进行对话就报错出错了：Input should be a valid dictionary or object to extract fields from

- **根因**：报错来自 `POST /api/chat/stream` 的 **422 body 校验**，不是模型/接口坏了（带正确头的同一请求 200 正常流式）。
  R-164 重写的新前端在 `chat/index.tsx` 用裸 `apiFetch` 发字符串 body，**漏了 `Content-Type: application/json`**；
  `fetch` 对字符串 body 默认 `text/plain;charset=UTF-8` → FastAPI 拿不到 JSON body，把整串文本直接交给 Pydantic →
  `model_attributes_type`。老前端 `ChatView.vue` 一直显式带头，属重写时引入的回归。实测：`text/plain` → 422 复现，`application/json` → 200。
- **修复**：① 调用点显式 `headers: { 'Content-Type': 'application/json' }`（对齐老前端契约）；
  ② `api/client.ts` 的 `apiFetch` 加兜底——body 是字符串且调用方未指定 Content-Type 时补 `application/json`
  （显式指定的头不覆盖，FormData 不动），从根上堵住这类漏头 → 422；
  ③ `client.test.ts` 新增 3 条断言（字符串 body 兜底 / 显式头不被覆盖 / FormData 不设头）。
- **验证**：`vitest` 6 passed；Playwright 无头端到端（带令牌 → 对话页 → 发送）请求返回 **200**、气泡正常流式且无「出错了」；
  `scripts/verify.sh` 全绿；后端(8000)/前端(3000) 保持运行。

## [M164 / R-175] 2026-09-28 — 动效规范立项（该有的动画不能省）+ AI 设置切 TAB 白闪修复

> 作者：① ai设置切换tab页的时候页面会闪一下 ② 添加到文档中，做功能 该有的动画不能省，所有的动画必须要美观流畅。

- **① 白闪根因**：R-174 给 `TabsContent` 的入场动效从 `opacity: 0` 起步，而 Radix 的 `Presence` 在未选中时
  **会卸载旧 Content** → "旧面板已消失 + 新面板全透明"叠加，先渲染出一帧空白。rAF 逐帧实测：切换帧
  `opacity 0.00`（面板 1218px → 644px），CDP 逐帧截图确认该帧内容为空 → 大卡片白闪一下。
  **修复**：入场改 `opacity 0.85 → 1` + `y 8 → 0`、0.22s（位移继续表达"新内容进来了"）。实测切换帧 0.85、
  约 100ms 落定 1.00，无空白帧。
- **② 写进文档（本次交付物）**：`AGENTS.md` 反问清单加第 9 条「**动效必问**」、工程标准加「**表现力（强制）**」、
  交付前自测加**动效点检**
- **验证**：无头 rAF 采样脚本工作台 `0.85→0.90→0.94→0.97→1.00`、AI 设置 `0.85→0.86→0.95→0.97→1.00`，
  8 页点检 0 页面错误；`vitest` 新增「入场首帧不得全透明」断言（锁死这条规则）；`scripts/verify.sh` 全绿；服务保持运行。

## [M163 / R-174] 2026-09-28 — 对标封面尺寸对齐素材库 + 展示口径「前3+最新」+ 全站 TAB 切换动画

> 作者：① 博主对标的封面图不需要那么大，和素材库的图一样大就行 ② 博主对标改为前3 + 最新一篇，其他逻辑不变
> ③ AI设置、脚本工作台，切换TAB页没有动画。

- **① 封面尺寸**：对标页网格 `lg:grid-cols-3` → `grid-cols-2 sm:grid-cols-3 lg:grid-cols-4`（与素材库一致），
  封面从 **344×258 → 255×191**（素材库同视口 265×199，差的 4% 来自对标分区 Card 的内边距）。
  卡片统计行加 `flex-wrap`，加载骨架 2 → 4 个。
- **②「前3 + 最新」= 4 条**：`target_units` 改 `ranked[:3]` + 最新 + 按互动分顺延补位、`picked[:4]`；
  `ensure_top3_with_text` → `ensure_top_with_text`（保底 4 条有文案）；`BENCH_TOP_N=3` 常量收敛口径。
  **其余规则一律不动**：15 条候选、广告/同款过滤、展示「有文案优先」、缺文案自动下载转写、无文案顺延、
  「最新」按 publish_time、`/top`、`/prepare`、重跑任务文案（`top3_with_text` → `top_with_text`）与 docstring 同步；
  前端文案「前2 + 最新一篇」→「前3 + 最新一篇」、「转写补齐（前2+最新）」→「（前3+最新）」。
- **③ TAB 切换动画（全站）**：`components/ui/tabs.tsx` 的 `TabsContent` 内层包 `motion.div`
  （opacity 0→1 + y 8→0，0.25s，复用 `EASE_OUT_EXPO`）；调用方的 `className` 挂在内层，避免破坏 `space-y-*`。
  Radix 未选中会卸载 Content → 每次切回都是重新挂载，动画必然重播。覆盖主页/AI 设置/脚本工作台及三个抽屉的 tab。
- **验证**：无头探针（封面唯一尺寸 255×191、每个对标 4 张卡、AI 设置与脚本工作台切 tab opacity 0.52→1.000 /
  0.31→1.000 且落定 transform none）；`/api/benchmark/top` 冒烟 11 个对标全部 4 条；
  `pytest` 383 passed、`vitest` 新增 tabs 3 例、`scripts/verify.sh` 全绿；服务保持运行。

## [M162 / R-173] 2026-09-28 — 草稿卡片 AI 任务状态动画 + 讨论 tab 思考状态条 + 结束判定修复

> 作者：① 草稿点开抽屉后卡片为什么重新触发动画 ② 讨论中草稿卡片应该给动画
> ③ 素材库洗稿后草稿卡片为什么只讨论了一轮 ④ 讨论 tab 里正在思考的模型需要动画，不然不知道是不是结束了。

- **① 卡片动画重放（bug）**：`DraftTile`/`Actions` 定义在 `DraftsPage` 函数体内 → 每次 re-render 都是新组件类型 →
  React 卸载重建整棵卡片子树 → 进入动画重放。无头实测：点开抽屉后原 `<article>` 节点消失、opacity `0.72→0.99` 重播。
  修：提到模块作用域（纯 props + handlers），与 R-171 `CreatorBlock` 同款。
- **② 卡片没有「讨论中」状态**：进度原本只写 `app_kv['debate:{id}']`，只有「自己在本抽屉点过讨论」才轮询。
  修：新增 `services/draft_status.py` 作为唯一事实源（键 `draft_ai:{id}`，JSON：state/kind/note/actor/phase/round/rounds），
  讨论/洗稿/回炉/AI 生成四类长任务统一写；`GET /api/drafts` 每条附带 `debate`（单次批量查询）；
  卡片显示「{类型} {模型} {步骤} 第 x/y 轮 + 三点跳动」，失败/中断显示「上次讨论中断（可重新讨论）」，
  列表仅在有人跑任务时 3s 轮询（无任务 0 请求）。
- **③「只讨论了一轮」= 显示滞后（已证实）**：作者 17:57 从素材库发起的洗稿（task 3253）实际跑满 3 轮（18:08:20 完成）；
  抽屉只在本地 `discussing` 为真时轮询，外部发起的讨论打开抽屉只拉一次快照 → 停在当时那一轮。
  修：抽屉打开即读 `/debate-status`，running 就进入轮询并实时补留痕（1→5 条实测）。
  另外把 R-118「某轮评审/修订失败就以当前稿定稿」也标成中断（原先静默只跑 1 轮，看着像正常结果）。
- **④ 不知道是否结束（真 bug）**：`/debate-status` 只返回 Kv 里的长文案或 `null`，从不返回前端等待的
  `done/idle/failed` → 轮询永不停止、完成提示与正文刷新永不触发。修：接口新增 `state`（`running|failed|null`，
  原 `status` 文案字段语义不变，兼容老前端），前端以 `state != running` 收尾；`tasks.py` 启动自愈把残留
  `running` 改判「服务重启，任务中断」（洗稿路径原先根本不清理 → 永久转圈）。
- **验证**：无头探针 4 项全过（节点不重建/状态条推进到收尾/结束后 0 次轮询/failed 有中断条与重新讨论按钮）；
  `backend/tests/test_r173_draft_ai_status.py` 9 例 + `draft-ai-status.test.tsx` 3 例；后端 `pytest` 382 passed；
  `scripts/verify.sh` 全绿；后端已重启加载新代码（8000 `/health` 200）、前端 3000 保持运行。

## [M161 / R-172] 2026-09-28 — 博主对标封面长宽高统一（4:3）

> 作者：博主对标，封面需要统一长宽高，不然有些封面很高。

- **根因**：封面框虽写了 `aspect-video`，但它是 `article`（flex column）的 flex item，`min-height: auto`
  的自动最小尺寸取内容高度——框内 `<img class="h-full">` 百分比高度在不定高祖先下回退为固有高度
  （344 宽 × 3:4 竖图 = 459 高），把 `aspect-ratio` 顶开；同排卡片被 grid stretch 拉齐，整页参差。
  无头实测：同一排 344×194（B站 16:9）与 344×459、344×678（抖音/小红书）并存。
- **修复**：`frontend_v2/src/pages/benchmark/index.tsx` 封面框改
  `relative aspect-[4/3] w-full shrink-0 overflow-hidden` + 图片 `absolute inset-0 h-full w-full object-cover`
  （绝对定位不参与内容尺寸计算）；`creators/posts-dialog.tsx` 加载骨架 `aspect-[3/4]` → `aspect-[4/3]`。
- **验证**：修复后 33 张封面框唯一尺寸 344×258（4:3）；博主管理作品弹窗 263×197、素材库 265×199 回归正常；
  `scripts/verify.sh` 全绿；服务保持运行。

## [M160 / R-171] 2026-09-28 — 博主管理同步进度条「消失又出现」

> 作者：博主管理点击同步后，进度条会消失又出现，很奇怪。

- **根因**：`CreatorBlock` 定义在 `CreatorsPage` 函数体内部，每次渲染都是新的组件类型 → React 每次重渲染
  卸载重建整块卡片；jobs 轮询/SSE 频繁触发重渲染，`SyncProgressBar` 的进入动画（`initial` opacity/height 0）
  被反复重放。无头探针实测：进度一变，进度条与账号行 DOM 节点即被替换。
- **修复**：`frontend_v2/src/pages/creators/index.tsx` 把 `CreatorBlock` 提升到模块作用域，改为纯 props
  （`job/running/syncingAll/hasBenchmarks/h`）。
- **验证**：递增进度 mock 下探针 `barSame/rowSame` 由 `false` 变持续 `true`；`scripts/verify.sh` 全绿；服务保持运行。

## [M159 / R-170] 2026-09-28 — 脚本工作台删除草稿报 Method Not Allowed

> 作者：我点击删除脚本工作台的脚本报错 Method Not Allowed。

- **根因**：后端无 `DELETE /api/drafts/{id}` 路由；草稿删除按设计为逻辑删除（`status='deleted'`，
  老前端走 `PATCH {status:'deleted'}`）。新前端 `doDelete()` 误用 `DELETE` → 405。
- **修复**：`frontend_v2/src/pages/drafts/index.tsx` 改用 `PATCH {status:'deleted'}`，与后端/老前端契约一致。
- **验证**：无头实测点删除→确认→`PATCH /api/drafts/36` 返回 200、卡片消失、提示「已删除」（修复前 405）；
  `scripts/verify.sh` 全绿；服务保持运行。

## [M158 / R-169] 2026-09-28 — 脚本工作台草稿卡片不可见（Framer Motion 变体未传播）

> 作者：脚本工作台，每次刷新页面重新打开，里面的明明有 2 篇草稿，却看不到。

- **根因**：`/api/drafts` 与 tab 计数均正常（草稿 (2)），无头浏览器实测卡片已在 DOM 中，
  但计算样式为 `opacity:0; translateY(14px)`（framer-motion `initial` 态）且从未进入 `animate`。
  草稿卡片位于 `TabsContent`→无 variants 的 `motion.div layout`→`AnimatePresence` 多层之下，
  父级 `listVariants` 的变体标签未传播到它；其它页列表项是 section 直接子节点故正常。
- **修复**：`DraftTile` 的 `motion.article` 显式 `initial="initial" animate="animate"`，
  不再依赖祖先变体传播。
- **验证**：无头实测修复后 opacity=1（修复前 0）；`scripts/verify.sh` 全绿；服务保持运行。

## [M157 / R-168] 2026-09-28 — 老前端 frontend/ 标记废弃，默认前端 = frontend_v2

> 作者：在文档中将老的前端项目标成废弃，以后说启动项目、修改项目都不修改老前端项目，而是新前端项目。

- `frontend/`（Vue 3 + Naive UI）标记**废弃**：只读保留（生产挂根路径兜底），禁止改代码/加功能/修 bug；
  `frontend_v2/`（React）成为**默认前端**，「启动项目 / 修改项目」一律指它（dev 3000 / 生产 /v2）。
- 标注：`AGENTS.md`（技术栈 + 目录速览 + 服务运行端口改 3000）、`README.md`（运行命令）、`docs/ARCHITECTURE.md`（前端行）。
- 老前端暂不删除；verify.sh 保留其 lint/build 防腐，后续下线/删除另立需求。
- 验证：`scripts/verify.sh` 全绿；服务保持运行（8000/3000）。

## [M156 / R-167] 2026-09-28 — frontend_v2 线上 bug②：AI 对话 [object Object] / 对标封面裂开 / 草稿抽屉空白防御

> 作者：脚本工作台明明有草稿，打开却是空白，ai对话进行对话，ai回复我出错了：[object Object]，博主对标页面的封面图是裂开的。

- **AI 对话错误显示**：`chat/index.tsx` 显式处理 `event: error` 帧（原先只查 `data.error` 字段，错误帧被漏过或
  把对象塞给 `new Error`）；新增 `errText()` 健壮提取；`api/client.ts` 新增 `detailText()`（FastAPI 422 的
  detail 数组/嵌套对象统一转可读文本）。
- **对标封面裂开**：后端 `unit_payload` 由远端 `cover_url`（CDN 防盗链 403）改 `cover_url_local`（本地 /covers/ 优先）；
  前端 benchmark/素材卡/作品弹窗/主页时间线封面加 `referrerPolicy="no-referrer"`。
- **草稿抽屉空白（防御）**：本地 34 篇草稿+新建保存链路+预览+深色+生产构建全量复测均正常、无法复现；
  新增 `ErrorBoundary` 组件包住 TipTap 编辑器，渲染崩溃时降级纯文本编辑（内容不丢），杜绝白屏。
- **验证**：对标封面 headless 实测全部加载（0 张 4xx）；错误提取单测 3 例；vitest 22 例全绿；verify.sh 全绿；服务保持运行。

## [M155 / R-166] 2026-09-28 — NAS Docker 部署包含 frontend_v2 构建

> 盘点「还有什么没做的」时发现：Dockerfile 只构建老前端，NAS 部署后 /v2 会 404（R-164 部署链路未闭环）。

- `Dockerfile` 新增 `frontend-v2-build` 阶段（node:22-alpine，vite 7 需要 Node ^20.19/>=22.12）：
  `npm install` + `npm run build`，产物 COPY 到 `/app/frontend_v2/dist`（与 `main.py` 的 /v2 挂载路径一致）。
- `.dockerignore` 排除 `frontend_v2/dist/`（与老前端同规则）。
- 验证：verify.sh 全绿；NAS 下次 `docker compose build && up -d` 后访问 `/v2/` 实测。

## [M154 / R-165] 2026-09-28 — frontend_v2 线上 bug：素材库卡顿 / 同步·拆分无动画 / 抽屉滚不到底

> 作者：现在页面很多bug，比如点击素材库，页面很卡，点击同步、拆分没有动画，弹出的抽屉，抽屉向下滚动不到底。

- **卡顿**：`MaterialCard` 改 `React.memo`（卡片回调全部 `useCallback` 稳定化；任务判断改 ref 读取的 `hasTask`，
  避免任务进度更新整页重渲）；去掉卡片/网格 framer-motion `layout` 动画；仅前 40 张卡有入场动画；
  卡片加 `content-visibility: auto` 跳过屏外渲染。
- **同步/拆分无动画**：`use-card-tasks` 新增 `begin()`（点击即显示本地进度 ramp）→ `claim()`（直接用同步接口
  返回的 `media.task_id` 接管进度，替代原先的盲扫竞争）→ `finish()`；任务终态经 `onSettled` 回调自动刷新列表；
  拆分/删除加卡片级 spinner 覆盖层。
- **抽屉滚不到底**：页面容器有 framer-motion transform/filter，`position:fixed` 相对祖先而非视口定位 →
  Drawer 与聊天重命名弹层改 `createPortal` 挂 `document.body`。
- **验证**：headless 实测（抽屉 top=0 覆盖全视口+滚动到底、同步卡片即时进度、618 卡滚动流畅、零 console 错误）；
  `scripts/verify.sh` 全绿；服务保持运行。

## [M153 / R-164] 2026-09-28 — 全新前端 frontend_v2（全功能 9 页重设计，挂 /v2）

> 作者：前端太丑，新建独立项目（老前端名+v2），零复用老代码、全新布局、审美与动效优先。
> 确认：React + shadcn/ui + Framer Motion；Linear/Vercel 风；全功能新皮肤；挂 /v2 并存；
> 先做视觉基准（登录+主页）确认风格再铺其余 7 页；vitest 组件测试。

- **新目录 `frontend_v2/`**：React 19 + TS(strict) + Vite 7 · Tailwind v4（CSS 变量双主题令牌）·
  shadcn/ui 风格基础组件（button/card/dialog/dropdown/tabs/tooltip/scroll-area/avatar/switch/progress/sonner 等）·
  Framer Motion（页面转场/stagger/微交互）· TanStack Query · TipTap React 预留 · vitest + Testing Library。
- **API 层**：`openapi-typescript` 从 `/openapi.json` 生成 `schema.d.ts`（`npm run gen:api`）+
  `openapi-fetch` 客户端（X-Access-Token 中间件、401 清 token 跳登录、detail 错误归一）；
  SSE 客户端（fetch 流 + 自动重连 + 事件总线）驱动 Query 失效刷新；登录态独立 key（`echo_v2_token`）。
- **布局壳**：可收缩左侧导航（图标轨+active 指示动画）/ 顶栏（标题转场 + 搜索占位 + 通知中心 + 主题切换）/
  移动端抽屉；通知中心（未读角标 + 面板 + 全部已读/清空）。
- **全功能 9 页重设计**（功能对齐老前端，布局/交互全部重做）：
  - **主页**：时间线横轴（封面 hover/今天刻度）+ 灵感池（来源 tab/换一批/抓取更新/生成文案→角度弹窗）。
  - **素材库**：**卡片墙**（封面懒加载/hover 播放/角标/进度覆盖层动画/多选批量）+ **右侧抽屉编辑**
    （标题/平台链接/封面/视频/关联脚本/元信息/标签/转写/文稿/评论 tab）；云端转本地抽屉；播放器弹窗；
    全套筛选工具栏（持久化）+ 上传 + 自动合并/拆分 + SSE/轮询双通道卡片同步进度。
  - **脚本工作台**：四 tab（草稿/待制作/完成/废稿）+ 打分/分节反馈 + **TipTap React** 块编辑器（Markdown
    契约不变、粘贴/拖拽插图）+ 讨论（双模型留痕）/正文对比（两版 diff）/版本（回滚/查看）+ 体检/回炉/定稿。
  - **博主管理**：博主/账号卡片（头像上传/启停/同步/作品弹窗/表单/解析链接）+ 运行中进度条（jobs 轮询+SSE）
    + 预算调整 + 切换/对标确认流。
  - **博主对标**：前2+最新卡片（互动分/文案/AI 分析/洗稿）+ 重新对标任务 + 洗稿原文对照弹窗。
  - **人设档案**：初始化/增量校验面板 + 金句库 + 表达风格（禁用词/样本/范本）+ 建议确认流 + 档案多选删除。
  - **AI 设置**：模型槽位（厂家/模型/Key）+ 生成方/评审方 + ASR + 每日篇数 + 推理预算网格 + 自检结果 +
    各功能提示词（编辑/候选/评测/启用/历史/效果对比）。
  - **AI 对话**：会话侧栏 + SSE 流式（步骤条+Markdown 渲染）+ 写操作确认/取消条。
- **后端/门禁**：`main.py` 挂 `/v2` 静态目录；`verify.sh` 增 `frontend_v2`（eslint + vitest + tsc/vite build）。
- **验证**：frontend_v2 自测 tsc/eslint/vitest 19 例全绿 + build 通过（vendor-react/motion/query/radix/tiptap 分包）；
  Playwright headless 全页面点检（9 页渲染/登录/抽屉/编辑器/通知/主题切换，零 console 错误）；
  `scripts/verify.sh` 全绿；服务保持运行（8000/5173/3000）。
- **修复**：AppShell 页面级 `AnimatePresence mode=wait` 与 React 19 Outlet 组合导致页内 setState 时整页
  误卸载重挂载（抽屉打不开）→ 改为仅入场动画的 key 化 motion.div；`asr.options`/`budgets` 按接口真实形态取值。

## [M152 / R-163] 2026-09-28 — 同步提速：任务进队列 + 消费者并行 + TikHub 全局限速（10 req/s）

> 作者：现在同步的速度太慢了，都是同步的操作，任务放到队列中，消费者应该并行，不过tikhup只支持10个请求/s。
> 确认：限速=全局合计 10 req/s（保留按路由 429 退避兜底）；博主级+素材级都并行；并发可配默认 4；允许 SQLite WAL。

- **R-163 限速器**：`platform/tikhub.py` 新增进程内**全局令牌桶** `_TokenBucket`（`_throttle_route` 先过桶），
  速率/容量取 `ECHO_TIKHUB_RATE_LIMIT`（默认 10 req/s）/ `ECHO_TIKHUB_RATE_BURST`（默认 10）；
  移除默认「按路由 1.2s 串行」，改为**按路由 429 退避兜底**（`_penalize_route`）；保留 R-151 有界重试与退避。
- **R-163 消费者池**：新增 `services/sync_pool.py`——`claim_task`（`UPDATE … WHERE status='pending'` 原子认领）、
  `gather`（线程池并发 + 单任务异常收集 + 完成回调）、`pool_size`、`session_factory`（按 bind 派生线程安全会话）。
- **R-163 博主级并行**：`run_all_top15_sync`（sync-all）与 `run_daily_sync_all`（每日 06:00/17:00）由逐个串行改为
  线程池并发（`ECHO_SYNC_CONCURRENCY` 默认 4）；每个博主独立 Session、复用预置 SyncJob；进度按完成数聚合；
  `BudgetExceeded` 触发取消标记，未开始者置 failed。
- **R-163 素材级并行**：`run_card_sync_queue` 改为并发消费（`ECHO_SYNC_MEDIA_CONCURRENCY` 默认 2，独立小池）；
  同一合并作品去重改为主线程按平台优先级**确定性预标记**（防并发重复下载）；评论/灵感池计数即使媒体步骤失败也如实汇总。
- **R-163 稳定性**：`platform/budget.py` `_charge`/`ensure_budget` 加进程内 `RLock`，并行下不超发；
  `db.py` 连接时开 `journal_mode=WAL` + `busy_timeout=30000` + `synchronous=NORMAL`。
- **验证**：新增 `tests/test_r163_sync_pool.py`（令牌桶速率/突发、claim 原子性、gather 并发与异常收集、预算并发不超发）；
  更新 `tests/test_r151_tikhub_retry.py`（重置限速器 + 429 退避）、`tests/test_r162_sync_all_queue.py`、
  `tests/test_r109_daily_sync.py`（并发后改为顺序无关断言）；`scripts/verify.sh` 全绿 + 接口冒烟 + 前端点检；服务保持运行。

## [M151 / R-162] 2026-09-19 — 博主管理：【同步对标博主前15条】改为【同步所有博主前15条】（队列化、所有博主同时显示动画）

> 作者：同步对标博主前15条，改为同步所有博主账号前15条，点击后将所有博主的任务提交到队列中，
> 然后后台一步消费，前端需要展示所有博主的同步动画。
> 确认：范围=当前主博主 + 其全部对标博主；运行中的博主跳过并汇总；保持串行消费（不做博主间并行）。

- **R-162 后端**：`platform_sync.run_sync` 新增 `job` 参数（队列复用预置 SyncJob，缺省行为不变）；
  新增 `enqueue_all_top15_sync(owner)`（为每个博主写 `platform_sync` 队列任务 + 预置 running 的 SyncJob，
  阶段「排队中…」，跳过运行中/无启用账号者）、`run_all_top15_sync(owner, entries)`（单消费者按队列顺序逐个
  `run_sync(scope=daily, creator_id=…, with_media=True, job=…)`）、`all_top15_worker`；完成后若有同步成功则
  `maybe_start_benchmark_rerun(refetch=False)`。接口 `POST /api/platform/sync-benchmarks` → `POST /api/platform/sync-all`
  （无主博主/无可同步博主 400，同批任务在跑 409）。**无表结构变更**（复用 `background_tasks` + `sync_jobs`）。
- **R-162 前端**：`CreatorHeaderRow` 按钮文案改【同步所有博主前15条】；`CreatorsView` 调 `/api/platform/sync-all`，
  确认弹窗说明范围与成本；沿用 `/api/platform/jobs?status=running` 轮询——所有预置 job 使主博主与全部对标卡片
  **同时出现同步动画**（排队中显示不确定进度，轮到后显示真实 done/total）；批量按钮在自身或任一博主运行中保持 loading。
- **验证**：`tests/test_r162_sync_all_queue.py`（入队顺序=主博主+全部对标 / 预置 running job / 跳过运行中与无账号 /
  消费者复用预置 job 且收尾自动重新对标）；`scripts/verify.sh` 全绿 + 接口冒烟 + 前端点检；服务保持运行。

## [M149/M150 / R-160+R-161] 2026-09-18 — 博主管理：一键同步对标前15条 + 多账号连点动画修复

> 作者 2 条：①当前博主「全量同步」后加【同步对标博主前15条】，点击同步其下所有对标账号前15条；
> ②逐个点每个账号「同步前15条」，点得多了后点的没有动画。
> 确认：同步深度与主博主「同步前15条」完全一致；完成后自动重新对标；后端一个后台任务统一编排；运行中的对标跳过。

- **R-160 后端**：`platform_sync.run_benchmark_top15_sync(owner)` + `benchmark_top15_worker`——
  遍历当前主博主全部对标，逐个 `run_sync(scope=daily, creator_id=bm.id, with_media=True)`（评论采集 +
  缺视频下载 + 缺转写 ASR，已下载/已转写跳过）；`platform_sync` 任务 payload.creator_id 命中的对标跳过；
  单个对标失败不阻断其余，`BudgetExceeded` 停止；完成后 `maybe_start_benchmark_rerun(refetch=False)`。
  接口 `POST /api/platform/sync-benchmarks`（无主博主/无对标 400，同类任务在跑 409）。**无表结构变更**。
- **R-160 前端**：`CreatorHeaderRow` 在「全量同步」后加【同步对标博主前15条】（仅当前主博主且其下有对标时显示），
  二次确认后调用；`CreatorAccountRow`/header 的进度条沿用既有 `jobFor`（每个对标一条 SyncJob）。
- **R-161 修复**：`CreatorsView` 原用**单个共享变量** `syncingAcct`/`syncingOwner` 表示“哪个在转圈”，
  并发连点多个账号时先返回的请求在 `finally` 把变量清零，覆盖后点账号的 loading（点击越多越明显）。
  改为 `reactive(new Set())` 按 id 独立记录，每个请求只清自己；子组件 prop 由数字 id 改布尔 `syncing`。
  并将 `pollJobs` 改为 `GET /api/platform/jobs?status=running&limit=50`（`list_jobs` 新增可选 `status` 参数），
  避免历史 job 把运行中进度挤出。
- **验证**：`scripts/verify.sh` 全绿（ruff + mypy + pytest + 前端 lint/build + 文档一致 30 表/129 路由）；
  `tests/test_r160_benchmark_top15.py`（遍历全部对标 / 跳过运行中 / 无对标报错 / 全跳过不触发重新对标）；
  接口冒烟 + 前端点检；服务保持运行。

## [M148 / R-159] 2026-09-14 — 脚本工作台：新增「完成」状态与 tab + 待制作两个流转按钮
> 作者：脚本工作台加【完成】tab；待制作的素材加【完成】按钮（变完成状态）、加【退回草稿】按钮（变草稿状态）。

- **状态**：`drafts.status` 新增 `done`（完成）——`DraftCreate`/`DraftUpdate` 白名单加 `done`，模型注释与
  AI 对话只读视图 `v_drafts.status` 说明同步（`draft=草稿 / used=待制作 / done=完成 / archived=不采用 / deleted=已删除`）。
  `status` 是 VARCHAR，**无表结构迁移**。
- **前端 `DraftsView`**：tab 变四个 **草稿 / 待制作 / 完成 / 废稿**（工作流顺序）；
  待制作卡加**【完成】**（→`done`）与**【退回草稿】**（→`draft`），保留【移入废稿】【删除】；
  完成卡提供**【退回待制作】**（→`used`）与【删除】；深链打开时切到对应 tab（含 `done`）。
  流转只改状态、**不动反馈**（「采用」时已记过一次正向信号）；【删除】仍走 R-158 的二次确认逻辑删除。
- **验证**：`scripts/verify.sh` 全绿（ruff + mypy + pytest **366 例**（新增 2 例：`done` 全状态往返 / 非法状态 422）
  + 前端 lint 0 error + build + 文档一致 30 表/128 路由）；
  headless Chrome 点检（测试临时稿，跑完清理）：四 tab 正确，待制作点【完成】→ 待制作 2→1 / 完成 0→1，
  完成点【退回待制作】→ 完成 0 / 待制作 2，待制作点【退回草稿】→ 草稿 +1。

## [M147 / R-158] 2026-09-14 — 草稿工作台：恢复「废稿」tab + 删除二次确认 + 废稿可恢复
> 作者：【不采用】移到废稿栏；【删除】需要提示是否删除、删除才是逻辑删除、页面上不可见。
> 确认：恢复「废稿」tab 且**只列未采用（archived）**的稿子（已删除的不可见）；两个 tab 的「删除」都弹确认；
> 废稿里提供「恢复为草稿」。这**部分回退 R-152** 的「隐藏废稿 tab」展示决定（状态语义与后端接口不变）。

- `DraftsView`：恢复第 3 个 tab「废稿 (N)」（只列 `archived`；空态提示从哪进来），每条提供「恢复为草稿」+「删除」；
  `list('archived')` 不再把 `deleted` 一起列出来。
- 「不采用」（草稿卡）/「移入废稿」（待制作卡）→ `archived`，进废稿 tab、可恢复。
- 「删除」→ `useDialog` 二次确认（「确定删除「标题」？删除后页面上不可见。」，按钮 删除/取消）→ 确认后 `PATCH status=deleted`，
  此后任何 tab 都不展示；`deleted` 不做物理删除。
- 深链 `#/drafts?id=X` 打开时切到对应 tab（draft/used/archived）；已删除的不在任何 tab。
- **后端/接口/表结构零改动**（`archived` / `deleted` 语义本来就有）。
- **验证**：`scripts/verify.sh` 全绿（ruff + mypy + pytest **364 例** + 前端 lint 0 error + build + 文档一致 30 表/128 路由）；
  headless Chrome 点检：三个 tab「草稿/待制作/废稿」、废稿卡按钮「恢复为草稿|删除」、
  草稿卡点删除弹出确认（含 取消/删除），点取消后稿子仍在、弹窗消失（未对真实草稿执行删除）。

## [M146 / R-157] 2026-09-14 — 草稿版本：自动定稿补齐 + 回滚/查看 + 【正文对比】
> 作者 5 条：①为什么 AI 洗稿后没自动定稿——要求洗稿前 ASR 为第一版、洗稿后为第二版；②【版本】每条加【回滚到此版本】【查看】，
> 回滚只是把版本快照覆盖回当前正文保存；③【原文对照】改【正文对比】，左右各一个版本下拉框选任意两版对比；
> ④【版本】不再提供两版对比；⑤点讨论时若没有任何版本，先把当前正文定稿为第一版，讨论后生成第二版。

- **根因（第 1 条）**：R-156 的自动定稿只接在讨论链路（`draft_flow.discussion_task`），洗稿走的是
  `benchmark.rewrite_worker → run_rewrite_debate`（对标页 + 素材库编辑页洗稿），当时没接，所以洗稿稿没有版本。
- **自动定稿补齐**（`source` 区分，界面标签区分）：
  - 洗稿 `run_rewrite_debate`：**两版**——洗稿前先把素材 ASR 文案记第一版（`note=洗稿前（素材 ASR）`），洗稿完成记第二版（`note=洗稿后`）；
  - 讨论 `discussion_task`：**无版本时**先把当前正文记一版（`note=讨论前`），跑完记 `讨论后`；已有版本只追加一版；
  - AI 生成（`generate_draft` / `debate_task`）与一键回炉（记到**原稿**）、每日自动生成各留一版；金样本自测（`api/prompts`）与回炉中间稿不留
    （`generate_draft(..., snapshot=False)`）；
  - 新增 `finalize_version`（留版 + **≥2 版才**触发改稿差异分析，首版不空跑）与 `maybe_start_diff_analysis`。
- **回滚**：`POST /api/drafts/{id}/versions/{vid}/rollback`——把该版本快照（正文/标题/封面字/标签）覆盖写回草稿并保存；
  **不额外留痕、不改状态**（作者口径）。`GET /versions` 仍返回时间正序列表。
- **前端**：`snapshot_version` 支持 `content` 覆盖（「洗稿前 ASR」不是草稿当时状态的快照）；
  【版本】tab 去掉两版对比，每条加**【回滚到此版本】【查看】**（查看=弹窗显示该版本 标题/封面字/标签/正文）；
  原【原文对照】→**【正文对比】**：左右两栏正文上方各一个版本下拉框（只列版本，默认左=次新/右=最新），
  <2 版提示先定稿；来源标签扩为 手动定稿 / AI 讨论定稿 / AI 洗稿定稿 / AI 生成定稿。
- **验证**：`scripts/verify.sh` 全绿（ruff + mypy + pytest **364 例**（新增 5 例：回滚纯覆盖不留痕 / 回滚 404 /
  洗稿前后两版 / `generate_draft` snapshot 开关 / 首版不触发分析；并按新口径更新 R-156 两例）+ 前端 lint 0 error
  + build + 文档一致 **30 表 / 128 路由**）；真实接口冒烟：两次定稿 → 版本 2/3，回滚到版本 2 后草稿恢复且版本数不变、
  非法版本 404；headless Chrome 点检：版本行按钮序「回滚到此版本|查看」、版本 tab 无对比区、查看弹窗显示正文、
  正文对比 2 个下拉框 + 2 栏 diff。测试草稿与版本已清理（未触碰用户真实草稿）。

## [M145 / R-156] 2026-09-14 — 草稿定稿 + 版本留痕 + 任意两版差异 + 版本链反哺 AI
> 作者 5 条：①【洗稿后】改【修改后】；②编辑/新增加【定稿】按钮 + 【版本】tab，每次定稿存一条当前正文；
> ③AI 讨论跑完自动把最新一版定稿留痕；④可选任意两个版本做差异比较；⑤AI 分析能看出第一稿到最后一稿的变更，生成更准。
> 确认口径：定稿=快照+标记（不锁定不改状态）；版本存 正文+标题+封面字+标签；定稿=先保存再记版本；
> 版本 tab 列表选两版出 diff（默认最新两版）；版本链接到改稿差异分析 + 生成 few-shot。

- **文案**：原文对照右侧标题「洗稿后」→「**修改后**」。
- **数据**：新增表 `draft_versions`（`draft_id/title/cover_text/script/tags/source/note/created_at`，`source=manual|ai_discuss`）；
  新表由 `create_all` 自动建（无字段迁移）；`DATABASE.md` 29→30 表。
- **接口**：`POST /api/drafts/{id}/finalize`（先更新草稿再记一条版本，触发版本链分析；内容全空 400、草稿不存在 404）；
  `GET /api/drafts/{id}/versions`（时间正序，含正文，前端本地算 diff）。
- **AI 讨论自动定稿**：`draft_flow.discussion_task` 在讨论跑完后 `snapshot_version(source="ai_discuss")` 并触发 `diff_analysis`。
- **前端**：编辑 pane 保存旁加**【定稿】**按钮（新建稿有内容先建稿、空稿提示不落库）；新增第 4 个 tab**【版本】**——
  版本列表（时间/来源/标题，手动定稿 vs AI 讨论定稿）、点选两版（默认最新两版、满两个挤掉先选的）、
  下方左右红绿 diff、顶部显示「当前正文与最新版本一致（已定稿）/ 当前正文有未定稿改动」。
- **AI 学习（第 5 条）**：`analyze_diff` 改为接收**版本链**（初稿→…→定稿，去相邻重复），提示词改成「看逐版修改」；
  `apply_diff_suggestions` 版本链优先、无版本退回 `original_script→script`；生成注入的 `_rewrite_examples`
  优先用版本链的**首版→终版**（无版本退回老行为）；后台任务体统一为 `diff_analysis.diff_task`。
- **验证**：`scripts/verify.sh` 全绿（ruff + mypy + pytest **359 例**（新增 14 例：快照/版本链/批量链/多阶段提示词/
  相邻重复忽略/apply 用版本链/diff_task/`_rewrite_examples` 用版本链/定稿接口 3 例/讨论自动定稿）+ 前端 lint 0 error
  + build + 文档一致 **30 表 / 127 路由**）；真实接口冒烟：两次定稿各生成版本 1/2（script 正确）、`/versions` 返回两条、
  空稿定稿 400；headless Chrome 点检：原文对照显示「修改后」（无「洗稿后」）、编辑弹窗有【定稿】、
  版本 tab 2 条版本默认全选且出 2 栏 diff、状态显示「已定稿」。测试用草稿与版本已清理。

## [M144 / R-155] 2026-09-14 — 草稿讨论 tab：【讨论 / 重新讨论】入口（基于原文跑双模型多轮讨论）
> 作者：讨论 tab 没讨论过时把「暂无讨论记录」变成【讨论】按钮，点击后 AI 拿原文做多轮次讨论并生成标题/封面字/标签；
> 讨论过则在底部给【重新讨论】，点击后拿原文重新讨论。
> 确认口径：原文＝洗稿稿用洗稿素材 ASR 文案（`original_script`）、自建稿用当前正文；正文+标题+封面字+标签都更新；
> 标签与现有合并去重；重新讨论保留旧留痕；未保存的新建稿提示先保存。

- **后端**：`run_debate` 增加可选 `source_text/source_title`（旧调用行为不变）——传了就走「基于原文」初稿提示词
  （产出 `title/cover_text/script/tags`），写回 `draft.original_script`（供【原文对照】），`merge_tags` 与现有标签合并去重，
  随后沿用**同一套** N 轮评审/修订 + 自检收口 + `quality`；`draft_flow` 新增 `resolve_discussion_source` /
  `start_discussion` / `discussion_task`（任务 kind=`draft_discuss`），重新讨论前写一条「—— 重新讨论（基于原文）——」分隔；
  `POST /api/drafts/{id}/discuss`（草稿不存在 404 / 无可讨论原文 400）。
- **前端**：`DraftsView` 讨论 tab——未保存新建稿提示「先保存草稿」；无留痕处显示【讨论】按钮（无可讨论原文时置灰）；
  有留痕时底部【重新讨论】；运行中按钮隐藏 + `debate-status` ⏳；任务终态后把标题/封面字/正文/标签/原文案刷回弹窗并刷新列表。
- **验证**：`scripts/verify.sh` 全绿（ruff + mypy + pytest **345 例**（新增 9 例：原文解析 3 + 写回/标签合并 + 留痕追加 +
  接口三态）+ 前端 lint 0 error + build + 文档一致 29 表/125 路由）；
  **真实链路端到端**（自建稿→`/discuss`）：任务 `done 100`，3 轮跑满（`rounds_done=3`、`passed=true`、
  gen=model1(deepseek-flash)/critic=model2(kimi-k2.6)），标题/封面字/正文被更新，标签合并为
  `["成长","求职","职场","复盘","低学历逆袭","个人成长"]`，`original_script` 写回原文，`draft_discussions` 7 条（draft+3×(critique+revise)）；
  headless Chrome 点检：无留痕稿显示【讨论】、有留痕稿显示【重新讨论】（4 条留痕）、未保存新建稿提示先保存且 0 个讨论按钮。
- 测试用临时草稿均已按应用语义逻辑删除，未留垃圾数据。

## [M143 / R-154] 2026-09-14 — 脚本工作台草稿：空白新建不落库 + 弹窗关闭即刷新
> 作者反馈：①新建草稿后叉掉弹窗，刷新页面发现草稿 tab 多了一条全空草稿——「新建了草稿但里面没有任何内容不应该新建」；
> ②新建/编辑弹窗「叉掉 / 保存 / 取消」后都要调用查询接口，否则要切页才能看到新数据。

- **根因**：`createDraft()` 点「新建草稿」当场 `POST /api/drafts {空内容}` 落库，叉掉弹窗不做任何处理 → 库里留下空稿；
  `closeEdit()` 只关弹窗不查询 → 列表要等切页重挂载才更新。实测库里确有 2 条当天产生的空 `draft`（id 26/27）。
- **修复（前端 `DraftsView.vue`）**：新建改为打开**本地空白稿**（`id=null`，不发请求）；`save()` 时
  `title/cover_text/script/tags/video_id` 全空 → 提示「草稿内容为空，未保存」并关闭、**不落库**，有内容才 `POST`；
  `closeEdit()`（叉掉 / 取消 / 保存统一入口）调用 `load()` 重新查询列表，保存新建后自动切到「草稿」tab。
- **后端**：`DraftCreate` 补 `tags: list[str]` 并在 `create_draft` JSON 编码（原只有 `PATCH` 支持 tags，新建带标签需要它）；
  `POST /api/drafts` 对全空内容返回 400「草稿内容为空，未创建」作为其它调用方的兜底（路径/表结构不变）。
- **数据清理**：把本次问题遗留的空草稿（id 26/27）按应用既有语义**逻辑删除**（`status=deleted`，不物理删）。
- **验证**：`scripts/verify.sh` 全绿（ruff + mypy + pytest **336 例**（新增 5 例：带 tags 往返 / 无 tags 默认空 /
  空白拒绝且不落库 / 纯空白拒绝 / 仅 tags 或 video_id 允许）+ 前端 lint 0 error + build + 文档一致 29 表/124 路由）；
  headless Chrome 点检：新建不写内容叉掉后草稿卡数不变（2→2）、关闭时触发 `/api/drafts?limit=500` 查询、
  写入标题保存后卡数 2→3 且标题立即可见。

## [M142 / R-153] 2026-09-14 — 素材库洗稿入口收敛：去掉卡片上的洗稿，只留编辑页
> 作者验收 R-152 后要求：保留编辑页的洗稿，去掉素材卡片上的洗稿按钮。

- `MaterialCard.vue`：删除云端卡与本地卡上的「洗稿」按钮及 `canRewrite` / `rewritingKey` / `rewrite` 三个 props。
- `VideosView.vue`：移除卡片洗稿接线（`canRewriteCard` / `rewriteCard` 与传给卡片的 props）；
  **保留**编辑页链路——`canRewriteEditing` / `rewriteEditing`、`TranscribeSection` 的「洗稿」按钮、
  `RewriteDiffModal`、`composables/rewrite.js`，以及后端 `POST /api/benchmark/rewrite-source` 与 `VideoOut.creator_id`
  （因此**后端/接口/表结构零改动**）。
- **验证**：`scripts/verify.sh` 全绿（ruff + mypy + pytest 331 例 + 前端 lint 0 error + build + 文档一致 29 表/124 路由）；
  headless Chrome 点检：非主博主素材卡片洗稿按钮 **0** 个（卡片动作＝同步/删除）、编辑页「已转写」旁「洗稿」仍在、
  切回主博主 0 个。

## [M141 / R-152] 2026-09-14 — 脚本工作台隐藏废稿 tab + 对标「前2+最新」+ 素材库非主博主洗稿入口
> 作者四条：①脚本工作台【废稿/已删除】tab 不再展示（只是不展示）；②博主对标沿用旧规则取两篇，第三篇为对标博主最新一篇；
> ③素材库非主博主的卡片素材「同步」旁加洗稿；④素材库非主博主素材编辑页 ASR「已转写」旁也加洗稿。
> 反问确认：第三篇与前2重叠 → 按互动分顺延保底3条；第三篇没有文案 → 也自动补齐转写；
> 洗稿加在云端卡与本地卡（凡有「同步」的）；`DraftsView` 保留「不采用/移入废稿/删除」按钮，只隐藏 tab。

- **① 脚本工作台**：`DraftsView.vue` 删除 `archived` tab-pane（只剩「草稿/待制作」）；后端 `drafts.status` 语义、接口、
  `markArchived`/`softDelete` 与按钮**一律保留**（作者「只是不展示」）；深链打开废稿/已删除稿时不再切到已隐藏 tab
  （弹窗照常可看），删除提示改为「已删除」。
- **② 博主对标口径**（`services/benchmark.py` / `api/benchmark.py`）：新增 `target_units()` 统一目标选取
  （`with_text_first` 保留 R-106「有文案优先」展示口径）——最新 15 条按互动分取**前 2** + 第三篇 = 该对标**最新一篇**
  （重叠时按互动分顺延补第 3，保底 3 条；候选不足 3 条则给全部）；`/top`、`/prepare`、`rerun_benchmarks`（含每日同步后
  自动重算）全部走同一口径；`ensure_top3_with_text` 同样对最新一篇补齐转写（无文案/广告顺延）。文案与页头提示同步改写。
- **③④ 素材库洗稿入口**：新增 `resolve_rewrite_source()` + `POST /api/benchmark/rewrite-source`
  （入参 `video_id` / `post_id` / `work_id` 三选一，服务端取该素材 ASR 文案 + 标题 + 对标名 + 来源 id），
  复用现有双模型多轮讨论洗稿 `rewrite_worker`，落脚本草稿；主博主自己的素材拒绝（400）。
  `VideoOut` 新增 `creator_id`（前端判断「非主博主」）；
  前端新增 `composables/rewrite.js`（发起 + 轮询，状态模块级跨页保留）+ `components/RewriteDiffModal.vue`
  （博主对标页与素材库共用的原文/洗稿对照弹窗，消除重复弹窗代码）；
  `MaterialCard` 云端卡与本地卡「同步」旁、「TranscribeSection」「已转写」旁加「洗稿」（仅非主博主素材）。
- **文档**：API.md（+1 路由，共 124）、
  milestones（M141）、requirements/R-152。
- **验证**：`scripts/verify.sh` 全绿（ruff + mypy + pytest **331 例**（新增 11 例：前2+最新/重叠顺延/有文案优先/
  最新补转写/来源解析与主博主编拒/接口三态）+ 前端 lint 0 error + build + 文档一致 29 表/124 路由）；
  接口冒烟与前端点检见里程碑记录。

## [M140 / R-151] 2026-09-14 — 素材同步失败修复：TikHub 同路由限速 + 瞬时故障重试
> 作者报障：素材同步失败 ——「关于经济独立我的思考…」：`TikHub 请求失败: [SSL: UNEXPECTED_EOF_WHILE_READING] EOF occurred in violation of protocol`。
> 该次 daily 同步（09:22–09:34，5 个博主账号）注册的 `card_sync` 队列里 **169 条失败**，通知只显示到其中两条。

- **根因（实测三条，非推测）**：
  1. **本地代理掐断 TLS 隧道**。进程环境变量里没有任何 `*_PROXY`，但 `httpx._utils.get_environment_proxies()`
     返回 `{'http://': 'http://127.0.0.1:7890', 'https://': 'http://127.0.0.1:7890'}`——
     httpx 默认 `trust_env=True`，会读 **macOS 系统代理**；堆栈落在 `httpcore/_sync/http_proxy.py:316 → start_tls`，
     即 CONNECT 隧道建好后在 TLS 握手阶段被掐断。同窗口 DeepSeek 也报 `ConnectTimeout`/`RemoteProtocolError`，
     属本地代理到外网的**瞬时抖动**（手工探测与随后请求均 200，API key / 额度正常）。
  2. **TikHub 单路由限速 1 请求/秒**。并发 40 次探测 **35 次 429**，响应原文：
     `"Request too fast, the request rate limit for the current route is 1 times/second"`；
     而 daily 同步是 `ThreadPoolExecutor(3)` 多账号并行、每条素材再打评论接口，必然超限 ——
     被限流时服务端有时回 429，**有时直接掐 TLS 连接**（就是上面的 SSL EOF）。
  3. **代码放大故障**：`TikHubClient._get()` 只有一次 `httpx.get`，无重试、无限速、失败不写日志，
     于是「一次瞬时抖动 = 一条素材同步失败 + 一条失败通知」，一次网络波动就产出 169 条通知。
- **修复**（`backend/app/services/platform/tikhub.py`，前端/接口/表结构零改动）：
  - 新增 `_throttle_route(path)`：进程内按 **API path** 排队，最小间隔 `_ROUTE_MIN_INTERVAL=1.2s`
    （按 1 req/s 留 0.2s 余量；`threading.Lock` 先占时间片再在锁外 sleep），**不同路由互不阻塞**；
  - `_get()` 有界重试：最多 4 次尝试、退避 `1.5s → 4.0s → 8.0s`，只对 `httpx.TransportError`
    （SSL EOF / 连接重置 / 读写超时）与 HTTP `429/500/502/503/504` 重试；**4xx 永久错误立即抛**（不浪费额度）；
    （先按 3 次尝试实现，回补时实测仍有 3 条撞进代理抖动窗口而失败，故加到 4 次）
  - 重试 `warning`、最终失败 `error` 写日志（R-133 logger）；错误消息保留 `TikHub 请求失败:` 前缀并追加「（已重试 3 次）」，
    通知里可直接看懂，不再是一句裸 SSL 错误。
- **验证**：`scripts/verify.sh` 全绿（ruff + mypy + pytest **320 例**（新增 6 例：SSL EOF 重试成功 / 429 重试成功 /
  400 不重试 / 重试耗尽消息与次数 / 无 key 不发请求 / 同路由排队且不同路由不阻塞）+ 前端构建 + 文档一致性 29 表/123 路由）。
  真实链路冒烟（重启后的后端进程，新代码）：报障那条素材 1570 `POST /api/platform/posts/1570/sync` → 200「单条同步完成」；
  `GET …/comments/refresh` 两次均 200 并在库里落评论；直连 2 条真实抖音作品各取回 20 条评论无 429/SSL 报错；
  限速器实测同路由背靠背第二次等待 **1.202s**。
- **169 条失败素材已回补（作者确认「评论+指标，缺视频/转写才补齐」后执行）**：
  169 条失败任务对应 **100 条云端作品**（92 条本就有素材、82 条已有评论）。逐条 `POST /api/platform/posts/{id}/sync` 回补，
  期间撞上代理抖动窗口的用后续轮次补跑，最终 **100/100 作品的单条同步任务状态 done**；评论覆盖 97/100
  （3 条平台本就没有评论）、本地素材 97/100（其中 411/441 与另一平台帖同属合并作品 343，素材在作品级已存在；
  1594 抖音返回「无可用视频源」，属视频本身不可取）、转写 97/100。今日 TikHub 额度 414/2000。
  - **回补过程本身就是修复效果的实测**：日志里出现 `TikHub 请求失败，1.5s 后重试（第 1/2 次）：ConnectTimeout / ReadTimeout`
    后紧接着 `HTTP/1.1 200 OK` —— 这些请求在修复前会直接判失败并推通知，现在自动恢复。
  - 代理抖动窗口内（09:59–10:55 之间多次、每次数分钟）重试仍会耗尽并如实报错：
    3 次尝试期间实测 60 条里有 3 条失败，故把上限提到 **4 次尝试（退避 1.5s→4.0s→8.0s）**；这类持续数分钟的抖动
    不是重试能覆盖的，需要作者处理代理节点。
  - 回补期间我重启过后端两次（加载新代码），产生了 2 条「服务重启，任务被中断」通知；相关转写任务已重跑成功。
- **未做（需作者决策）**：不擅自改代理设置（是否走代理由网络环境决定）；1594 这类「平台端无视频源」的作品无法补。

## [M139 / R-150] 2026-09-12 — 口播脚本编辑区换 Tiptap v3 块编辑器（保持 Markdown 存储）
> 作者：「有那种类似于 notion 开源组件吗，嵌入进我这个系统，我现在这个富文本使用不方便」。
> 反问后作者确认：**Tiptap v3** + 官方 `@tiptap/markdown` 往返、**只换 DraftsView 口播脚本这一处**、
> **保持 `drafts.script` 为 Markdown**（后端零改动）。

- **新增** `frontend/src/components/ScriptEditor.vue`：Tiptap v3 块编辑器，对外仍是 Markdown 字符串
  （`v-model` ↔ `props.modelValue`）；扩展 = StarterKit（含 Link/Underline）+ Image + Placeholder
  + TableKit + TaskList/TaskItem + `Markdown`；`onUpdate` 用 `editor.getMarkdown()` 回写，
  外部换稿用 `setContent(..., { contentType: 'markdown', emitUpdate: false })` 且先比对避免光标跳走。
- **改造** `DraftsView.vue`：`defineAsyncComponent` 懒加载编辑器（Tiptap/ProseMirror 不进首屏，
  实测独立 chunk 507KB / gzip 160KB，入口 chunk 353KB 未变）；删掉自研 `wrap/linePrefix/insertHr/insertLink/onImage`
  与 `textarea().selectionStart` 拼接逻辑（-100 行）；「预览」按钮保留，仍走 `markdown-it`（与草稿列表同一渲染器）。
- **插图**：工具栏 / 粘贴 / 拖拽三条入口都走原有 `uploadImage()`（`POST /api/uploads/image`），存 URL 不存 base64。
- **为什么补表格/任务列表扩展**：StarterKit 不含表格，缺了会导致「打开含表格的稿 → 保存」把表格整块丢掉
  （实测原样吞掉）。补齐后：表格 GFM 往返保留（仅多余空行/对齐空格被规范化）、任务列表逐字一致。
- **保真性验证（可复现）**：用与组件完全相同的扩展集在 Node 里跑 `MarkdownManager` 往返
  ① 库里 18 篇历史 AI 稿 → **18/18 逐字一致**；② 语法矩阵（标题/粗斜/删除线/有序无序/嵌套列表/引用/代码块/
  分隔线/链接/图片/硬换行/表格/任务列表）逐字一致（表格仅空白规范化，二次往返稳定不漂移）。
- **浏览器端到端（Chrome headless + puppeteer-core，拦截 PATCH 不写库）**：15/15 通过——载入库存正文、
  占位提示、加粗/H2/列表/引用/表格按钮生效、「预览↔返回编辑」内容不丢、保存 payload 仍是 Markdown
  （`**重点**` / `## 小节标题` / `- 第一条` / `> 引用内容` / GFM 表格）且字段齐全。
- **已知限制**（不改行为，仅留档）：行内 HTML（如 `<br>`）会被 Markdown 序列化转义成 `&lt;br&gt;`；
  历史稿中无此内容，`markdown-it` 也一直是 `html:false`。
- 门禁：`scripts/verify.sh` 全绿（ruff + mypy + pytest **314 例** + 前端 lint 0 error + 构建 + 文档一致性 29 表/123 路由）。

## [M138 / R-149] 2026-09-12 — 下线「需求管理」网页（保留需求归档与 AI 查需求工具）
> 作者：「需求管理这个菜单不用了」。按询问确认的范围 **A（正式下线网页）** 实施，沿用 R-136 下线复盘时
> 「不留死代码」的口径。

- **前端删除**：`App.vue` 菜单项、`router.js` 路由、`views/RequirementsView.vue`（构建 0 error）。
- **后端删除**：`api/requirements.py`（4 条路由）、`schemas/requirement.py`、`main.py` 的 router 注册；
  `requirements_service` 只保留 `list_requirements`；`core/requirement_file` 只保留 H1 解析
  （删掉只服务「网页新建」的 `next_requirement_id` / `STATUSES` / `ID_RE` 及其单测）。
- **保留**：`requirements/R-xxx.md` + `README.md`（工作流事实源，AGENTS.md 强制、`verify.sh` 校验、
  `backup.sh` 快照）、AI 对话的 `list_requirements` 工具（问「R-146 是什么需求」仍能答），
  以及 R-148 的标题清洗与「真实归档全量」护栏（AI 读归档同样受益）。
- 口径同步：`docs/API.md` 删 4 条路由（**127 → 123**，`check_doc_consistency.py` 实测一致）、milestones。
- 死代码检查：全仓无 `RequirementsView` / `api/requirements` / `next_requirement_id` 残留引用。
- 测试：删掉随页面一起消失的 2 条页面样式契约用例；总数 **315 例**；verify 全绿。
- 须知：下线后**网页不能再登记/改状态**；新需求按 AGENTS.md 既定流程由 AI 直接写入归档文件（不受影响）。

## [M137 / R-148] 2026-09-12 — 需求管理页整页横向溢出修复（真实布局修复，非隐藏）
> 作者反馈：「需求管理这个页面，ui都超出了浏览器边界了」。第一版只做了「换行 + 外套滚动容器」，
> 被作者当场指出 **「你这只是单独溢出隐藏了」** —— 用 headless Chrome 量了渲染宽度，确认作者是对的。

**实测（headless Chrome 量 DOM 尺寸）**
| | 修复前 | 第一版（只加 wrap） | 最终（固定列宽） |
|---|---|---|---|
| 表格宽度 | 1067px | **1067px（恒定）** | **878 / 775 / 575 / 675（跟随容器）** |
| 表格内溢出 | — | **189～492px（要横向滚动）** | **0** |
| 页面溢出 | >0 | 0 | 0 |

**两个根因**
1. **数据侧**：145 条需求里 108 条标题被文件名 slug 污染（`# R-001-HISTORY-IMPORT: 中文标题`
   被解析成 `-HISTORY-IMPORT: 中文标题`），是 33 字符无断点 ASCII。
2. **布局侧（主因）**：需求表是 `table-layout: auto`，单元格上又有内联 `min-width`，
   各列实测宽度 `编号 54 / 标题 180 / **状态 805** / 摘要 29` —— **「状态」下拉那一列独吞 805px**，
   把表格推到 1067px，比容器（1440 视口下 878px）宽 189px。

**修复**
- 解析层 `_parse_headline()`：剥掉老式 H1 里的 slug（保守规则：仅当 ID 后紧跟 `-` 且 slug 以冒号结尾；
  新式 `# R-110 标题` / `# R-141: 标题` 不受影响），不改任何需求文档原文。
- 布局层：需求表改 **`table-layout: fixed`** + 显式列宽（编号 76px / 标题 28% / 状态 132px / 摘要自适应），
  去掉会撑宽列的内联 `min-width`，下拉框 `width: 100%` 填满本列 → 表格恒等于容器宽，**不需要横向滚动**。
- 兜底层（保留但已不触发）：`.table th/td { overflow-wrap: anywhere }` 让长串在列内换行；
  `.table-wrap { overflow-x: auto }` 作为极窄屏的最后防线。
- **顺带全站扫描**（headless Chrome，1440/1100 两档）：`/home /videos /creators /benchmark /drafts
  /persona /prompts /chat /requirements` **页面溢出全为 0**；其中首页时间线 `.tl` 与提示词页 tab 条
  是**设计上的内部横向滚动**，不属缺陷。

**测试**：`tests/test_r148_requirements_title.py` 扩到 7 例 —— 除标题清洗（含对真实 `requirements/`
全量跑的护栏）外，新增**固定列宽契约**（必须有 `table-fixed`/`table-layout: fixed`/显式列宽/下拉 100%，
且**禁止再出现内联 `min-width`**），防止退回「auto 布局 + 撑宽 + 藏滚动」。总数 **317 例**。

## [M136 / R-147] 2026-09-12 — AI 对话升级为通用型 agent（P0 多步可见 + P1 只读 SQL + P2 写操作确认）
> 作者问「有办法让 ai 对话像个通用型 agent 吗」，在 P0/P1/P2/P3 四档方案里确认 **P0+P1+P2 都做**（P3 沙箱跑代码明确不做）。

**P0｜多步与过程可见**
- `ChatService.reply(..., conversation_id, on_step)`：回合数 / 工具调用总次数 / 墙钟上限都走 `.env`
  （`ECHO_AGENT_MAX_ROUNDS=8` / `ECHO_AGENT_MAX_TOOL_CALLS=16` / `ECHO_AGENT_TIMEOUT_SECONDS=120`）；
  **到限不再抛「对话在多次工具调用后未收敛」**，而是补一条系统提示让模型带着已有数据收尾作答。
- `api/chat.py::/stream` 改为「后台线程跑 agent + 队列转发 SSE」：每一步工具调用实时下发
  `event: step`（调用名/参数 → 结果摘要），前端渲染成步骤条；回答仍按打字机节奏发。
- `ChatView.vue`：助手气泡里显示步骤条（`调用 sql_query …` / `sql_query → 查到 1 行`）。

**P1｜只读 SQL（能答任意数据问题）**
- 新增 `app/core/analytics_views.py`：启动时幂等重建 **8 个只读视图**
  （`v_videos`/`v_drafts`/`v_feedback`/`v_persona_tags`/`v_topics`/`v_ideas`/`v_metrics`/`v_platform_posts`），
  **明确排除** `app_kv`（含明文模型 Key）、`ai_prompts`（提示词正文）、`chat_*`、`schema_migrations` 等敏感/内部表。
- 新增 `sql_query` 工具 + `app/services/chat_sql.py`，四层护栏：① 只读连接（`mode=ro` + `PRAGMA query_only=1`）；
  ② 只允许单条 `SELECT`/`WITH`（拒 `;` 多语句与全部写/管理关键字）；③ **表引用必须是视图白名单**
  （正则抽 `FROM`/`JOIN` 标识符后校验，连子查询偷查原表也挡住）；④ 自动补 `LIMIT ≤200`、单元格截断、
  5s 超时（progress handler 中断）。返回 `{columns, rows, row_count, truncated, sql}`。
- 系统消息注入**视图 schema 卡片**（视图名 + 真实列名 + 中文说明，含「platforms 是 JSON 用 LIKE 判平台」这类提示）。

**P2｜写操作人机确认（可审计）**
- 新增 `agent_actions` 表（第 29 张表）+ `app/services/agent_actions.py`：写工具**只登记提案**
  （`pending` + 影响范围 `preview`），作者在对话里点「确认执行」后才真正落库；取消则不动任何数据。
- 写工具从「直接执行」改为「提议」：`generate_draft`、`rework_draft`、`set_draft_status`
  （used/archived/deleted/draft；删除是软删可恢复）。系统规则明确要求模型**不得声称已完成**。
- 新接口：`GET /api/chat/actions`、`POST /api/chat/actions/{id}/confirm`、`POST /api/chat/actions/{id}/cancel`
  （API.md 路由 124→**127**）。前端渲染「⚠ 待你确认」卡片（动作 + 预览 + 确认/取消 + 执行结果/失败原因），
  刷新或切会话后仍能重新挂载。
- 顺带把「建占位稿 + 入队双模型讨论」抽到 `services/draft_flow.py`，供「AI 生成」按钮与 agent 写操作共用
  （原来只写在 API 层，别处复用不了）。

**验证（真实调用）**
- P0+P1：一次提问里模型**自己选择** `sql_query` 并写对 SQL —— 4 个 `event: step` 事件，答案与库完全一致
  （素材 292 条；草稿 22 篇 = draft 8 + used 1 + archived 4 + deleted 9）。
- P2：说「把草稿 22 标记为不采用」→ 只产出待确认提案（库中状态**仍是 draft**），确认后变 `archived` 并写审计
  （`agent_actions`：action/status/result/created_at/decided_at）；随后已还原为 draft。
- 测试：新增 `tests/test_r147_chat_agent.py`（27 例，含 10 条 SQL 越权用例与「到限必须收尾作答」）；
  总数 **310 例**；verify 全绿。

## [M135 / R-146] 2026-09-12 — AI 对话「瞎回复」修复：工具暴露总数 + 程序固定的数据使用规则
> 作者反馈：「现在项目中的ai对话功能，完全就是瞎回复」。

**复现（真实调用，非推测）**
| 提问 | 修复前 | 数据库真值 | 修复后 |
|---|---|---|---|
| 素材库一共有多少条视频？ | **50 条** | **292 条** | **292 条** ✅ |
| 我一共有多少篇脚本草稿？ | **10 篇**（还把 id 当编号列了一串） | **22 篇** | **22 篇** ✅ |
| 抖音的素材有多少条？ | — | 276 条 | **276 条** ✅ |

**根因**：`_search_videos` / `_search_drafts` 只返回**截断后的列表、不带总数也没有"还有更多"标记**
（`limit` 默认 10、封顶 50）→ 模型无从知道自己在看一页，就把**取回条数当成了总数**。
`get_metrics_summary.top_videos` 也切到前 10 条且无总数，同类缺陷。
（对照：`get_persona` 返回 43 条与库一致；问「帮我把最近那篇草稿删掉」会正确拒绝并说明边界 —— 说明工具本身与权限边界没坏。）

**修复**
- 分页类工具统一返回 `{total, returned, truncated, <items>}`：`search_videos`、`search_drafts`
  （`total` 是**筛选后**的真实总数，用 `q.count()`）；`get_metrics_summary` 增加 `video_total`
  并附 `top_videos_note` 说明「只是前 10 条」。
- 新增 `chat_service.TOOL_DATA_RULES`：**程序固定**的「工具数据使用规则」，由 `reply()` 追加在系统消息末尾
  （不放进 `ai_prompts`，所以提示词优化改不到）：① 数量/统计只能引用 `total`，绝不能把列表长度当总数；
  ② 只依据工具返回的数据作答，没返回的数字/标题/日期不要编造，查不到就说查不到；③ 引用条目用真实标题与 id。
  同时更新 `prompt_contract.CONTEXT_NOTES["chat"]`，告诉优化器这段由程序注入、不要重复写。
- 顺带修一个越权上下文 bug：`/api/chat`（非流式）用 `_last_history(db, None)` 时**不过滤会话**，
  会把所有会话的历史混在一起喂给模型 → 现在显式限定 `conversation_id IS NULL`（遗留单线程）。
- 测试：新增 `tests/test_r146_chat_grounding.py`（12 例：total 是真实总数、跟随筛选、封顶但仍给全、
  契约测试「分页入口都必须暴露 total」、系统消息含固定规则且不在 `ai_prompts` 里、历史不跨会话、时间正序）；
  总数 **283 例**；verify 全绿。

## [M134 / R-145] 2026-09-12 — 一键「打包 → 上传 → 启动 → 自动增量升级」
> 作者澄清真实诉求：「我把这个版本打包上去后，后续我有新版本直接打包部署上去启动就会自动增量新增字段和表」。

- **机制本来就成立**（R-144 已具备）：启动时 `create_all` 自动建**新表**；那一版代码里的 `_migrate_*` 自动补**新字段**；
  结构自检 + 老库升级测试保证「漏写迁移」会被抓住。本次补的是这条链路上缺的两块。
- **升级前自动备份（新）**：`core/schema_guard.pending_upgrade()` 在 `init_db()` **之前**判断是否有待应用的结构变更
  （库文件不存在=全新安装→跳过；结构已最新→跳过，即重复启动不改数据），有变更则
  `auto_backup_before_upgrade()` 用 SQLite 官方 backup API 备份到 `data/backups/pre_upgrade/<时间戳>.db`
  并做 `integrity_check`，保留最近 5 份；**备份失败只告警不阻断启动**（宁可先起来也别停服）。
  启动顺序变为：**判断待应用变更 → 自动备份 → 升级 → 结构自检**。
- **`scripts/release.sh`（新）**：用 `git archive HEAD` 打包 → `dist_release/echo_<版本>_<时间戳>.tar.gz`。
  只含**被 git 跟踪**的文件，天然排除 `.env`（密钥）/`data/`/`node_modules/`/`.venv/`；
  工作区有未提交改动**直接拒绝打包**（防止发半成品）；打包后校验关键文件齐全 + 反向断言不含密钥/数据。
- **`scripts/update.sh`（重写为部署流程）**：① 升级前备份 → ② `git pull`（解包部署可 `SKIP_PULL=1`）→ ③ 构建 →
  ④ 启动 → ⑤ 健康检查（用容器内 python，不依赖宿主机 curl）→ ⑥ 打印库结构版本并断言结构一致；**任一步失败即非零退出**。
- `.gitignore` 增加 `dist_release/`（打包产物不入库）。
- 测试：`tests/test_r144_schema_guard.py` 新增 8 例（待升级判断的三种情形、备份可校验且含真实数据、
  只保留 5 份、**完整复现「老库+新代码→先备份→再升级→重启不重复备份」**、发布包不含密钥/数据、
  `update.sh` 步骤顺序）；总数 **271 例**；verify 全绿。
- 实测：用**真实生产库副本**跑完整链路（打包 → 解包 → 老库 → 启动），日志确认「检测到待应用的结构变更 → 已自动备份 → 结构自检通过」。
  ⚠ 未验证：本机 Docker daemon 未启动，`docker compose build/up` 这一步未在本地实测。

## [M133 / R-144] 2026-09-12 — 上线部署加固：镜像带脚本 + 启动结构自检 + 老库升级测试 + 迁移记账
> 作者准备上线，追问「后续增量上线怎么办，新表/新字段怎么办」。查证后确认 4 个缺口，作者要求全做（A/B/C/D）。

**查证到的 4 个缺口**
- **A**：`Dockerfile` 与 `docker-compose.yml` 都没有 `scripts/`（grep 计数 0），而 `scheduler._backup_job`
  每天 02:30 会调 `/app/scripts/backup.sh` → 每晚报「备份脚本不存在」，**每日备份永不执行**（= 没有回滚预案）。
  顺带发现：镜像里**没有 `.dockerignore`**，构建上下文会把宿主机的 `frontend/node_modules`（192M）带进去，
  `COPY frontend/ ./` 会覆盖镜像内 `npm install` 装的 Linux 版 esbuild/rollup → **前端构建必然失败**；
  健康检查用 `curl` 而 `python:3.12-slim` 没有 curl → 容器会永久 unhealthy。
- **B**：`create_all` 不给已存在的表补列（所以有 24 个手写 `_migrate_*`），漏写迁移只能在运行时 `no such column` 才暴露，启动毫无提示。
- **C**：pytest 全部用**全新库**（直接建出最新结构），漏写迁移在本地 100% 绿，上线才炸。
- **D**：没有迁移记录，排障只能人工 `PRAGMA table_info` 比对，不知道库升到哪一版。

**修复**
- **A**：`Dockerfile` 加 `COPY scripts/ ./scripts/` + `chmod +x`；新增 `.dockerignore`（排除 `node_modules/.venv/data/.git` 等）；
  健康检查改 python urllib + `start_period: 40s`；`scripts/backup.sh` 改为**环境变量优先、其次 `.env`**
  （容器里没有 `.env` 文件，只有注入的环境变量）。
- **B**：新增 `app/core/schema_guard.py::missing_schema(bind)` + `run_startup_check(bind)`：启动时把
  「模型声明的表/列」与实际库对一遍，缺了 → 日志 error（写明「多半是加了字段忘了写迁移」）+ 站内通知
  `schema_check` + 落 `app_kv`；**内部任何异常都吞掉，绝不阻塞启动**。
- **C**：新增 `backend/tests/fixtures/schema_baseline.sql`（生产库**结构快照**，27 表，只含 schema 不含数据）
  + `tests/test_r144_schema_guard.py::test_upgrade_from_prod_snapshot_adds_everything`：
  用快照建库 → 跑 `init_db()` → 断言「模型每一张表、每一列都存在」。**漏写迁移今后会直接红。**
- **D**：新增 `schema_migrations` 表（28 张）+ `record_migration` / `migration_status` / `ensure_baseline`；
  首次运行写基线 `baseline_pre_r144`；启动日志打印「结构自检通过：N 张表；库结构版本=…」。
- 文档：`AGENTS.md` 技术栈同步；`docs/DATABASE.md` 27→28 张 + `schema_migrations` 章节。

**验证（都是真实执行）**
- **用真实生产库副本（61MB）演练老库升级**：`init_db()` 后结构自检通过、28 张表、库结构版本=`baseline_pre_r144`。
- **故意漏写迁移的演练**：在同一副本上 `ALTER TABLE drafts DROP COLUMN tags` → 启动自检 `ok=False`、
  日志给出可读原因、站内通知 1 条、结果落 `app_kv`（证明护栏真的会响）。
- 测试：新增 `tests/test_r144_schema_guard.py`（12 例，含镜像/构建契约与老库升级）；总数 **263 例**；verify 全绿。
- ⚠ **未验证**：本机 Docker daemon 未启动，`docker compose build` 没能在这里真跑 —— 请在 NAS 上首次构建时确认
  （重点看前端 build 阶段是否成功，这正是不加 `.dockerignore` 会炸的地方）。

## [M132 / R-143] 2026-09-12 — 各功能 LLM 预算做成可配置（AI 设置内，保存即生效）
> 作者在选定「保留显式上限、按实测定标」方案 A 后，同意把各功能预算也做成可配置项（「要」）。

- 新增 `services/budget_settings.py`：预算的**唯一事实源**。`SLOTS` 定义 9 个可配置项
  （脚本初稿 12000 / 评审 14000 / 修订与自检收口 16000 / 对标洗稿 12000 / 转写校对 12000 /
  人设归纳合并 8000 / 提示词优化 8000 / AI 对话 8000 / 对标可讲分析 4000），
  全部存 `app_kv` → **保存即生效**；`save_budgets` 校验「未知键 / 非整数 / 越界」并给可读原因；
  `reset_budgets` 一键回默认。
- **下限与标定分层**：厂家下限 `min_max_tokens` 从 12000 退回 **4000**，定位为**安全网**
  （只兜「有人随手写 300」）；「每个功能要多少」改由 `SLOTS` 按任务标定。
  生效值 = `max(设置, 下限)`，界面显示**真实生效值**，不制造「填了 500 却按 500 跑」的错觉。
- 调用点全部改读配置：`debate`（初稿/评审/修订/收口 + 洗稿初稿）、`persona._llm_merge`、
  `ingest.correct_transcript`、`prompt_service.optimize`、`benchmark`（可讲分析 ×2、洗稿 ×2）、
  `chat_service.reply`（含工具调用）。`db=None` 的调用点（人设提炼线程池）会自己开短连接读配置。
- 接口：`GET/PUT /api/settings/models` 增加 `budgets`/`reset_budgets`（**不新增路由**，仍是同一个「保存即生效」按钮）。
- 前端「AI 设置 → 模型设置」新增「推理预算（高级）」区块：每项数字输入 + 默认值/生效值/已改标记 + 说明 + 一键恢复默认。
- 护栏调整：`tests/test_r142_thinking_budget.py` 拆成「下限是合理安全网（2000～12000）」+
  「长输出功能（初稿/评审/修订/洗稿/校对）的默认预算必须 ≥ 实测最坏 8023 × 1.2 余量」两条，
  避免「下限过高把各功能配置压平」这类回归。
- 测试：新增 `tests/test_r143_budget_settings.py`（10 例：默认值/保存回读/下限抬升/恢复默认/
  无会话读取/非法输入 4 种/坏 KV 兜底/**脚本生成真的用了配置的预算**）；总 **251 例**；verify 全绿。

## [M131 / R-142] 2026-09-12 — 推理预算定标（修「评审总是降级」）+ 瞬时网络错误重试 + 单次调用时限统一
> 作者反馈：「模型1 调用失败，已降级模型2（脚本生成）… 推理预算被思考吃光（思考 5986 字、正文为空）
> …（思考 11950 字、正文为空）… 为什么总是这样」。查证后确认是 R-139 把预算定标定低了。

**量测（真实调用，同一份评审提示词 2974 字 + 同一篇真实脚本）**
| max_tokens | finish_reason | 思考 | 正文 | reasoning_tokens |
|---|---|---|---|---|
| 4000 | length | 5961 字 | **0** | 4001 |
| 8000 | stop | 9869 字 | 833 字 | 6493 |
| 12000 | stop | 9649 字 | 1034 字 | 6296 |
| 16000 | stop | 12215 字 | 1031 字 | 8023 |
| 4000（复测） | stop | 3945 字 | 1286 字 | 2418 |

**根因**：同一步骤的思考量在 **2418～8023+ tokens** 间大幅波动，而首轮预算取 DeepSeek 下限 4000、重试翻倍到 8000
—— 正好落在波动区间内，所以「有时成功、有时两次被截断后降级」（库里 8 篇带模型信息的草稿有 5 篇降级过）。
另外两点也在放大问题：连接级瞬时错误（`Connection reset by peer`）当时**不重试**就直接降级；
`read=180` 在不设 stream 时等价于「单次调用总时限」，预算抬高后 Kimi 实测跑到 **180.3s** 正好被误杀。

**修复**
- 厂家下限按量测定标：DeepSeek 4000→**8000**、Kimi 6000→**10000**（覆盖实测最坏值，人设提取等调用方一并受益）。
- 各步预算按量测定标（`debate.py`）：初稿 3200→**12000**、评审 3000→**14000**、修订 4200→**16000**、自检收口 →**16000**（洗稿路径同规格）。
- `MAX_TOKENS_CEILING` 16000→**32000**，翻倍重试仍有余地。
- 连接级瞬时错误（ConnectError/ReadError/WriteError/RemoteProtocolError）同类重试 1 次再降级；**超时不重试**（避免等待翻倍）。
- `llm.py`：`read` 超时与墙钟取同一个值 → 单一语义「**单次调用最多 `ECHO_LLM_TIMEOUT_SECONDS`（默认 600s）**」，
  既不再误杀推理模型的长调用，也保留对「一直有零碎字节但永不结束」的兜底。
- `debate.py` 留痕修正：初稿的 `actor` 改记**实际出结果**的槽位（此前记配置槽位，内部降级后与事实不符）。
- 测试：`tests/test_r139_llm_router.py` 预算断言改为从 `VENDORS` 读取；新增「连接错误重试一次」「超时不重试」
  「read 超时=墙钟」3 例；总 **238 例**。

**补充（同日，作者选定「保留显式上限」方案 A 后）**
- 各步预算抽成具名常量（`debate.BUDGET_INITIAL/BUDGET_CRITIQUE/BUDGET_REVISE`），并新增
  `tests/test_r142_thinking_budget.py` **校准护栏**：厂家下限与各步预算低于「实测最坏 8023 tokens × 1.2 余量」直接判红
  —— 护栏上线即抓到 DeepSeek 下限 8000 比实测最坏值还低 23 tokens，已一并抬到 **12000**（Kimi 对齐）。

**验证**
- 评审步骤按新预算连跑 4 次：正文 984 / 681 / 881 / 955 字，**0 次截断**（旧预算下约一半被截断）。
- Kimi 修订在 12000 预算下实测 180.3s / 106.8s —— 证明 `read=180` 确实会误杀，`read=600` 正常。
- 真实跑一轮双模型讨论（生成方 Kimi + 评审方 DeepSeek，1 轮）：`quality.fallback == false`，两方都按配置完成，
  自检通过、口癖覆盖 0.875，无新增降级通知。

## [M130 / R-141] 2026-09-12 — 邮件次要通道化：配置校验 + 发信失败不炸穿流水线
> 发现于 R-140 的端到端验证：作者要求手动触发每日流水线，结果**3 条候选 + 3 篇脚本都生成落库了**，
> 但最后一步发邮件抛 `UnicodeEncodeError` → 整轮被置 `failed`、`generated_count=0`；失败告警邮件走同一路径也失败。

**根因（两层）**
- **配置层**：`.env` 里 `ECHO_SMTP_AUTH_CODE=授权码（非登录密码）`、`ECHO_MAIL_TO=接收邮箱` 是把
  `.env.example` 的说明文字当值留着（值 100% 非 ASCII）。`smtplib` 在 `server.login()` 里
  `initial_response.encode('ascii')` 炸在位置 17-26（正好是授权码前 10 个字符）。
  另发现 `ECHO_WEB_BASE_URL` 的行尾注释被整串吃进值里（AGENTS.md 早已要求「行尾注释必须换行书写」）。
- **代码层**：`_send` 只判断「三个值非空」就当配置可用，占位符一路走到 `login()` 才炸；而它在流水线 `try` 里，
  异常直接让整轮 `failed`。

**修复**
- 新增 `notify.mail_config_problem()`：提前校验「缺失 / 非 ASCII（占位符） / 非法邮箱」并给出可读原因。
- `_send`：配置非法或发送异常都**记日志 + 返回 False**，不再向上抛；中文主题改 RFC2047
  （`Header(subject,"utf-8").encode()`，纯 ASCII 保持原样）；正文改 `msg.as_bytes()`，
  避开 `sendmail(str)` 的 ASCII 编码路径。
- 流水线把邮件当次要通道：稿子生成成功即 `status=done` + `generated_count` 保留，
  邮件问题写进 `run.error` 并经 `_pipeline_task` 带进**完成通知**（站内可见「已生成 N 篇脚本；注意：邮件未发送：<原因>」）。
- 测试：`tests/test_r140_pool_ideas.py` 增 4 例（配置校验、`_send` 不抛且不连 SMTP、中文主题编码、
  邮件失败时流水线仍 done 且计数保留）。真实进程复现验证：`send_daily_digest` 由「抛异常」变为「返回 False + 可读原因」。
- **待作者处理（代码改不了）**：`.env` 的 `ECHO_SMTP_AUTH_CODE` / `ECHO_MAIL_TO` 需填真实值，
  `ECHO_WEB_BASE_URL` 需去掉行尾注释。

## [M129 / R-140] 2026-09-12 — 灵感池入池修复与限量 + 每日篇数口径对齐
> 起因：作者发现首页「灵感池」没数据。查证后确认是 **R-093 的回归**（非 R-138/R-139 引入），
> 作者确认「要（每日队列同步也进池）」「限量」，并要求一并做「篇数口径对齐」与「端到端验证」。

**根因（已查证）**
- 全项目只有 `_collect_comments()` 会写 `topic_ideas`；它只在 `with_comments=True` 时被调用，
  而 R-093（2026-09-06）把「daily + 带媒体」改成逐素材队列：`queue_mode = with_media and scope=="daily"`
  → `with_comments = not queue_mode`。**所有每日同步路径都是「daily + 带媒体」**（定时 `run_daily_sync_all`、
  博主页「同步前15条」），于是全部跳过 `_collect_comments`；队列里的 `sync_post_comments()` 只写
  `platform_post_comments`，**从不写灵感池**。数据佐证：`topic_ideas` 787 行（09-05：81、09-06：706、之后 0 行），
  而今天同步日志写着「采集评论 124/163 条」——注释「评论也由队列逐条采集」只兑现了入库，漏了进池。
- 热榜半边为空是另一回事：热榜靠每日流水线 `fetch_and_store()` 或首页「抓取更新」刷新，
  该库 `pipeline_runs` / `topic_candidates` 均为 0 行（流水线从未跑过），`hot_topics` 停在 09-08 而接口只查当天。
  手动 `POST /api/topics/refresh` 实测恢复（fetched 161）——属运行环境问题，非代码缺陷。

**修复**
- 「评论 → 选题池」抽成唯一实现 `pool_ideas_from_comments()`：`_collect_comments()`（全量/每周）与
  `sync_post_comments()`（队列/单帖）都调用它，杜绝「一边有一边没有」的再次发生。
- **进池限量**（`.env` 可覆盖）：单帖最多 `ECHO_POOL_IDEAS_PER_POST=8` 条（按点赞降序）、
  单博主每天最多 `ECHO_POOL_IDEAS_PER_DAY=40` 条；`0` = 不限量。仍保留「标题 ≥4 字」、
  按 `(source,title,snapshot_date)` 去重、重复出现点赞取大。
- **可观测**：同步任务说明新增「灵感池新增 N 条」（`sync_account` / `run_sync` / `run_daily_sync_all` 与
  payload `pool_ideas`），不再只有「采集评论 N 条」。
- **每日篇数口径对齐**：`run_daily_pipeline` 的组候选与生成切片统一用 `model_settings.topics_count(db)`
  （此前组候选用 `.env` 的 `pipeline_topics_count`、生成用 `app_kv`，会出现「候选 3 条、实际生成 1 条」）。
- 测试：新增 `tests/test_r140_pool_ideas.py`（10 例：队列模式进池、非队列不回退、单帖同步进池、
  可关闭、单帖/单博主/按博主隔离限量、0=不限量、去重与点赞取大、篇数口径）；总 232 例通过。

## [M127+M128 / R-138+R-139] 2026-09-11 — AI 设置（模型1/2 槽位）+ 统一模型路由与降级层
> 作者原话：①主模型和副模型改为模型1、模型2，可分别配置厂家/模型/Key；②脚本生成改为「生成方 / 评审方」两个下拉；
> ③除脚本生成外其他 AI 功能默认用模型1，出问题降级模型2，**不能降级后像退化了**；④讨论轮次控制所有自动生成脚本的讨论轮数。
> 另要求：菜单「AI 提示词」→「AI 设置」，其余功能不改；保存**实时生效**。

**模型槽位与设置页（R-138 / M127）**
- 新增 `services/model_settings.py`：厂家目录（DeepSeek / Kimi，加供应商只需加一行）+ 槽位（厂家/模型/Key）+
  ASR 服务商与模型 + 每日篇数，全部存 `app_kv` → **保存即生效（无需重启）**；旧 `generation_model` 自动无感迁移
  （`kimi` → 生成方=模型2），默认 模型1=DeepSeek `deepseek-flash`、模型2=Kimi `kimi-k2.6`，复现原生产行为。
- 新增 `GET/PUT /api/settings/models`（非法配置 400 + 可读原因）；`GET /api/settings/asr` 改读运行时配置；
  旧 `/generation-model` 保留兼容，`random/alternate` 明确 400 下线（作者选择「只留显式生成方/评审方」）。
- 前端「AI 提示词」→「AI 设置」：首 tab「模型设置」（模型1/2 行内选厂家/模型/Key、生成方/评审方、ASR 服务商+模型、
  每日自动生成篇数、保存/重新读取），讨论轮次留在工具栏；**Key 明文存 DB 并可回显**（作者明确接受该权衡，界面提示备份风险）。
- ASR 实时生效：`Transcriber(mode=…, model=…)` 与 `SiliconFlowASR(model=…)` 接受运行时覆盖，转写不再只认 `.env`。
- 每日自动生成篇数改为 `model_settings.topics_count`（Kv > `.env` > 默认），控制双模型讨论的成本（≈ 篇数 × 轮次 × 2 次调用）。

**统一模型路由与降级（R-139 / M128）**
- 新增 `services/llm_router.py`：`snapshot(db)` 取线程安全配置快照；`RoutedLLM` 与 `OpenAIClient` 接口兼容
  （`chat` / `chat_json` / `chat_completion`）；**模型1 主用 → 模型2 降级**，触发条件=报错/超时/空正文/缺契约字段
  （`chat_json(require=(...))`）；主模型「输出不合法」可重试 1 次；降级**可见**：`log.warning` + 站内通知
  （`llm_fallback`，同功能 30 分钟冷却避免刷屏，自己开短连接所以跨线程安全）+ `RoutedLLM.degraded`。
- **参数按厂家归一化**（作者要求「降级后不能像退化」）：不支持 temperature 的推理模型不传该参数；
  `max_tokens` 抬到厂家下限（Kimi ≥3000）——此前 Kimi 拿到小 max_tokens 会把预算耗在思考上返回空正文。
- 接入全部非脚本生成的 AI 功能：人设（逐篇/合并/增量/语义复核）、视频预打标、转写校对、改稿差异、AI 对话（含 tools）、
  提示词优化、金样本评测、对标分析（可讲分析/洗稿初稿/广告判定）→ 默认模型1。
- **脚本生成统一**：`debate.run_debate` 成为唯一路径，手动工作台、一键回炉、灵感池一键、AI 对话生成、
  提示词自测、每日自动生成全部走「生成方初稿 → 评审方 N 轮 → 生成方修订 → 自检收口」，
  轮次取设置（`debate_rounds`，1–10）；初稿用 `generation_user_message`（与金样本回放同一份输入）。
  `Draft.quality` 记录 `models`（生成方×评审方）/`used`/`fallback`/`rounds`/`rounds_done`/`issues`/`passed`/`style_coverage`，
  草稿列表与详情页显示模型组合与「由备用模型生成」标记。
- 新增 `services/model_health.py`：保存模型配置后**异步**跑双模型兼容性自检（3 个极简样例 × 2 槽位，校验文本/JSON 契约），
  结果写 Kv 并由 `GET /api/settings/models` 的 `selfcheck` 回到设置页，不兼容时给出「模型2 在 X 功能上不兼容」告警 + 站内通知。
- **实测暴露并修掉两个真实缺陷（都是「降级后像退化」的真凶）**：
  1. **DeepSeek 也是推理模型**：实测 `max_tokens=1500/3000` 时 `finish_reason=length`、`reasoning_tokens` 吃满预算、
     **正文为空**；4000 才出正文。原 `min_max_tokens=400` 形同虚设 → 提到 4000（Kimi 提到 6000，实测长上下文下
     思考可吃掉 4000+ tokens）。同时把「空正文 + 有思考内容」从「服务故障」区分为 `LLMUnusableOutput`：
     先**翻倍 max_tokens 重试同一模型**，仍不行才降级，并在错误信息里写清「推理预算被思考吃光」。
  2. **httpx read timeout 挡不住长时间挂起**：一次真实评审调用挂了 **39 分钟**才超时（服务端持续吐字节，
     read timeout 被不断重置），「超时降级」形同虚设。`OpenAIClient._post` 改为**流式读取 + 墙钟上限**
     （`ECHO_LLM_TIMEOUT_SECONDS`，默认 600s），每收到一段数据检查是否超期；HTTP 4xx/5xx 与响应结构异常
     也直接转成可读 `LLMError`（通知里能一眼看出是 Key 失效还是限流）。
  3. **流式读取必须用 `iter_bytes` 而非 `iter_raw`**：Kimi 对较长响应返回 `Content-Encoding: gzip`
     （实测 770 字节 gzip / 1401 字节解码后 JSON），`iter_raw` 拿到的是压缩字节 → JSON 解析必然失败。
     **这个坑是「双模型兼容性自检」自己抓出来的**（自检报告 model2 在两个 JSON 契约上不兼容），
     修完自检 6/6 通过 —— 正好证明自检功能本身有效。
  4. **单次「无数据到达」上限要给推理模型留足静默时间**：加了墙钟上限后把 read timeout 收到 30s，
     结果 Kimi 稳定在 40s 被判超时（思考中长时间不吐第一个字节），默认配置（生成方=Kimi）
     每篇都被迫降级 —— 反而制造了「降级」。现固定 `READ_TIMEOUT_SECONDS = 180s`：
     静默超过 180s 才算死连接，整体仍由墙钟 deadline（600s）兜底。复测自动生成路径
     `fallback=False`、`used.gen=model2(Kimi)`、`used.critic=model1(DeepSeek)`、`passed=True`。
- 测试：新增 `tests/test_r139_llm_router.py`（29 例：降级四种触发、输出不可用先抬预算重试、参数归一化与厂家下限、
  墙钟上限/HTTP 错误可读、通知落地、双模型讨论与轮次、运行时篇数、ASR 运行时接线、非脚本功能默认模型1、
  注入 llm 不被路由破坏、gzip 响应解码、read timeout 留足思考静默）；`tests/test_r138_model_settings.py`（7 例）；总 222 例通过。
- **真实链路实测**（非 mock）：双模型兼容性自检 6 次调用全通过（模型1 DeepSeek 0.9–1.5s / 模型2 Kimi 4.9–13.9s）；
  人为把模型1 Key 改错后调 `/api/drafts/angles` → 自动降级模型2 并产出 3 个可用角度（8.5s 正常路径，
  降级路径 29s），站内出现 `llm_fallback` 通知；真实双模型讨论生成 3 篇（生成方 Kimi + 评审方 DeepSeek，1 轮），
  `draft_discussions` 留痕完整（初稿/评审/修订），`Draft.quality` 记录模型组合与降级标记。

## [M126 / R-137] 2026-09-11 — DeepSeek 模型切换到 DeepSeek-V4.1-Flash
- 官方 2026-09-10 发布 V4.1 Flash，规范 API 模型名为 **`deepseek-flash`**（`deepseek-v4-flash` 等仅为临时兼容别名）。
- `.env` / `.env.example` / `config.py` 默认值三处统一改为 `deepseek-flash`；**顺带修掉已停用的旧模型名 `deepseek-chat`**（官方 2026-07-24 停用）。
- 真实调用验证：JSON 模式返回可解析结构；长输出 334 字符 JSON / 286 字脚本无截断（确认 thinking 模式未吃光 token）；应用层 `correct_transcript` 走新模型并正确纠错「面视→面试」。
- 未改动 Kimi 配置、`generation_model` 策略（仍为 kimi）、base_url 与鉴权。

## [M122~M125 / R-133~R-136] 2026-09-11 — 系统体检修复：P0 稳定性 → P1 任务闭环 → P2 正确性 → P3 复盘下线/文档统一
> 起因：对全系统做「闭环 / 描述与实现一致性 / bug」体检，作者要求按 P0–P3 顺序登记并修复。

**P0 稳定性兜底（R-133）**
- **备份修复（此前形同虚设）**：`scripts/backup.sh` 硬编码 `data/echo.db`（不存在），`sqlite3.connect` 会新建空库 → 备份出的其实是 4KB 空库。
  现改为从 `.env` 解析 `ECHO_DB_PATH`（回退 `ECHO_DATA_DIR/echo.db`），源库缺失/校验失败非零退出，备份后做 `integrity_check` + 表数量校验。
  实测：**58,372,096 bytes / 28 张表**，与真实库一致。`scheduler._backup_job` 检查退出码并对失败告警。
- **流水线终态**：`run_daily_pipeline` 失败时置 failed + 邮件告警 + **抛 `PipelineError`**（任务层写 failed + 站内通知，不再谎报「完成」）；
  `running` 超 2 小时视为卡死可重跑（`core.pipeline.is_stale`）；新增启动自愈 `mark_stale_pipeline_runs_on_startup`。
- **最小可观测性**：新增 `core/log.py`；此前全后端**零日志**、53 处 `except` 只 pass/rollback。关键失败路径（任务/定时/备份/inbox/流水线）全部留痕；
  新增 `_alert()` 统一「日志 + 站内通知 + 邮件告警」；`_run_worker` 的失败通知单独 try（通知写失败不再把成功任务改判 failed）。

**P1 任务终态与体验闭环（R-134）**
- 启动自愈 `_cleanup_stale_sync_state`：复位 `sync_jobs` 与账号 `sync_status` 的 running（原来博主页进度条会永久「同步中」）；
  `card_sync` 队列中断时 `_fail_remaining` 把剩余行置 failed（不再永久「排队中… 4%」）。
- `debate_status` **补上漏掉的 `@router.get` 装饰器**（路由此前未注册，前端 404 被静默吞掉）；新增 `clear_debate_state` 清理进度状态与占位稿。
- inbox 改为「先入库 commit 成功再移动文件」，移动失败回滚并留日志（此前会丢素材）。
- `PromptsView` 支持 `#/prompts?key=xxx` 深链（通知点击可定位）；
  **更正**：`DraftsView` 实际已支持 `?id=`（用 `location.hash` 解析），体检中「两处深链都失效」的结论不准确。
- 重启中断任务改为逐条标记 + 汇总站内通知；消费 `persona_incremental_pending` 重新入队；`_rerun_if_pending` 改为「先入队成功再清标记」。

**P2 正确性与成本（R-135）**
- 重复入队判重：转写（同素材进行中→409）、同步（同 scope/账号/博主→409）、媒体补齐（同素材已在队列→duplicate）。
- 预算护栏：新增 `ensure_budget` 预检并在同步/队列每轮调用；`_sync_one_acc` 不再吞 `BudgetExceeded`（此前任务仍报「同步完成」）。
- **生成模型策略生效**：`generate_draft` 不再固定 DeepSeek，改为跟随 `generation_model`（影响每日流水线、灵感池、回炉、AI 对话、提示词自测）。
- 选题池博主隔离：`_comment_candidates` 与 `topic_pool` 按 `creator_id` 过滤（此前对标评论灵感会串进主博主生成）。
- 四维分节分回流：新增 `_dim_examples` 按 hook/pace/ending/style 注入生成范例；修正前端不实文案。

**P3 复盘下线 + 文档统一（R-136）**
- **复盘 ABCD 正式下线**（API/页面已在 R-097 删除）：删除 `services/review.py`、`ReviewReport` 模型与 `review_reports` 表（幂等迁移）、chat 的 `get_review_report` 工具、
  以及 prompt_service/prompt_contract/prompt_eval 中的 review 引用；**赛道雷达保留**并迁到 `services/metrics.radar`。
- 删除 `services/metrics.py` 中无调用方的 `upsert_snapshot/import_snapshots/fetch_daily/series_for_video`。
- 文档口径统一：ARCHITECTURE/README/QUICKSTART/AGENTS 更正「数据看板与复盘（已下线）」、提示词候选（手动）、27 张表、views 10、top15、pytest 183、inbox 路径；
  `API.md`/`DATABASE.md` 头注由「自动生成」改为「人工维护」；删除 milestones 重复的 M117 行。
- **门禁增强**：新增 `scripts/check_doc_consistency.py`（校验表数量/表名 + 路由数量/每条路由是否收录）并接入 `verify.sh`；实测 27 张表 / 122 个路由一致。

**测试**：新增 4 个测试文件（`test_r133_stability` 6 + `test_r134_task_loops` 9 + `test_r135_correctness_cost` 8 + `test_r136_review_sunset_docs` 4），
`verify.sh` 全绿（ruff + mypy + pytest 187 + 前端 lint/build + 文档一致性）。

## [M121 / R-132] 2026-09-10 — 「AI 基于最新素材优化」最小改动：定位说清 + 可改清单 + 长度约束 + 变更说明
- **定位说清**：按钮「AI 基于最新素材优化（候选）」→「**AI 基于真实样本优化（候选）**」（"最新素材"是误导——素材更新会自动注入、无需改提示词）；
  `generation` 卡片增加说明「素材/反馈更新会自动注入，无需改提示词；此按钮只在你想调整**写法与结构**时用」。
- **给优化器正面靶子**：`OPT_SYSTEM` 增加**可改 / 不可改**清单——可改：角色设定、写作或判断方法、结构要求（开场钩子/收尾引导）、篇幅与语气方向、需遵守的原则；
  不可改：作者姓名/身份/经历等具体事实、红线与金句清单、程序解析所需的输出格式与字段（此前只有禁止项，没有正面方向）。
- **长度约束（防膨胀）**：候选总长 ≤ `max(1.5 ×（当前提示词 + 契约段）, 300 字)`；超限按自检失败处理（重试 1 次 → 仍超则丢弃并返回原因）。
- **候选附「变更说明」**：模型按「【提示词】/【变更说明】」格式输出，程序解析后把说明写进候选 `note`（与模型/语料来源并列），
  前端候选面板改为多行展示——不用只看 diff 猜"这版好在哪"。
- 测试：`test_r129_prompt_optimize` 新增 4 用例（变更说明解析 / 长度上限 / 超长拦截重试 / 说明入库且不进正文）；`verify.sh` 全绿（pytest 158）。

## [M118~M120 / R-130 + R-131] 2026-09-10 — 人设↔提示词边界整理 + 提示词降权、重心转向数据侧
- **R-130 边界整理**：提示词页 10 个 key 分「人设引擎（persona_init/merge/updates/compare）」与「生产提示词」两组，人设引擎标注「改这里会影响人设提取质量」；启用人设引擎候选后引导去人设页确认；表达风格/禁用词/金句锚点/风格范本统一标注为「生成时的运行时上下文，由人设页维护，不在提示词正文里」。
- **`drafts.persona_version`**：AI 草稿（生成/双模型讨论/对标洗稿）记录生成时的人设版本；「版本效果对比」新增「跨 N 个人设版本，均分不宜直接横向比」提示，解决归因不纯。
- **R-131 降权**：取消「每 3 条新素材自动产出候选」与「每周日自动产出候选」——改为累计 10 条素材发一条提醒（周任务同样只提醒）；新增「一键优化规则型（预打标/校对/差异/复盘）」手动入口（`POST /api/prompts/optimize-rules`，后台任务，样本不足的 key 自动跳过）。**说明**：原计划的「规则型自动优化开关」改为「手动一键」，避免后台不可见地烧钱。
- **数据侧增强（"像作者"的真杠杆）**：
  - ① **改写稿 few-shot**：把「AI 原稿 → 作者改后」成对样本（优先高分/采用）注入生成上下文，只学改法不抄内容；无成对样本时不注入。
  - ② **风格样本扩容 + 风格范本**：检索条数默认 3 → 可配置 3~8；人设页可勾选「生成风格范本」素材，勾选的必定注入、不参与检索淘汰。
  - ③ **开场/结尾结构模板**：`_best_practice_lines` 升级为 `_structure_templates`——取高表现内容的首句/收尾句做结构模板；无评分反馈时退回真实互动最高的素材转写稿。
- **生成后自检（R-131）**：红线命中 / AI 腔禁用词 / 口癖覆盖率；不达标自动重写 1 次（附失败原因），结果落 `drafts.quality`（attempts/issues/passed/style_coverage），前端草稿接口已带出。
- **打分引导**：生成提交提示与草稿打分处提示「打分是 AI 学你偏好最强的信号」（当前反馈数据为 0，是最缺的一环）。
- 顺带修复：`_best_practice_lines` 先 `limit()` 后 `filter()` 的崩溃问题随本次重构彻底移除（原逻辑并入 `_structure_templates`）。
- 测试：新增 `test_r130_r131_data_side` 13 用例；`verify.sh` 全绿（ruff + mypy + pytest 154 + 前端 lint/build）。

## [M113~M116 / R-129] 2026-09-10 — AI 提示词优化升级：按 key 语料 + 契约自检 + 分层模板 + 金样本评分 + 版本归因
- **按 key 定制语料**（新增 `services/prompt_contract.py`）：generation=人设+风格画像+加权转写稿+反馈；video_tags=「转写稿→真实标注」；correct=「原始转写→校对稿」成对；review=历史复盘报告；diff=「AI 原稿→作者改后」；persona_*=人设档案与逐篇提炼结果；chat=工具清单与权限规则。取不到样本时返回「样本不足，暂不优化」（`/optimize` → 422），不再拿人设腔调语料硬改所有提示词。
- **输出契约固定 + 分层**：每个 key 的契约段由程序在候选末尾拼接（`assemble_candidate`），优化器只能改「角色与任务」段；`validate_candidate` 校验长度预算 / 契约字段 / 是否写死事实（红线原文、「你是 XX 本人」、作者姓名），失败自动重试 1 次后丢弃并返回原因。
- **优化提示词改写**：明确「不得写死作者姓名/身份/传记/红线，这些由运行时动态注入；只给方向盘、不锁死思路、字段结构不得改」。
- **优化模型跟随**「生成模型策略」（Kv/settings 的 `generation_model`；random/alternate 归 DeepSeek）。
- **金样本回放评分**（新增 `services/prompt_eval.py` + 新表 `prompt_evals`）：候选产出后自动以「高表现素材选题 Top5 + 高/低分草稿各 3 条」为金样本，候选与当前版各跑一遍，按格式合法率 / 红线命中率 / 像作者率算综合分，结果落库并在提示词页展示；不支持回放的 key（chat）明确标注原因。
- **版本归因与效果对比**：`drafts` 增加 `prompt_version`（生成时记录启用的提示词版本），按版本聚合草稿数/均分/采用数并在提示词页展示。
- **反馈语料加厚**：打分反馈带四维分节分 +「AI 原稿→作者改后」diff（最强偏好信号）。
- 候选可**拒绝**（rejected 留痕）；历史版本可一键启用（即回滚）。
- **修复**：`generation._best_practice_lines` 先 `limit()` 后 `filter()`，存在当前博主时必抛 `InvalidRequestError`——最佳实践注入一直失效，已修正。
- **实测**：video_tags 候选不再变「人设分身」（评测 100 vs 当前 60）；correct 候选为纯校对任务提示词；generation 候选显式声明「人设/红线运行时动态注入」，不再写死传记与红线；优化模型正确跟随设置为 kimi。
- 测试：新增 `test_r129_prompt_optimize` 16 用例；`verify.sh` 全绿。
- **评测稳健性修复**：评测模型改为与各 key 生产实际使用的模型一致（只有 generation 跟随生成模型策略，其余走 DeepSeek）——
  此前统一用推理模型跑 `correct` 长文本会返回空正文（实测 2/3 样本为空，评分被误判）；回放 `max_tokens` 提高到 6000、
  JSON 类输出允许代码围栏、两版全空时标记「评测无效」而不是给误导性低分。复测：correct 候选 92.5 vs 当前 92.5；video_tags 100 vs 60。

## [M110/M111/M112 / R-128] 2026-09-10 — 人设分析管线升级 + 增量/全量 5% 对齐 + 候选提示词人设化
- 人设分析：逐篇提取（`analyze_one`）的提示词改为「只给方向盘」（角色 + 观察方向；维度/措辞/条数由 AI 自定，程序只解析固定字段）；新增 `persona_merge` 归纳合并层，把近义/重复信号「总结去重」成结构化档案；`persona_tags` 新增 `dimension` 落库（维度→category 映射）。
- 增量对齐：新增 `persona_profile.py` 管线与 `persona_incremental_task`（新增已发布素材入队 / 手动重跑；进行中不重复入队，期间新素材收尾补跑）。每次先「从头全量重算」（全量逐篇提取 + `merge_full`），再算「当前档案 + 新篇」增量；集合覆盖率（近义模糊匹配）+ AI 语义复核（`persona_compare`）均 ≥95% 才通过，否则**自动回退全量结果**并写通知；结果落 `persona_checks`。
- 缓存（作者已确认允许）：逐篇提取结果按「提示词指纹 + 文案 hash」缓存于 `app_kv`；内容未变则复用，结果与从头重算等价，显著降低每次增量的 LLM 成本。
- 候选提示词人设化：`learning_material` 注入归纳合并后的人设档案（含维度）；`OPT_SYSTEM` 改为不锁死 AI 思路、只保留程序解析所需的输出格式。
- 前端：人设页顶部新增「增量 vs 全量对齐（5% 口径）」面板（覆盖率/语义分/是否回退/差异明细/重跑按钮，按后台任务态防重复点击）；人设条目展示与编辑「维度」；AI 提示词页说明更新。
- 新增 `backend/scripts/reset_r128.py`：清空人设档案、校验记录、AI 提示词与逐篇提取缓存，并重新 seed 新版默认提示词（本次已执行并按新管线重跑全量人设）。
- 修复：`PersonaTagUpdate.category` 正则补 `phrase`（原漏掉，编辑金句锚点会 422）。
- 稳健性（真实重跑发现并修复）：全量归纳**优先把「每篇提炼结果」原样喂给模型**（全局视角，65 篇 → 约 48 条），
  而不是先机械摊平成几百条扁平列表（那样模型压不住、输出超 max_tokens 被截断，会退化成几百条原始标签）；
  全局失败/篇数 >120 时才退回「机械近义去重 + 分批归纳 + 再机械去重」，并对落库建议设 150 条防御上限（超限置 truncated）。
- 测试：新增 test_r128_persona_profile（缓存/覆盖率/语义回退/落库/归纳合并/语料注入）共 10 用例，更新逐篇与服务测试；verify.sh 全绿。

## [M109 / R-127] 2026-09-08 — 像我金句库：候选金句单条拒绝 + 一键接受/一键拒绝
- 候选金句每条新增「拒绝」（仅从本次候选移除；候选为每次点「提取」临时生成，不落库）。
- 「像我金句库」标题加「一键接受」「一键拒绝」：一键接受逐条收为锚点（跳过空/重复/已是锚点的句子并提示统计）；一键拒绝二次确认后清空本次候选。
- 纯前端改动；verify.sh 全绿。

## [M108 / R-126] 2026-09-08 — 人设初始化改为逐篇喂 AI + 去重
- persona_init_task 不再把所有转写稿拼进一个大 prompt：每篇非广告转写稿单独调一次 AI（4 路并行，带进度回调，单篇失败跳过）。
- 各篇产出的标签/红线先做规范化去重（去空白/小写），并跳过当前主博主「已确认/待确认」里已有同标签（与 suggest_persona_updates 口径一致；被拒标签允许再次建议）。
- 结果仍以 status=suggested、version=max+1 落库，出现在「待确认建议」供前端确认。
- PersonaService 新增 analyze_one（单篇）并抽公共解析；analyze_initial 保留兼容旧口径。
- 新增 test_persona_piecewise 2 用例（逐篇去重/跳过已存在/广告排除/空转写 noop）；verify.sh 全绿。

## [M107 / R-125] 2026-09-08 — 人设初始化防抖（禁止重复入队）
- 根因：按钮 loading 只覆盖“提交请求”那一下（接口立即返回 task_id），后台任务跑完前按钮已可再点，连点会排队多个 persona_init。
- 后端 POST /api/persona/init：存在 pending/running 的 persona_init 时返回 409，拒绝重复入队。
- 前端 PersonaView：进入页面/任务期间轮询 running persona_init，按钮保持「初始化中…」禁用直至后台完成；方法内加 running 守卫；离开页面清理定时器。
- 新增 test_persona_init 2 用例（进行中 409 / 空闲可启动）；verify.sh 全绿。

## [M106 / R-124] 2026-09-07 — 人设档案：新增/编辑统一弹窗，移除页底手动添加
- 移除页面底部「手动添加」区块。
- 「已确认档案」标题旁新增「新增」按钮，点开弹窗新增档案（标题「新增风格档案」，类别默认风格）。
- 单行「编辑」与「新增」复用同一弹窗：编辑态标题「编辑人设标签」，新增态标题「新增风格档案」；有 id 走 PATCH，无 id 走 POST。

## [M105 / R-123] 2026-09-07 — 人设档案：一键拒绝建议 + 已确认档案多选删除
- 「待确认建议」标题旁新增「一键拒绝建议」（与一键确认并列），把全部待确认建议一次性标为已拒绝（留痕），带确认弹窗防误触；后端新增 POST /api/persona/reject-all。
- 「已确认档案」新增多选模式：右侧中间悬浮按钮同素材库样式，进入多选后点行/勾选框选择，悬浮条显示已选数量并支持「删除所选」「取消」；后端新增 POST /api/persona/tags/batch-delete（只删当前博主）。
- 新增 test_persona_bulk 4 用例；verify.sh 全绿。

## [M104 / R-122] 2026-09-07 — 来源素材/云端深链跨博主直接打开
- 根因：脚本工作台「来源素材」链接（`#/videos?post=<作品 id>`）在素材库只查当前筛选博主的云端作品，
  洗稿来源属对标博主时提示「未在当前素材库找到…」且打不开（R-046 深链缺陷，R-090 只修了本地 edit 深链）。
- 后端新增 `GET /api/works/by-post/{post_id}`：按平台作品 id 反查所属博主，复用素材库同口径 list_works 返回包含它的云端条目（合并作品或单条）。
- 前端 VideosView：post 深链当前列表找不到时调用 by-post 拉详情直接打开弹窗回显；已转本地则打开本地编辑。
- verify.sh 全绿。

## [M103 / R-121] 2026-09-07 — 素材编辑页封面替换与播放
- CoverEditor 增加「替换/上传封面」按钮；有本地视频时点封面播放，无视频回退上传。


## [M102 / R-120] 2026-09-07 — 洗稿标题/标签/来源跳转/封面字
- 洗稿初稿生成新标题与封面字（标题不与素材标题一致，兜底加后缀）；drafts 新增 tags，编辑窗独立标签文本框；来源素材标题可点击跳转素材库。


## [M101 / R-118] 2026-09-07 — 洗稿双模型多轮讨论
- 对标洗稿改为 生成方初稿 + 评审方/生成方多轮打磨，每轮写 draft_discussions 留痕，最终稿落 drafts。

## [M100 / R-117] 2026-09-07 — 洗稿来源记录 + 原文/洗稿左右对照
- drafts 增加 source_ref 记录来源素材；草稿显示「对标洗稿 · 来源标题」并新增「原文案」tab。
- 对标洗稿弹窗改为左右 diff 高亮（lib/diff.js 字符级 LCS）。


## [M99 / R-116] 2026-09-07 — 对标页进行中状态切页保留
- AI分析/洗稿落后台任务（benchmark_analyze/benchmark_rewrite）并返回 task_id；结果写入 background_tasks.result（新增列）。
- 前端轮询任务、切页回来按 running 任务恢复 loading 并续轮询，完成后回填结果/弹窗；同时保留模块级共享状态作为同会话快速反馈。


## [M98 / R-115] 2026-09-07 — AI 分析 JSON 解析健壮化
- _parse_json 支持代码围栏/推理前后缀，并扫描第一个合法 JSON 对象。
- 实测 kimi-k2.6 为推理模型：答案在 content、推理在 reasoning_content；analyze max_tokens 800→2000，避免推理吃光 token 导致 content 为空。


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
- AGENTS.md / docs（ARCHITECTURE、DECISIONS、milestones）/ requirements（R-001~R-014）
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
- docs/ARCHITECTURE.md：重写为详细架构（技术栈/进程/模块/ER/配置/部署）
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
- 文档同步：重新生成 API.md（旧 bind-link 已下线）；ARCHITECTURE 定时任务补 04:00 清理；DATABASE 补运行时索引附录

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
- milestones/需求索引同步

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
- 按代码重写/校准：AGENTS.md、README.md、ARCHITECTURE（定时任务以 scheduler.py 为准）、milestones（M0–M52 + 待排期）、DECISIONS（整理 D-001~D-037）、QUICKSTART、GLOSSARY、FAQ
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

