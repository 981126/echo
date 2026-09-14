# 变更记录

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
- 顺带把 R-149 遗漏的 `DESIGN.md` 前端页面清单同步（去掉已下线的 `RequirementsView` / `/requirements`）。

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
- 口径同步：`docs/API.md` 删 4 条路由（**127 → 123**，`check_doc_consistency.py` 实测一致）、
  PRD 的页面清单与「事实源」描述、PRODUCT 的能力表、milestones。
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
- 文档：`docs/QUICKSTART.md` 新增 §8「NAS 部署 + 增量上线 runbook」（改表/改字段模板、生产库副本演练、备份→升级→回滚顺序）；
  `docs/DESIGN.md` 记结构机制与两个坑；`AGENTS.md` 技术栈同步；`docs/DATABASE.md` 27→28 张 + `schema_migrations` 章节。

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
- `docs/DESIGN.md` 记录量测表 + 再校准方法 + 「为什么不干脆去掉 max_tokens」的评估结论。

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
- 文档口径统一：PRD/ARCHITECTURE/DESIGN/README/QUICKSTART/AGENTS 更正「数据看板与复盘（已下线）」、提示词候选（手动）、27 张表、views 10、top15、pytest 183、inbox 路径；
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

