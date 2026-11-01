# R-244 开发设计：抖音数据看板

- **对应需求**：`requirements/R-244-douyin-data-dashboard.md`
- **日期**：2026-11-01
- **状态**：已实现（2026-11-01，代码与本文一致；verify 全绿 + 真实 TikHub 联调 + 浏览器点检完成）
- **重要说明**：2026-11-01 作者两次反馈后布局与统计能力有改版（v2 曲线在数据上方；v3 统计周期下拉 7/14/30/90、指标卡可点击切换曲线、移除粉丝独立栏/同类创作者/条均指标，详见 §5.16），本文其余章节保留原始设计，**以 §5.16 与代码为准**。本文中的新字段、新接口、阈值、映射均为实施前设计；2026-11-01 已用作者真实抖音创作者 Cookie 实测 `fetch_author_diagnosis` / `fetch_item_analysis_involved_vertical` / `fetch_item_analysis_overview` / `fetch_item_audience_portrait` / `fetch_item_audience_others`，真实响应样例存于 `.tmp/dashboard/*.json`。设计里的字段名与口径以真实响应为准；开发时按本文实现并补测试。

## 1. 开发背景

### 1.1 要解决的问题

作者要一个「只呈现数据、不做 AI 分析」的抖音创作者数据看板，形态对齐 `creator.douyin.com/creator-micro/home`：

1. 账号总览：近 7 日播放量、主页访问量、作品点赞/分享/评论、净增粉丝 + 播放量趋势 + 同类创作者对比。
2. 近期作品列表：替代原「通知」「活动管理」；点一条在下方展开该作品详情。
3. 作品详情 5 个 tab：总览 / 流量分析 / 观众分析 / 评论热词 / 评论管理（只读）。
4. 数据全部来自 TikHub，不直连抖音；拿不到的数据明确标注，不造假。

### 1.2 现有可复用能力

| 能力 | 位置 | 本需求怎么用 |
|---|---|---|
| 抖音创作者 Cookie 加密存储 + 数据源策略 | `douyin_creator_sync.py`、`douyin_account_policy.py` | 复用 `_cookie` 取 Cookie、`resolve_data_policy` 判断能否取私有数据、失效标记与通知 |
| TikHub 客户端（限速/重试/预算/业务错误判定） | `services/platform/tikhub.py` | 新增 5 个 creator_v2 方法；全部走 `_post`，复用限速与错误处理 |
| 单条作品创作者数据刷新 | `douyin_creator_sync.sync_post_creator_data` | 作品详情刷新直接复用（overview + 流量来源 + 搜索词 + 观看/跳出趋势 5 次请求） |
| 账号作品列表 + 指标快照 | `douyin_creator_sync.sync_account_creator_data` | 账号「更新数据」时调用（2 次请求），顺带写入当天作品快照，供趋势与 7 日 KPI 差值 |
| 作品指标落库 | `douyin_creator_sync._apply_item_metrics` | 复用；本需求小改：合并保留 `raw` 里的审核状态字段 |
| 指标对比（本人近 30 条同时点中位数） | `video_review_comparison.build_comparison` | 作品诊断结论直接用 `facts["plays"]` 的 state/baseline/sample_count |
| 评论同步 | `platform_sync.sync_post_comments` | 评论管理/评论热词数据来源；作品详情刷新时顺带刷评论（`pool=False` 不写灵感池） |
| 后台任务 + SSE + 进行中指示器 | `tasks.py`、`events.py`、`ActiveWorkProvider` | 「更新数据」按后台任务实现，支持切页/刷新恢复 |
| 预算 | `services/platform/budget.py` | 刷新前预检剩余额度；实际请求由 `_charge_requests` 计费 |
| 前端动效/格式化/组件 | `lib/motion.ts`、`lib/format.ts`、`components/ui/*` | 统一动效令牌与格式化；复用 tabs/card/badge/skeleton/tooltip |

### 1.3 核心设计决定

1. **只读、只呈现**：本页不产生任何写抖音的操作；评论管理只读。
2. **数据优先缓存**：打开页面只读本地库；只有「更新数据」或超过有效期才请求 TikHub。账号诊断 24h、作品详情 6h、评论 6h。
3. **账号总览来源分两层**：能对上抖音官方口径的 `播放量/完播率/互动指数/净增粉丝/投稿数` 用账号诊断接口；`主页访问量/作品点赞/作品分享/作品评论/逐日趋势` 用本地每日快照差值，并始终显示「覆盖 N 条作品」与「数据积累中」说明。
4. **作品详情 tab 数据全部来自 TikHub 真实响应**；「评论热词」明确标注本地统计口径；「评论管理」明确只读。
5. **拿不到就不画**：逐小时趋势、平台扶持流量、较往期对比等在 TikHub 无接口的项不展示或显示空状态，不用 0 或推算值填充。
6. **不改视频复盘**：只在作品详情加「去视频复盘」跳转入口（复用现有 `?post=` 参数）。
7. **只做抖音当前主博主的账号**：不扩多平台、不切账号。

### 1.4 边界

- 不支持非当前主博主的账号数据；不缓存其他账号数据。
- 不改 `platform_sync` 的每日同步流程与口径；账号快照覆盖范围 = 每日创作者同步覆盖的近 120 天作品（当前该账号 25 条）。
- 不做中国地图可视化（不引入地图库），地域分布用 Top 省份条形列表。
- 不新增依赖（中文分词用纯 Python n-gram 规则，见 5.11）。
- 不自动轮询刷新（除「打开页面发现诊断过期自动触发一次」外）。

## 2. 涉及的技术

### 2.1 后端

| 技术或模块 | 用途 | 本次使用方式 |
|---|---|---|
| FastAPI + Pydantic | 新接口 | 新增 `/api/douyin-dashboard` 路由，复用 `X-Access-Token` |
| SQLAlchemy 2.x | 查询本地快照、评论、作品 | 新增 2 个 JSON 文本列（`douyin_post_metrics`），不改其他表 |
| PostgreSQL | 数据存储 | JSON 用 TEXT（与项目一致） |
| Alembic | 表结构迁移 | 新增 revision `r244dashboard`（2 列） |
| httpx | 调 TikHub | 复用 `TikHubClient._post` |
| TikHub Creator V2 | 账号诊断、作品列表、作品指标、流量/趋势/观众数据 | 5 个新方法 + 复用 4 个既有方法 |
| 现有 `tasks` / SSE | 更新数据任务 | 新增任务 kind `douyin_dashboard_overview` / `douyin_dashboard_post` |
| 现有 `build_comparison` | 作品诊断结论 | 只取 facts，不新增对比算法 |
| 纯 Python 标准库 | 评论热词、KPI 差值、时间处理 | `re`、`json`、`statistics`、`datetime`，不新增依赖 |

### 2.2 前端

| 技术或模块 | 用途 | 本次使用方式 |
|---|---|---|
| React 19 + TypeScript | 新页面 | `frontend_v2/src/pages/dashboard/`，路由 `#/dashboard` |
| TanStack Query | 查询/刷新 | queryKey：`['dashboard','overview']`、`['dashboard','works',limit]`、`['dashboard','post',postId]` |
| 现有 `useTaskScope` | 「更新数据」任务跨页恢复 | scope：`douyin_dashboard_overview`、`douyin_dashboard_post_<postId>` |
| 手写 SVG 图表 | 趋势线、环形图、年龄柱状图、占比条 | 复用项目无图表库的现状（学 `pages/video-review/charts.tsx`） |
| Framer Motion | 页面/详情展开/tab/列表动效 | 用 `lib/motion.ts` 令牌；不引入新动画库 |
| lucide-react + 现有 ui 组件 | 图标、卡片、badge、骨架、tooltip | 全部复用 |

### 2.3 计划新增/修改的文件

**后端新增**

| 文件 | 内容 |
|---|---|
| `backend/app/services/douyin_dashboard.py` | 业务核心：账号解析、缓存、KPI/趋势计算、作品详情装配、评论热词、作品诊断、刷新任务函数 |
| `backend/app/api/douyin_dashboard.py` | 薄路由（3 个 GET + 2 个 POST） |
| `backend/tests/test_r244_douyin_dashboard.py` | 单测：状态映射、KPI/趋势、热词、观众映射、mock 接口冒烟 |
| `backend/alembic/versions/r244dashboard.py` | `douyin_post_metrics` 加 2 列 |

**后端修改**

| 文件 | 改动 |
|---|---|
| `backend/app/models/video_review.py` | `DouyinPostMetric` 加 `audience_portrait`、`audience_others` |
| `backend/app/services/platform/tikhub.py` | 新增 5 个 creator_v2 方法（含 mock 分支） |
| `backend/app/services/douyin_creator_sync.py` | `_apply_item_metrics` 写 `raw` 时合并不覆盖既有 `review/visibility`；新增 `store_post_audience` 小函数（或放 dashboard 服务） |
| `backend/app/main.py` | 注册路由 |
| `backend/app/core/task_meta.py` | 2 个新 kind 的中文名 + 跳转 `/dashboard` |
| `docs/DATABASE.md` | `douyin_post_metrics` 两列说明 |
| `docs/CHANGELOG.md`、`docs/milestones.md`、`requirements/README.md` | 交付记录 |

**前端新增**

| 文件 | 内容 |
|---|---|
| `frontend_v2/src/pages/dashboard/index.tsx` | 页面骨架：数据获取、账号总览、近期作品、详情区编排、自动刷新守卫 |
| `frontend_v2/src/pages/dashboard/works-list.tsx` | 右侧近期作品列表 |
| `frontend_v2/src/pages/dashboard/post-analysis.tsx` | 作品详情区 5 个 tab |
| `frontend_v2/src/pages/dashboard/charts.tsx` | 播放量趋势图、环形分布图、年龄柱状图、占比条、观看趋势图 |
| `frontend_v2/src/pages/dashboard/types.ts` | 接口响应类型 |
| `frontend_v2/src/pages/dashboard/format.ts` + `format.test.ts` | 百分比/万/亿/增减格式化与映射单测 |

**前端修改**

| 文件 | 改动 |
|---|---|
| `frontend_v2/src/App.tsx` | 路由 `dashboard`（lazy） |
| `frontend_v2/src/components/layout/sidebar.tsx` | 导航加「数据看板」 |
| `frontend_v2/src/components/layout/app-shell.tsx` | `TITLES` 加 `/dashboard` |
| `frontend_v2/src/api/schema.d.ts` | `npm run gen:api` 重新生成 |

## 3. 开发流程图

```
┌──────────────────────────── 打开数据看板 ────────────────────────────┐
│ 1) GET /api/douyin-dashboard/overview                                │
│    └─ 读 Kv 缓存（账号诊断）+ 本地快照算周期 KPI/各指标曲线           │
│       ├─ 缓存不存在或 >24h → needs_refresh=true                       │
│       └─ 返回 200（含 credential/data_policy/warnings，不报错）       │
│ 2) GET /api/douyin-dashboard/works?limit=20&offset=0                 │
│    └─ 读 platform_posts + 最新 platform_post_stats + 状态             │
│ 3) 前端：needs_refresh 且本会话未自动触发过 → POST overview/refresh    │
│    └─ 202 {task_id} → useTaskScope 轮询 → 完成后 invalidate 并重读     │
└──────────────────────────────────────────────────────────────────────┘
                                │
              用户点「近期作品」某一条
                                ▼
┌───────────────────── 作品详情 ──────────────────────┐
│ 1) GET /api/douyin-dashboard/works/{post_id}        │
│    └─ 读最新 douyin_post_metrics 行 + 评论 + 对比   │
│       ├─ 有缓存（<6h）→ 直接展示                     │
│       └─ 无缓存/过期 → stale=true                    │
│ 2) 前端 stale 且无运行中任务 → POST .../refresh      │
│    └─ 202/200 {task_id|skipped} → 轮询 → invalidate   │
└──────────────────────────────────────────────────────┘
                                │
                 「更新数据」按钮（账号/作品）
                                ▼
┌──────────────────────── 后台任务（线程） ────────────────────────┐
│ overview: 预算预检 → diagnosis(1) → 作品快照(2) → 写 Kv            │
│           → 作品快照同步(2) → 写 Kv → mark_valid                  │
│ post:     预算预检 → 缓存<6h 且非 force → skipped                 │
│           → sync_post_creator_data(5) → audience_portrait(1)      │
│           → audience_others(1) → 评论同步(1) → 写库               │
│ 每步 update(progress,note)；失败保留旧数据，错误写任务并通知       │
└──────────────────────────────────────────────────────────────────┘
```

## 4. 数据流转图

```
TikHub Creator V2                     本地数据库                         前端
─────────────────                     ─────────────────────────────     ─────────────────────────
fetch_author_diagnosis ──┐
                         ├── 刷新任务归一化 ──► app_kv                     GET /overview
                         ├──────────────────► douyin_dashboard:overview:◄── 账号总览
                         │                    {account_id} (JSON)
fetch_item_list ─────────┤                    platform_posts / platform_post_stats
                         │                    douyin_post_metrics（每日快照）◄─ 7 日 KPI/趋势
fetch_item_overview_data ┤
fetch_item_play_source ──┤  sync_post_creator_data    douyin_post_metrics
fetch_item_watch_trend ──┤  + audience 两个接口 ────► +audience_portrait   ◄── GET /works/{id}
fetch_item_search_keyword┤                            +audience_others       作品 5 个 tab
                         │
fetch_video_comments ────┴── sync_post_comments ───► platform_post_comments  ◄── 评论列表/热词
```

说明：
- `platform_post_stats` 是「作品累计指标按天」；`douyin_post_metrics` 是「创作者私有指标按天」。两者同日写入，同 `post_id + date` 对应。
- 账号 7 日 KPI/逐日趋势 = 对「近 120 天发布且被同步的作品」做两日快照求差后求和（见 5.4）。
- 观众画像/受众兴趣存 `douyin_post_metrics` 当天行（新增 2 列）。

## 5. 实现细节

### 5.1 账号解析与错误语义

- 账号：`get_current_creator(db)` 取当前主博主 → `CreatorAccount(platform='douyin', enabled=True)`；无主博主/无抖音账号时 GET 接口返回 200 + `account=null` + `blocked_reason`，让页面渲染空状态（不抛 500）。
- 数据源策略：`resolve_data_policy(db, account)`：
  - `is_blocked`（Cookie 失效未更新）：GET 正常返回缓存 + `credential.status="invalid"` + 警示；POST 刷新返回 400。
  - `is_creator=False`（开关关闭/无 Cookie）：GET 返回公开数据 + `private_available=false` + 提示；POST 刷新返回 400。
- 作品归属：`own_post(db, owner, post_id)`（复用视频复盘逻辑），不存在/不属于当前账号 → 404。
- 错误文案统一中文，不暴露 Cookie/Key；Cookie 只在请求体使用，不写日志、不返回。

### 5.2 缓存、刷新与额度

| 项 | 规则 |
|---|---|
| 账号总览缓存 | `app_kv` 键 `douyin_dashboard:overview:{account_id}`，值 JSON：`{diagnosis, diagnosis_at, warnings}`；TTL 24h（v3 起不再缓存投稿概览） |
| 作品详情缓存 | 最近一条 `douyin_post_metrics`（含 `captured_at`），TTL 6h；`platform_post_stats` 当天行同步刷新 |
| 打开页面自动刷新 | 仅当 overview 缓存不存在或 >24h，前端在**本会话**自动触发一次（sessionStorage 记录时间戳，10 分钟内不重复），随后按钮转「更新中」 |
| 作品首次选中 | 若该作品无 `douyin_post_metrics` 行或 >6h，自动触发详情刷新一次（同一作品 10 分钟内不重复自动触发） |
| 手动「更新数据」 | 允许强制刷新；若已有同目标运行中任务 → 直接复用 task_id（202, reused=true） |
| 刷新幂等 | `start_task(dedupe=True)` 默认按 kind+payload 去重 |
| 预算预检 | `get_budget(db)`；overview 需 3 次（诊断 1 + 作品快照 2），post 需 8 次；剩余不足 → 400「今日 TikHub 请求额度不足（剩余 X 次，本次需要 Y 次）」 |
| 失败保留旧数据 | 任务失败不回滚已成功写入的部分；页面显示旧数据 + 任务错误；`sync_post_creator_data` 内部 `db.rollback()` 只影响本次事务 |
| 返回体状态 | GET 响应含 `needs_refresh`、`stale`、`updating_task_id`（查询运行中任务，供前端显示进行中） |

请求数核算：

| 任务 | 接口 | 次数 |
|---|---|---|
| 账号「更新数据」 | `fetch_author_diagnosis` + `fetch_item_list`（`sync_account_creator_data` 内 2 页）；v3 起不再请求投稿概览 | **3** |
| 作品「更新数据」 | `fetch_item_overview_data` + `fetch_item_play_source` + `fetch_item_search_keyword` + `fetch_item_watch_trend`×2（`sync_post_creator_data` 内 5 次）+ `fetch_item_audience_portrait` + `fetch_item_audience_others` + 评论 1 次 | **8** |

### 5.3 账号诊断（`fetch_author_diagnosis`）

> v3 起：诊断只用于「近 7 日」周期的播放量/净增粉丝（官方口径）；14/30/90 日周期这两个指标改用本地快照差值。

请求：`POST /douyin/creator_v2/fetch_author_diagnosis`，body `{"cookie": "..."}`，无日期参数（固定最近 7 天）。

真实响应结构（2026-11-01 样例）：

```json
{"data": {"code": 0, "data": {
  "Interact":          {"OwnValue": 0.0287, "SimilarValue": 0.0204, "AuthorRank": 0.6316, "SimilarRank": 0.4999, "SimilarCount": 17367},
  "NewFans":           {"OwnValue": -63,    "SimilarValue": 128,    "AuthorRank": 0.0,    "SimilarRank": 0.501,  "SimilarCount": 17367},
  "PlayCnt":           {"OwnValue": 88474,  "SimilarValue": 32470,  "AuthorRank": 0.6604, "SimilarRank": 0.5,    "SimilarCount": 17367},
  "PlayFinishRatio":   {"OwnValue": 0.1316, "SimilarValue": 0.1094, "AuthorRank": 0.5975, "SimilarRank": 0.5001, "SimilarCount": 17367},
  "PublishActivation": {"OwnValue": 1,      "SimilarValue": 4,      "AuthorRank": 0.1962, "SimilarRank": 0.5822, "SimilarCount": 17367}
}}}
```

页面映射：

| 原始 key | 页面字段 | 单位/格式 | 说明 |
|---|---|---|---|
| `PlayCnt` | 播放量 | 次（≥1 万显示「x.x 万」） | 与抖音首页账号总览口径一致 |
| `PlayFinishRatio` | 完播率 | 百分比 1 位 | 0~1 小数 |
| `Interact` | 互动指数 | 4 位小数（或百分比？）→ 页面显示 0.0287 | 抖音定义的互动综合得分，不做换算 |
| `NewFans` | 净增粉丝 | 整数（可为负） | 负值红色 |
| `PublishActivation` | 投稿数 | 整数 | 近 7 日发布作品数 |

派生显示：`同类创作者平均 {SimilarValue}` + `超过 {round(AuthorRank*100)}% 的同类创作者`（`AuthorRank` 缺失则不显示）。

归一化后存 Kv：`{"plays": {"own": 88474, "similar": 32470, "rank": 0.6604}, ...}`，避免页面直接依赖第三方字段名。


**粉丝数据（与播放数据同一区块，作者 2026-11-01 追加）**：

| 字段 | 接口/来源 | 说明 |
|---|---|---|
| 总粉丝量 | 本地 `creator_account_snapshots.followers`（TikHub 公开主页接口每日同步） | 实测 59,063 = 抖音「5.91 万」；页面显示快照日期 |
| 粉丝净增 | `fetch_author_diagnosis` `NewFans.OwnValue` | 实测 -63，与抖音一致；附同类平均/排名 |
| 吸粉量 / 脱粉量 / 回访粉丝量 | **TikHub 无接口**（已核对 creator_v2 全部 14 个接口与公开接口） | 固定返回 null，页面「暂无数据（TikHub 未提供）」；不用作品维度涨粉/脱粉凑，避免与净增对不上 |

接口返回 `fans` 块：`{total:{value,date}, net:{value,similar,rank}, acquired:null, lost:null, returning:null, unavailable:[...], note}`；总粉丝量不额外消耗请求（复用每日快照）。

### 5.4 账号 7 日 KPI 与逐日播放趋势（本地快照差值）

**输入**：`platform_post_stats`（`post_id, stat_date, plays, likes, comments, shares, favorites`）+ `douyin_post_metrics`（`post_id, snapshot_date, profile_visits, follower_gain`），限定当前账号作品、`stat_date ∈ [today-13, today]`。

**用于页面的指标**：主页访问量（`profile_visits`）、作品点赞（`likes`）、作品分享（`shares`）、作品评论（`comments`）4 个数字卡；播放量/净增粉丝用账号诊断（见 5.3），不走快照合计。

**规则**（每个指标 `m ∈ {profile_visits, likes, comments, shares}`）：

1. 对每条作品收集其在周期内的 `(date, value)` 序列（按日期升序，去重同日取最后一条）。
2. 当前周期 `D_cur = [today-6, today]` 内：
   - 若该作品在 `D_cur` 内至少有 2 个不同日期 → `delta = max(0, last_value - first_value)`；
   - 否则该作品不参与本指标合计（记为「未覆盖」）。
3. `cur_total = Σ delta`；覆盖作品数 `covered = 参与合计的作品数`。
4. 前 7 日 `D_prev = [today-13, today-7]` 用同一算法得 `prev_total`、`prev_covered`。
5. `较前 7 日 = cur_total - prev_total`，仅当 `prev_covered >= ceil(covered * 0.5)` 且 `prev_total` 可算（`prev_covered ≥ 1`）时显示；否则 `delta=null`，页面显示「暂无对比（历史数据不足）」。
6. 值为负（平台修正/删除）按 0 计，避免出现负数增量；页面不展示负值增量。

**逐日播放趋势**：

1. 对每条作品、`d ∈ 最近 7 天`：若 `d-1` 与 `d` 都有快照 → `added(d) += max(0, plays(d) - plays(d-1))`。
2. 某天没有任何作品可算 → 该天 `value=null`（图表断开，不补 0）。
3. 覆盖说明：`{posts: 参与计算的作品数, dates: 用到的快照日期列表}`，页面显示「仅统计近 120 天发布且已同步的 N 条作品」。
4. 若最近 7 天中可算天数 < 2 → `available=false`，页面显示「数据积累中：需要至少 2 天同步数据，当前已有 X 天」。

**已知口径差异（页面必须说明）**：本算法只覆盖近 120 天发布且被每日同步的作品（当前 25 条），且只统计相邻两日快照；抖音官方「数据中心」是账号全量口径，两者数字可能不同。播放量/净增粉丝的大数字仍用账号诊断接口，保持与抖音一致。

**历史脏快照剔除规则（实施补充，2026-11-01 真实数据发现）**：

- 现象：历史公开同步把抖音 `plays` 长期写成 0（app/v3 不返回播放数），创作者接口才是真实值；10-29 还有一批「同步失败写全 0」的快照。若把 0 当基线，会算出「一天新增 494 万播放」「一周点赞 5.3 万」。
- 规则：累计计数器（播放/点赞/评论/分享/主页访问量）不可能从 >0 掉回 0 —— 同一作品同一字段只要出现过正数，就把 0 值日期当作「缺失快照」剔除，不参与区间差值/逐日新增；某天所有公开统计全为 0 时，该天的创作者指标也一并不参与。
- 示例（真实数据）：作品 1827 的 10-29 `plays=0`、10-30 `plays=1,969,052` → 10-30 不产生「新增 196 万」，只从 10-30 之后的真实增量开始算。
- 单测锁定：`test_account_kpis_ignores_zero_snapshot`、`test_play_trend_ignores_public_zero_plays`。

**测试点**：新增作品当天（首日快照）不计入增量；缺日期断开；负增量按 0；前 7 日覆盖不足返回 null；跨 14 天窗口边界正确。

### 5.5 投稿条均指标（`fetch_item_analysis_*`，v3 起已移除）

> 2026-11-01 v3：作者要求删除「条均指标」栏 → 页面不展示、账号「更新数据」不再请求这两个接口（overview 请求数 5→3），`TikHubClient` 中对应方法与 mock 已删除；以下内容仅保留为历史设计记录。

请求（2 次）：

1. `POST /douyin/creator_v2/fetch_item_analysis_involved_vertical`，body `{"cookie","start_date":"YYYYMMDD","end_date":"YYYYMMDD"}`（**字符串**，传整数会 422；R-244 联调踩过）。
2. `POST /douyin/creator_v2/fetch_item_analysis_overview`，body `{"cookie","start_date","end_date","primary_verticals":["生活记录"]}`（垂类来自上一步；为空时传空数组）。

日期范围：`end=today`，`start=today-6`（近 7 日，与新需求周期一致）；接口限制最多 90 天。

真实响应字段 → 页面：

| 原始字段 | 页面字段 | 格式 |
|---|---|---|
| `median_play_count.metric_value` | 条均播放量（中位数） | 次 |
| `average_like_count_per_video.metric_value` | 条均点赞 | 次 |
| `average_comment_count_per_video.metric_value` | 条均评论 | 条 |
| `average_share_count_per_video.metric_value` | 条均分享 | 次 |
| `average_play_duration.metric_value` | 条均播放时长 | 秒（1 位小数） |
| `bounce_rate_2s.metric_value` | 条均 2s 跳出率 | 百分比 |
| `completion_rate_5s.metric_value` | 条均 5s 完播率 | 百分比 |
| `cover_click_ratio.metric_value` | 条均点击率 | 百分比 |
| `submission_count.metric_value` | 周期投稿量 | 篇 |

失败降级：垂类/概览失败只记录 `warnings`，不失败整个刷新任务（诊断已成功仍可用）。

### 5.6 近期作品列表与状态映射

**数据查询**（GET 时纯读本地，不调 TikHub）：

```
platform_posts（account_id=当前账号, platform='douyin'）
  LEFT JOIN 该 post 最新一条 platform_post_stats（stat_date 最大）
  LEFT JOIN 该 post 最新一条 douyin_post_metrics（snapshot_date 最大）
order by publish_time desc
limit/offset 分页，返回 has_more
```

字段映射：

| 页面字段 | 来源 |
|---|---|
| post_id | `platform_posts.id` |
| 标题 | `platform_posts.title` |
| 封面 | `platform_posts.cover_url_local`（优先本地缩略 `/covers/x?w=400`，前端加 `w=400`） |
| 发布时间 | `publish_time`（北京时间，MM-DD HH:mm） |
| 播放/点赞/评论/分享 | 最新 `platform_post_stats` 对应列（NULL 显「—」） |
| 状态 | 解析最新 `douyin_post_metrics.raw.item` 的 `review` / `visibility`（见下表） |
| 是否有详情缓存 | 是否存在 `douyin_post_metrics` 行 |

**状态映射**（依据 2026-11-01 真实响应：公开作品 `review.status=2, visibility.status=1`；私密作品 `review.status=4 + details[0].text="不适宜公开", visibility.status=3`）：

| 条件 | 页面文案 | 徽标色 |
|---|---|---|
| `visibility.status == 3` | 私密 | 灰 |
| `review.status == 4` | 不适宜公开 | 红 |
| `review.status == 2` | 通过 | 绿 |
| `visibility.status == 1`（无 review） | 已发布 | 蓝 |
| 其他/缺字段 | 状态未知 | 灰 |
| 无 raw | — | 灰 |

**raw 合并规则**（改 `_apply_item_metrics`）：overview 接口返回的 item 不含 `review/visibility`，写库存 `raw` 前若旧 raw 有这两个字段而新 item 没有，则保留旧值，避免详情刷新把状态刷没。实现：`new_item = item.copy(); for key in ("review","visibility"): if key not in new_item and old.get(key): new_item[key]=old[key]`。

### 5.7 作品详情指标装配

**数据源优先级**：最新 `douyin_post_metrics.raw.item.metrics`（25 个字段）> 同表显式列（bounce/finish/avg/cover/profile/follower）> 最新 `platform_post_stats`（播放/点赞/评论/分享/收藏）。

**原始字段 → 页面字段映射**：

| 原始字段（raw item metrics） | 页面字段 | 单位 | 所属 tab |
|---|---|---|---|
| `view_count` | 播放量 | 次 | 总览 |
| `like_count` | 点赞量 | 次 | 总览 |
| `comment_count` | 评论量 | 条 | 总览 |
| `share_count` | 分享量 | 次 | 总览 |
| `favorite_count` | 收藏量 | 次 | 总览 |
| `danmaku_count` | 弹幕量 | 条 | 总览 |
| `completion_rate` | 完播率 | % | 总览/流量分析 |
| `bounce_rate_2s` | 2s 跳出率 | % | 总览/流量分析 |
| `completion_rate_5s` | 5s 完播率 | % | 流量分析 |
| `avg_view_second` | 平均播放时长 | 秒 | 流量分析 |
| `avg_view_proportion` | 平均播放占比 | % | 流量分析/作品诊断 |
| `favorite_rate` | 收藏率 | % | 作品诊断 |
| `subscribe_count` | 涨粉量 | 人 | 总览粉丝卡/观众数据 |
| `subscribe_rate` | 涨粉率 | % | 观众数据 |
| `unsubscribe_count` | 脱粉量 | 人 | 总览粉丝卡/观众数据 |
| `unsubscribe_rate` | 脱粉率 | % | 观众数据 |
| `dislike_count` | 不感兴趣量 | 人 | 观众数据 |
| `dislike_rate` | 不感兴趣率 | % | 观众数据 |
| `fan_view_proportion` | 粉丝播放占比 | % | 总览粉丝卡 |

比率统一：原始 0~1 小数 → 页面百分比 1 位小数；原始返回 >1 且 ≤100 视为百分数（复用 `_metric(rate=True)` 的兼容逻辑）；缺失显示「暂无数据」。
注意：`completion_rate` 等字段在不同 mock 中可能是 0~1；真实响应为 0~1（如 0.074461 = 7.45%）。

**播放量趋势（总览 tab）**：读该作品 `platform_post_stats` 最近 7 条按日期；「累计」= plays；「新增」= `max(0, plays(d)-plays(d-1))`；不足 2 天 → 空状态「TikHub 未提供逐小时趋势，逐日数据积累中」。

### 5.8 流量来源与观看趋势

**流量来源**：`douyin_post_metrics.traffic_sources` 已是 `[{"name":"推荐","value":0.74,"ratio":0.74}, ...]`（同步时 `_traffic_sources` 归一化）。页面展示时把中文渠道名映射到创作者中心文案：

| 同步名 | 页面文案 |
|---|---|
| 推荐 | 推荐页 |
| 关注 | 关注页 |
| 主页 | 个人主页 |
| 朋友 | 朋友页 |
| 私信 | 消息页 |
| 搜索 | 搜索 |
| 直播 | 直播 |
| 其他/其他渠道 | 其他 |

按 `ratio` 降序，条形图 + 百分比；**不展示「对比 7 日」列**（接口只有当前值）。

**观看趋势**：`douyin_post_metrics.retention_trend`（type=1）与 `bounce_trend`（type=7）是 `[{"key":"00:00","value":0.82}, ...]`；`similar_author_trend` 是 `{"retention": [...], "bounce": [...]}`。页面两个子 tab：留存分析/跳出分析；当前作品实线、同类作者虚线；`trend_reliable=plays>=200 && 趋势非空`，不可靠时显示「播放量较少，趋势仅供参考」。数据缺失 → 「暂无数据」。

### 5.9 观众分析（含活跃度映射证据）

**观众数据 6 卡**：`subscribe_count/subscribe_rate/unsubscribe_count/unsubscribe_rate/dislike_count/dislike_rate`（同 5.7 表）。

**涨粉量趋势**：读该作品 `douyin_post_metrics.follower_gain`（= `subscribe_count`，作品累计涨粉）按天序列：
- 「累计」= 当日 `follower_gain`；
- 「新增」= `max(0, v(d)-v(d-1))`；
- 不足 2 天 → 「数据积累中」；每小时版不做。

**观众画像**（`fetch_item_audience_portrait`，真实响应结构）：

| 维度 | 原始字段 | 页面展示 |
|---|---|---|
| 性别 | `gender.ratio_list: [{key:"male"/"female", value}]` | 环形图 + 男性/女性百分比（male→男性、female→女性） |
| 活跃分布 | `active: [{key:"-1"/"1"/"2"/"3"/"4", value}]` | 环形图 + 未知/低活/轻度/中度/重度（映射见下） |
| 年龄 | `age.ratio_list: [{key:"-18"/"18-23"/…/"50-", value}]` | 柱状图，固定顺序 -18、18-23、24-30、31-40、41-50、50- |
| 地域 | `province.ratio_list` + `city_level.ratio_list` | 省份占比 Top 6 条形列表（降序，其余合计一行）；城市等级 Top 3 小标签 |
| 新老用户 | `new_user` | 不展示（截图没有，避免页面过长） |
| 职业 | `career` | 不展示 |

**活跃分布 key → 中文映射（重要，TikHub 文档写错）**：TikHub 文档标注 `active` 为「活跃时段（上午/下午/晚上/其他）」，但抖音创作者中心页面实际是「活跃度分档：未知/低活/轻度/中度/重度」。2026-11-01 用同一作品对照验证：

- 截图图例顺序与颜色：未知(32,215,240)、低活(64,200,241)、轻度(106,194,244)、中度(142,198,243)、重度(187,210,248)；
- 截图环形图各颜色面积占比（像素统计）：重度 ≈ 89%、中度 ≈ 9.8%、轻度 ≈ 0.9%、低活 ≈ 0.4%；
- 同一时刻接口返回：`{"2":0.0178,"3":0.1075,"4":0.8347,"-1":0.0369,"1":0.0031}`；
- 对照可得：`4 → 重度`、`3 → 中度`、`2 → 轻度`、`1 → 低活`、`-1 → 未知`（占比一一对得上）。

因此映射表固定为 `{"-1":"未知","1":"低活","2":"轻度","3":"中度","4":"重度"}`，在代码中加注释与文档留痕；未来若作者发现抖音页面口径变化，只需改这一张表。

**受众兴趣分布**（`fetch_item_audience_others.audience_preference.total_data.ratio_data`）：

- 取 `ratio_data` 按 `value` 降序，过滤 key 以「未分类」开头的项，取前 6；
- 与截图一致：随拍 25.00%、游戏 16.67%、体育 12.50%、二次元 12.50%（真实响应逐项对得上）。

**受众关注热词**（`audience_search_most_keywords`）：

- 结构 `[{keywords, query_cnt_7d, query_7d_list}]`；
- 页面字段：词 = `keywords`，热度 = `int(query_cnt_7d)`；
- 排序：按热度降序取前 8（截图官方顺序不是按热度，这里按热度排更可解释）；
- 格式化：≥1 亿 → 「x.x 亿」；≥1 万 → 「x.x 万」；否则整数；
- 空数组 → 「暂无数据」。

### 5.10 涨粉量趋势（见 5.9，与作品粉丝数据同源）

同 5.9「涨粉量趋势」。

### 5.11 评论热词算法（本地，确定性可单测）

**输入**：该作品 `platform_post_comments.text` 列表（刷新时拉最新 Top 50），N = 评论条数。

**步骤**：

1. 清洗：去掉 URL、`@昵称`、`#话题#`、emoji/符号、数字串、英文字母串，只保留连续汉字片段。
2. 候选：对每个汉字片段生成 2~4 字滑窗 n-gram。
3. 停用规则：
   - 候选本身在停用词表（约 120 个：的/了/是/我/你/他/她/它/这/那/就是/什么/怎么/可以/自己/我们/他们/时候/因为/所以/但是/然后/还是/之前/之后/现在/今天/东西/事情/问题/觉得/感觉/真的/应该/需要/可能/准备/开始/继续/知道/希望/哈哈/捂脸…）；
   - 候选包含任一停用单字（的/了/是/吗/呢/吧/啊/呀/哦/嗯/哈/么/着/过/吧/嘛）；
   - 候选含数字/字母。
4. 计数口径：按**评论条数**计数（同一条评论内重复出现只算 1 次），防刷屏与重复。
5. 阈值：`count >= max(2, ceil(N * 0.02))`。
6. 去重：按 count 降序、词长升序扫描；若当前候选与已保留词互为子串 → 跳过（保留先出现的），避免「月入/月入过/入过」重复。
7. 排序：count 降序 → 长度升序 → 字典序，取前 40。
8. 输出：`{"items":[{"word":"工作","count":13,"ratio":0.13}, ...], "total_comments": N, "note":"基于已同步 N 条评论统计，与抖音官方口径可能不同"}`。
9. 降级：`N < 3` → `items=[]`，页面显示「评论太少，暂无法统计热词」；无候选同样空态。

**原型验证**（2026-11-01 用真实已同步评论）：102 条评论产出 `个月(37)/外包(17)/工作(13)/工资(12)/小时(11)/外卖(9)/月入(9)/一万(9)/过万(9)/驻场(8)/技术(8)/公司(7)/轻松(6)…`，词义可用；「捂脸」类表情文字可加入停用词。

**测试点**：停用词过滤、同评论去重、子串去重、阈值、确定性输出（同输入同输出）、空输入。

### 5.12 评论管理（只读）

- 数据：`platform_post_comments`（`post_id` 过滤），字段 `user_nick`、`text`、`likes`、`created_at`（本地同步时间）。
- 排序：`likes desc, id desc`，最多 50 条。
- 页面字段：用户昵称、评论内容、点赞数、同步时间（注明「同步时间」不是评论发布时间——本地未存评论发布时间）。
- 说明条固定文案 + 「打开抖音评论管理」外链 `https://creator.douyin.com/creator-micro/data/comment`。
- 无写操作按钮（TikHub 不提供回复/删除/举报）。
- 「刷新评论」：作品详情刷新任务里顺带同步（1 次请求）；单独刷新按钮仅空状态出现，调用同一详情刷新接口。

### 5.13 作品诊断结论

- 输入：`build_comparison(db, post)` 的 `facts`（plays、finish_rate、follower_gain 等）与 `comparison.count`。
- 规则（只判断流量，不下因果结论）：
  - `sample_count < 5` 或 `plays.missing` → 结论「样本较少，暂不做判断」；
  - `plays.state == "low"` → 「流量低于平时」；
  - `plays.state == "high"` → 「流量高于平时」；
  - 其他 → 「流量接近平时」。
- 说明文案模板：「这条视频播放 {plays}，你近 30 条相近视频在相同发布天数的中位数是 {baseline}（样本 {n} 条）。」
- 展示指标：平均播放占比 `avg_view_proportion`、收藏率 `favorite_rate`（直接来自 TikHub）；「较往期」官方对比不显示（TikHub 无接口）。
- 不使用 AI，不编造原因。

### 5.14 动效与不闪帧

| 交互 | 动效 |
|---|---|
| 页面首次进入 | 区块 `initial={false}` 或 softIn（0.85→1 + 8px，0.22s），禁止从 opacity:0 起步导致白闪 |
| tab 切换 | 复用 `ui/tabs` 滑块动画；内容用「保留旧内容到新内容就绪」策略（本次数据都在一个响应里，切换无需请求，直接局部淡入 0.2s） |
| 选中近期作品 | 行高亮 spring 过渡；详情区高度展开 + 内容 softIn；切换作品时先用骨架占位（保持区域高度），不整块消失 |
| 图表入场 | 路径/柱子 `initial={{opacity:0.7}} animate={{opacity:1}}`（0.3s），不做逐点动画 |
| 更新中 | 按钮 spinner + 「更新中 x%」；区块右下角轻量进度条（复用 `Progress`） |
| reduced-motion | `window.matchMedia('(prefers-reduced-motion: reduce)')` 时动画时长 0（状态切换保留） |

### 5.15 错误与降级总表

| 场景 | 后端行为 | 前端表现 |
|---|---|---|
| 无主博主 | GET 200 `{account:null, blocked_reason:"请先创建并切换主博主"}` | 整页空状态 + 去「博主管理」 |
| 无抖音账号 | GET 200 `{account:null, blocked_reason:"请先绑定抖音账号"}` | 同上 |
| 创作者数据未开启/无 Cookie | GET 200 + `private_available:false` + 公开数据 | 提示条 + 禁用「更新数据」（或点击返回 400 提示） |
| Cookie 失效 | GET 200 + `credential.status:"invalid"` + 缓存数据 | 顶部警示条 + 去更新 Cookie |
| 额度不足 | POST 400 明确文案 | toast + 警示条，不清空数据 |
| TikHub 接口失败 | 任务 failed + error（脱敏） | 区块提示失败原因 + 重试；旧数据保留 |
| 数据从未成功 | GET 200 + 字段 null + `needs_refresh:true` | 空状态 + 「更新数据」 |
| 快照不足 | GET 200 + trend.available=false + note | 「数据积累中」 |
| 平台返回 0 | 原样 0 | 显示 0（不当成缺失） |
| 未知字段/未知枚举 | 映射为「未知」并记 warning | 显示「未知」，「数据来源说明」可查 |

### 5.16 2026-11-01 v3 改版（作者最终确认，覆盖以上相关描述）

| 改动 | 实现 |
|---|---|
| 统计周期可下拉 7/14/30/90 天 | `GET /overview?period=N`；`account_kpis(days=N)`：当前窗口 `[today-N+1, today]`、前窗口 `[today-2N+1, today-N]`；前窗口覆盖作品数 ≥ 当前周期一半才显示「较前 N 日」 |
| 删除「播放量趋势（近 7 日）」标题 | 曲线区不再渲染标题，右上角仅显示图例「● 指标名（每日新增）」/「● 总粉丝量」 |
| 指标卡可点击切换曲线 | 后端返回 7 个指标各自的 `series`（daily 新增 / cumulative 累计）；前端 `metricKey` 状态控制 `TrendLine`，选中卡高亮（主色数字 + 底部粗线），默认播放量；切周期不重置已选指标 |
| 粉丝数据独立栏删除，总粉丝量/净增粉丝并入指标网格（一行 4 个） | 指标卡 7 个：播放量/主页访问量/作品点赞/作品分享/作品评论/净增粉丝/总粉丝量；`grid-cols-2 md:grid-cols-4`；吸粉量/脱粉量/回访粉丝量仍无接口，直接不展示 |
| 删除同类创作者对比、条均指标两栏 | 前端移除两个区块；后端 overview 不再返回 `analysis`，账号「更新数据」不再请求投稿概览两接口（5→3 次），`TikHubClient` 对应 2 个方法与 mock 删除 |
| 净增粉丝曲线可为负数 | `TrendLine` 纵轴域支持 `[min,max]`、画零参考线、面积从 0 线起；横轴长周期自动稀疏为约 7 个日期刻度 |
| 数据口径 | 7 日周期：播放量/净增粉丝用账号诊断，其余用本地快照；14/30/90 日：全部用本地快照（页面脚注动态说明）；总粉丝量取账号每日快照最近值并显示快照日期 |

### 5.17 2026-11-01 v4 改版（作者第三次反馈，覆盖以上相关描述）

| 改动 | 实现 |
|---|---|
| 移除「数据中心」标题，改博主头像 + 名称；数据更新时间移到统计周期后 | 卡片顶部第一行：头像（`coverThumb(avatar,160)`）+ 昵称 + 数据可用徽标 + 更新按钮；第二行：统计周期下拉 + ⓘ + 「数据更新至：YYYY-MM-DD HH:mm」 |
| 指标卡改为上中下三段 | 上=指标名（灰字）、中=数值（大号）、下=「较前 N 日 ±」或缺失说明；同类平均作为最下方小字；卡片整体可点击切换曲线 |
| 曲线不画孤立点、缺口平滑跨过 | `TrendLine` 重写：过滤 null 点后按索引坐标用 Catmull-Rom→三次贝塞尔生成平滑路径；面积填充沿同一条路径闭合到 0 线；不再渲染 `<circle>` 数据点；有效点 <2 时显示「有效数据点不足（N 个），无法绘制曲线」 |
| 逐日新增只按相邻两天差值 | `_post_trend_buckets` / `_fan_net_buckets` 增加 `_is_next_day` 校验：跨天缺口的增量不再摊到后一天（避免 30/90 日曲线出现「一天涨几千」的虚高）；缺口在曲线上由平滑线跨过 |
| 30/90 日曲线点少的原因 | 本地每日快照只在实际同步日存在（历史同步非每日），TikHub 不提供历史逐日回填；因此长周期只能展示已有快照日的增量，页面小字说明 |

### 5.18 2026-11-01 v5 改版（作者第四次反馈，覆盖以上相关描述）

| 改动 | 实现 |
|---|---|
| 去掉「同类平均 xxx · 超过 xx% 同类创作者」文字 | `KpiCardView` 不再渲染 similar/rank 行，卡片只保留「指标名 / 数字 / 较前 N 日」三段；后端响应字段保留（不展示、不新增请求） |
| 激活线固定在指标卡区域底部 | 卡片 `<button>` 改 `relative flex h-full flex-col`，网格 `items-stretch`；选中时渲染 `motion.span layoutId="kpi-active-line"` 绝对定位在 `bottom-0`、`inset-x-1`，切换指标时用 spring 在卡片间平滑移动 |
| 切换数据有动画（图表/曲线/指标区） | 曲线容器以 `key={chart-${metricKey}-${periodDays}}` 重挂，`initial={{opacity:.55,y:8}} → animate={{opacity:1,y:0}}`（softIn，0.24s），不闪白、`min-h` 固定高度不跳；指标区以 `key={kpis-${periodDays}}` 在切换周期时淡入 |
| 右侧近期作品切换有动画 | 选中行高亮用 `motion.span animate={{opacity}}` 淡入；左侧竖条 `layoutId="works-selected-bar"` 在行间平滑滑动；行内容 `relative z-10` 保证在遮罩之上；列表加载仍逐条 stagger 入场 |

### 5.19 2026-11-01 增量曲线口径确认（作者第五次反馈）

作者确认：接口不返回「逐日数据」时，用 **本次抓取的累计值 - 上一次可用快照的累计值** 作为该点增量；昨天没抓时用「非今天的最近一日」快照做基线（该点包含这段间隔的累计增量）。

实现要点：
- `_post_trend_buckets` / `_fan_net_buckets` 去掉「必须相邻两天」限制 → 相邻两次**可用快照**的差值记到后一个快照日期；两端仍必须在统计周期内（避免引入窗口外基线）。
- 由此曲线各点之和 = 周期首末快照差值（与指标卡合计口径一致）；点数 = 周期内有快照的日期数，断档日期无点、由前端平滑线跨过。
- 前端图例由「（每日新增）」改为「（较上次同步增量）」，图表脚注说明「断档时该点含间隔累计」；KPI 周期合计仍取首末快照差值，不累加曲线点。
- 已知限制：`plays` 在 2026-10-30 之前的公开同步行长期为 0（清洗后剔除），所以历史播放量曲线从 10-30 起才有真实点；从今往后每日创作者同步会持续写入真实累计播放，差值即新增。

### 5.20 2026-11-01 v7 交互修正（作者第六次反馈）

| 改动 | 实现 |
|---|---|
| 去掉「较前 N 日：诊断接口无上期数据」「数据积累中」等提示 | `KpiCardView` 底部行只在 `delta !== null` 时渲染「较前 N 日 ±x」；否则空行（`min-h-4` 保持卡片等高）。`note`/`missingNote` 不再展示（后端字段保留，不删接口） |
| 悬浮即激活指标 | `KpiCardView` 增加 `onMouseEnter`（80ms 防抖避免快速划过反复重绘）+ `onMouseLeave` 取消 + `onFocus` 键盘聚焦；点击仍保留 |
| 首次切换统计周期闪屏 | `useQuery(['dashboard','overview',periodDays])` 增加 `placeholderData: keepPreviousData`；渲染判断改为 `if (!data) { isPending ? 骨架 : 错误页 }`，切周期时继续显示上一周期数据直到新数据返回，不再整页骨架闪烁 |

### 5.21 2026-11-01 v8 布局与切换动画（作者第七次反馈）

| 改动 | 实现 |
|---|---|
| 去掉蓝色激活条 | `KpiCardView` 删除 `layoutId="kpi-active-line"` 与主色数字；选中/悬浮用 `bg-muted` 浅灰圆角底色块表示，数字保持普通前景色（对齐抖音创作者中心） |
| 账号总览改左右布局 | `grid lg:grid-cols-[minmax(0,1.4fr)_minmax(0,1fr)] lg:items-start`：左栏曲线（`TrendLine height=300`，面积填充），右栏 7 个指标卡 `grid-cols-2`；移动端自动上下堆叠 |
| 切换指标曲线闪一下 | 不再用 `initial opacity` 重挂闪烁；改为**交叉过渡**：`switchMetric` 时把当前曲线存 `fadeFrom`，旧曲线绝对定位原处 `animate opacity 1→0`（0.26s），新曲线 `opacity 0→1` 同时淡入，280ms 后移除旧层；容器 `min-h` 固定高度不跳版 |
| 交互保留 | 悬浮 80ms 防抖激活、点击/键盘聚焦同样生效；`keepPreviousData` 保证切周期不闪骨架 |

### 5.22 2026-11-01 v9 精简（作者第八次反馈）

| 改动 | 实现 |
|---|---|
| 移除「总粉丝量」指标卡 | 后端 `_kpi_cards` 删除 total_fans 卡、`account_kpis` 删除 `fields.total_fans`、`series.total_fans`（账号粉丝每日快照 `creator_account_snapshots` 仍保留，用于「净增粉丝」卡片与曲线）；前端指标卡自动变为 6 个（播放量/主页访问量/作品点赞/作品分享/作品评论/净增粉丝），右栏 2 列共 3 行 |
| 删除底部口径说明整段文字 | 移除 AccountOverview 底部 `<p>` 口径段（近 7 日/14/30/90 日说明 + 悬浮提示）；数据来源说明保留在统计周期旁的 ⓘ 悬浮提示中 |
| 指标数字字号调小 | 标签 `text-xs(12px)` → `text-[11px]`；数字 `text-2xl(24px)` → `text-xl(20px)`；较前对比 `text-xs` → `text-[11px]`，卡片间距略收紧 |

### 5.23 2026-11-01 v10 精简与默认选中（作者第九次反馈）

| 改动 | 实现 |
|---|---|
| 删除曲线下方口径说明 | AccountOverview 曲线区不再渲染 `<p>增量：本次抓取值…</p>`；曲线语义说明只保留在需求/设计文档与统计周期 ⓘ 提示里 |
| 默认选中近期作品第一条 | DashboardPage 新增 effect：`selectedId === null && worksQ.data.items[0]` 时 `setSelectedId(items[0].post_id)`；详情区在此期间显示 `AnalysisSkeleton`（列表加载中）或引导（列表为空）。首屏逻辑：overview+works 并行 → works 返回后自动展开第一条详情（详情缓存缺失/超 6h 仍按既有 10 分钟防重复自动刷新） |

### 5.24 2026-11-01 v11 右栏缩窄与字号（作者第十次反馈）

| 改动 | 实现 |
|---|---|
| 右栏字号再缩小 | `KpiCardView`：标签 11px→10px、数字 20px→18px（`text-lg leading-6`）、较前对比 11px→10px；行高/间距同步收紧，右栏 2 列仍可容纳「1,619 / 较前 7 日 -1,243」 |
| 右栏让约 20% 宽度给左侧曲线 | 左右网格 `lg:grid-cols-[minmax(0,1.4fr)_minmax(0,1fr)]` → `[minmax(0,2fr)_minmax(0,1fr)]`（实测 1440 宽下左 731px / 右 357px，约 2:1）；曲线 `height=300` 保持不变，可视面积更大 |
| 移动端 | 仍为上下堆叠（先曲线后数据），字号沿用缩小后的值 |

### 5.25 2026-11-01 v12 对比数字精简（作者第十一次反馈）

| 改动 | 实现 |
|---|---|
| 指标卡底部去掉「较前 N 日：」前缀 | `KpiCardView.deltaText = formatDelta(kpi.delta)`（纯数字，含 +/− 与千分位）；不再拼「较前 N 日」；div 的 `title` 保留「较前 N 日对比：xxx」便于悬停确认语义 |
| 字号/布局不变 | 10px、18px 与 2:1 左右比例沿用 v11 |

### 5.26 2026-11-01 v13 作品总览合并（作者第十二次反馈）

| 改动 | 实现 |
|---|---|
| 移除「流量分析」「观众分析」两个 tab | `post-analysis.tsx` 删除 `FlowTab`/`AudienceTab` 组件与 tab trigger/content；tab 只剩总览/评论热词/评论管理；观看趋势/流量来源/画像分布不再渲染（API 字段保留，不删后端） |
| 总览改左右布局 | 左栏 `Panel(指标趋势)`（宽 1.5fr）：一张图展示当前悬浮指标趋势，累计类指标可切「累计/新增」；右栏 `Panel(数据)`（1fr）：18 个指标块（流量 6 + 观看质量 5 + 观众 7）2 列排布 |
| 播放量趋势与涨粉量趋势合并 | 后端新增 `metric_trends`（`_metric_trends`）：从 `douyin_post_metrics.raw.item.metrics` + `platform_post_stats` 逐日提取 18 个指标序列；前端统一用 `metric_trends[key]` 绘制，选中哪个指标就画哪条，不再有两张固定趋势图 |
| 悬浮切换曲线 | 右侧指标块 `onMouseEnter`/`onFocus` → `setMetricKey(key)`；左图标题/单位/曲线随选中指标变化；比率指标纵轴显示百分数（`TrendLine` 新增 `axisFormat`） |

### 5.27 2026-11-01 v14 布局与分页（作者第十三次反馈）

| 改动 | 实现 |
|---|---|
| 作品总览改上下布局 | `OverviewTab`：上 `Panel(指标趋势)`（全宽，高度固定），下 `Panel(数据)`（`grid-cols-2 sm:grid-cols-3 xl:grid-cols-4` 全宽），最后作品诊断；悬浮切换逻辑不变 |
| 单条作品趋势为什么只有几天 | 单条作品趋势 = 本地每日快照（`douyin_post_metrics`/`platform_post_stats` 按天写入）。TikHub 单条作品接口只返回「当前累计值」，没有起止日期参数也不提供历史逐日回填，所以历史只能从系统开始每日同步后累积（该作品 10-29 发布、10-30 首次入库，当前 3 个点）；账号总览的 7/14/30/90 天周期是账号级口径，不适用于单条作品。曲线 hint 已注明 |
| 近期作品去按钮改自动翻页 | `works-list.tsx` 删除「加载更多」按钮；列表末尾放哨兵 `IntersectionObserver`（rootMargin 120px），滚到底自动 `onLoadMore()`；底部提示「向下滑动自动加载更多 / 加载中… / 已加载全部」 |
| 评论管理一页 10 条 + 自动加载 | `CommentsTab` 增加本地分页：`PAGE_SIZE=10`、`visibleCount` 切页；列表末尾哨兵 `IntersectionObserver` 滚动加载下一批；标题显示「已展示 x/N 条」；后端仍一次返回最多 50 条（不新增接口参数） |

### 5.28 2026-11-01 v15 精简（作者第十四次反馈）

| 改动 | 实现 |
|---|---|
| 移除「作品诊断」面板 | `OverviewTab` 删除作品诊断 `Panel`（结论/说明/平均播放占比/收藏率/note 不再渲染）；后端 `diagnosis` 字段保留（其中 `avg_view_proportion` 仍作为「平均播放占比」指标的兜底值），页面不展示 |
| 数据面板一行 5 个指标 | 指标网格 `grid-cols-2 sm:grid-cols-3 xl:grid-cols-4` → `grid-cols-2 gap-y-2 sm:grid-cols-3 lg:grid-cols-5`；18 项排成 5+5+5+3 行 |

### 5.29 2026-11-01 v16 总览微调（作者第十五次反馈）

| 改动 | 实现 |
|---|---|
| 数据栏一行 6 个指标 | 指标网格 `lg:grid-cols-5` → `lg:grid-cols-6`；18 项正好 3 行（窄屏 2/3 列） |
| 底部留白过多 | 页面根容器 `pb-10`（40px）→ `pb-2`（8px），滚到底时详情卡与页面底边总留白从约 64px 降到 32px（含 main 自身 24px 内边距） |
| 去掉趋势「新增」曲线 | OverviewTab 删除累计/新增 Tabs 切换与 diff 逻辑，`points` 直接取 `metric_trends[key]` 原始每日值；`MetricSpec.kind` 仅保留作语义标注 |

---

## 6. 新增/修改表结构

### 6.1 `douyin_post_metrics` 新增 2 列（唯一表结构改动）

| 字段 | 类型 | 默认 | 说明 |
|---|---|---|---|
| `audience_portrait` | TEXT | `'{}'` | 作品观众画像原始归一化 JSON（`fetch_item_audience_portrait` 的 `data`）；按天快照保存，缺失为 `{}` |
| `audience_others` | TEXT | `'{}'` | 受众兴趣/关注热词原始归一化 JSON（`fetch_item_audience_others` 的 `data`）；缺失为 `{}` |

其余字段不变。逐字段说明见 `docs/DATABASE.md` 的 `douyin_post_metrics` 章节（实施时同步补两行 + 表总览数量不变 38 张）。

### 6.2 Alembic revision

- 文件：`backend/alembic/versions/r244dashboard_add_post_audience.py`（revision id `r244dashboard`，down_revision 指向当前 head）。
- `upgrade()`：`ALTER TABLE douyin_post_metrics ADD COLUMN audience_portrait TEXT NOT NULL DEFAULT '{}'`；`audience_others` 同理。
- `downgrade()`：drop 两列。
- 禁止启动时补列。

### 6.3 `app_kv` 新增缓存键（非结构化，无需迁移）

| key | value | 说明 |
|---|---|---|
| `douyin_dashboard:overview:{account_id}` | JSON：`{"diagnosis":{}, "analysis":{}, "diagnosis_at":"ISO", "analysis_at":"ISO", "period":{"start","end"}, "verticals":[], "warnings":[]}` | 账号诊断 + 投稿概览缓存（24h） |

### 6.4 不改动其他表

`platform_posts/platform_post_stats/platform_post_comments/douyin_creator_credentials/creators/creator_accounts` 均不改结构。

## 7. 新增/修改接口

基础路径：`/api/douyin-dashboard`，全部挂在现有 `API_DEPENDENCIES`（登录 token 校验）下。

### 7.1 `GET /api/douyin-dashboard/overview`

请求参数：`period` 可选，取值 7/14/30/90，默认 7（其它值返回 400）。

> **v3 响应结构（以代码为准）**：`period:{start,end,days,label}`、`kpis:[7 项：播放量/主页访问量/作品点赞/作品分享/作品评论/净增粉丝/总粉丝量]`、`series:{plays,homepage_visits,likes,shares,comments,net_fans,total_fans}`（每项 `{key,label,unit,mode:daily|cumulative,points:[{date,value|null}]}`）、`diagnosis`、`needs_refresh/stale/updating_task_id/warnings`；**不再返回** `analysis/fans/trend`。指标卡含 `trend_key` 供前端点击切换曲线；`net_fans` 与 7 日周期诊断一致，总粉丝量为累计曲线。以下旧示例仅保留以对照字段演进。

响应 200：

```json
{
  "account": {"id": 1, "nickname": "陈皮的使用手册（六年之约）", "avatar": "/avatars/xxx.jpg"},
  "credential": {"status": "valid", "enabled": true, "has_cookie": true, "last_success_at": "2026-11-01T06:50:36", "last_error": ""},
  "data_policy": {"is_creator": true, "blocked": false, "reason": ""},
  "private_available": true,
  "period": {"start": "2026-10-26", "end": "2026-11-01", "label": "近 7 日"},
  "diagnosis": {
    "captured_at": "2026-11-01T10:59:56",
    "plays": {"own": 88474, "similar": 32470, "rank": 0.66},
    "finish_rate": {"own": 0.1316, "similar": 0.1094, "rank": 0.5975},
    "interact": {"own": 0.0287, "similar": 0.0204, "rank": 0.6316},
    "new_fans": {"own": -63, "similar": 128, "rank": 0.0},
    "publish_count": {"own": 1, "similar": 4, "rank": 0.1962},
    "similar_count": 17367
  },
  "analysis": {"captured_at": "2026-11-01T11:04:00", "items": [
    {"key": "median_plays", "label": "条均播放量（中位数）", "value": 11887, "unit": "次"},
    {"key": "avg_like", "label": "条均点赞", "value": 287, "unit": "次"},
    {"key": "avg_comment", "label": "条均评论", "value": 25, "unit": "条"},
    {"key": "avg_share", "label": "条均分享", "value": 31, "unit": "次"},
    {"key": "avg_play_seconds", "label": "条均播放时长", "value": 16.4, "unit": "秒"},
    {"key": "bounce_2s_rate", "label": "条均 2s 跳出率", "value": 0.3055, "unit": "ratio"},
    {"key": "finish_5s_rate", "label": "条均 5s 完播率", "value": 0.4782, "unit": "ratio"},
    {"key": "cover_click_rate", "label": "条均点击率", "value": 0.2084, "unit": "ratio"},
    {"key": "submission_count", "label": "周期投稿量", "value": 1, "unit": "篇"}
  ]},
  "fans": {
    "total": {"value": 59063, "date": "2026-10-31"},
    "net": {"value": -63, "similar": 128, "rank": 0.0},
    "acquired": null, "lost": null, "returning": null,
    "unavailable": ["吸粉量", "脱粉量", "回访粉丝量"],
    "note": "总粉丝量取本地账号每日快照；粉丝净增取账号诊断。吸粉量/脱粉量/回访粉丝量：TikHub 未提供账号级粉丝流水接口，暂无数据。"
  },
  "kpis": [
    {"key": "plays", "label": "播放量", "value": 88474, "prev": null, "delta": null, "source": "diagnosis", "available": true, "note": "较前 7 日：诊断接口不返回上期"},
    {"key": "homepage_visits", "label": "主页访问量", "value": null, "prev": null, "delta": null, "source": "snapshot", "available": false, "note": "数据积累中（已有 2 天）"},
    {"key": "likes", "label": "作品点赞", "value": 0, "prev": null, "delta": null, "source": "snapshot", "available": true, "note": ""},
    {"key": "shares", "label": "作品分享", "value": 0, "prev": null, "delta": null, "source": "snapshot", "available": true, "note": ""},
    {"key": "comments", "label": "作品评论", "value": 0, "prev": null, "delta": null, "source": "snapshot", "available": true, "note": ""},
    {"key": "new_fans", "label": "净增粉丝", "value": -63, "prev": null, "delta": null, "source": "diagnosis", "available": true, "note": "较前 7 日：诊断接口不返回上期"}
  ],
  "trend": {
    "available": false,
    "note": "数据积累中：需要至少 2 天相邻快照，当前已有 2 天",
    "points": [{"date": "2026-10-26", "value": null}, "..."],
    "coverage": {"posts": 0, "dates": ["2026-10-30", "2026-10-31"]}
  },
  "needs_refresh": false,
  "stale": false,
  "updating_task_id": null,
  "warnings": ["作品评论：快照覆盖较少，仅供参考"]
}
```

错误：500 仅未预期异常；账号类问题不报错（`account=null` 或 `private_available=false`）。

### 7.2 `GET /api/douyin-dashboard/works?limit=20&offset=0`

- `limit` 1~50，默认 20；`offset` ≥0。
- 响应 200：

```json
{
  "items": [{
    "post_id": 1952,
    "title": "我真绷不住了，到底谁在赚钱啊 #赚钱 #理财 #…",
    "cover_url": "/covers/abc.jpg",
    "publish_time": "2026-10-29T21:45:05",
    "status": "approved",
    "status_label": "通过",
    "plays": 13700,
    "likes": 330,
    "comments": 26,
    "shares": 35,
    "has_detail": true,
    "data_time": "2026-11-01T10:59:56"
  }],
  "total": 25,
  "has_more": false
}
```

- `status` 枚举：`approved / private / rejected / published / unknown`。
- 无账号 → 400（detail 同 5.1 文案）。

### 7.3 `GET /api/douyin-dashboard/works/{post_id}`

响应 200（核心字段）：

```json
{
  "post": {"post_id": 1952, "title": "…", "cover_url": "/covers/abc.jpg", "publish_time": "2026-10-29T21:45:05",
           "video_url": "https://www.douyin.com/video/7702085414127247306", "duration_seconds": 86,
           "status": "approved", "status_label": "通过"},
  // video_url 固定为抖音作品页 https://www.douyin.com/video/{platform_post_id}
  // （平台同步里的 video_url 可能是 CDN 直链，数据看板「查看原视频」要的是可打开的抖音页面）
  "data_time": "2026-11-01T10:59:56",
  "cached": true,
  "stale": false,
  "private_available": true,
  "overview": {"plays": 13700, "likes": 330, "comments": 26, "shares": 35, "favorites": 52, "danmaku": 0,
               "finish_rate": 0.075, "finish_5s_rate": 0.471, "bounce_2s_rate": 0.3089,
               "avg_play_seconds": 16.2, "avg_view_proportion": 0.1889},
  "play_trend": {"available": true, "mode": ["daily"], "points": [{"date": "2026-10-30", "total": 6735, "added": null}, {"date": "2026-10-31", "total": 6941, "added": 206}]},
  "fans": {"follower_gain": 14, "unsubscribe": 38, "fan_view_proportion": 0.686},
  "diagnosis": {"conclusion": "流量低于平时", "detail": "这条视频播放 13700，你近 30 条相近视频在相同发布天数的中位数是 11887（样本 10 条）。",
                "avg_view_proportion": 0.1888, "favorite_rate": 0.0038, "baseline_plays": 11887, "sample_count": 10},
  "flow": {
    "retention": {"points": [{"key": "00:00", "current": 0.9, "similar": 0.85}], "reliable": true},
    "bounce": {"points": [], "reliable": false},
    "sources": [{"name": "推荐页", "ratio": 0.742}],
    "unavailable": ["平台扶持流量（TikHub 未提供）"]
  },
  "audience": {
    "cards": [{"key": "subscribe", "label": "涨粉量", "value": 14, "unit": "人"}, "..."],
    "fan_trend": {"available": false, "points": [], "note": "数据积累中"},
    "gender": [{"key": "male", "label": "男性", "ratio": 0.9616}],
    "active": [{"key": "4", "label": "重度", "ratio": 0.8347}],
    "age": [{"key": "18-23", "ratio": 0.4239}],
    "provinces": [{"name": "广东", "ratio": 0.2462}],
    "city_levels": [{"name": "新一线", "ratio": 0.3014}],
    "interests": [{"name": "随拍", "ratio": 0.25}],
    "keywords": [{"word": "今日金价", "heat": 20382486}]
  },
  "comment_words": {"total_comments": 20, "items": [{"word": "工作", "count": 2}], "note": "基于已同步 20 条评论统计，与抖音官方口径可能不同"},
  "comments": {"total": 20, "items": [{"id": 1, "user": "7", "text": "现在这油价，老老实实骑小电驴吧", "likes": 0, "synced_at": "2026-10-31T07:12:00"}]},
  "updating_task_id": null,
  "warnings": []
}
```

错误：404 作品不存在/不属于当前账号；400 无账号。

### 7.4 `POST /api/douyin-dashboard/overview/refresh`

- 请求体：无（`{}`）。
- 响应 202：`{"task_id": 123, "reused": false}`；运行中已存在 → `{"task_id": 123, "reused": true}`（仍 202）。
- 错误 400（文案）：无主博主 / 抖音账号未绑定 / 创作者数据未开启 / Cookie 失效（`policy.is_blocked`）/ 额度不足。
- 任务 kind：`douyin_dashboard_overview`，payload `{"account_id": 1}`，进度 10/60/90/100，note：获取账号诊断/同步作品快照/写入缓存/完成（v3 起无投稿概览步骤）。
- 任务 result：`{"ok": true, "diagnosis_at": "...", "warnings": []}`。

### 7.5 `POST /api/douyin-dashboard/works/{post_id}/refresh`

- 请求体：`{"force": false}`（`force=true` 跳过 6h 缓存检查，用于手动刷新）。
- 响应：
  - 缓存 <6h 且非 force → 200 `{"skipped": true, "reason": "数据已是最新（6 小时内）", "data_time": "..."}`；
  - 需要刷新 → 202 `{"task_id": 124, "reused": false}`；运行中 → 202 `reused=true`。
- 错误：404 作品不存在；400 创作者数据不可用/额度不足。
- 任务 kind：`douyin_dashboard_post`，payload `{"post_id": 1952, "account_id": 1}`；进度 5/20/40/60/75/90/100；note：缓存检查/获取作品指标/流量与趋势/观众画像/受众兴趣/同步评论/完成。
- 任务 result：`{"ok": true, "post_id": 1952, "data_time": "..."}`。

### 7.6 公共错误响应

| HTTP | detail 示例 | 触发 |
|---|---|---|
| 400 | 请先创建并切换主博主 | 无 owner |
| 400 | 请先绑定当前主博主的抖音账号 | 无账号 |
| 400 | 当前账号未开启创作者数据，暂时无法获取私有指标 | policy 非 creator |
| 400 | 抖音创作者 Cookie 已失效，请在「博主管理 → 编辑账号」重新保存抖音创作者 Cookie | policy blocked |
| 400 | 今日 TikHub 请求额度不足（剩余 X 次，本次需要 Y 次） | 预算不足 |
| 404 | 作品不存在 / 作品不属于当前主博主 | post 校验 |
| 500 | 服务器内部错误（不暴露 Cookie/Key） | 未预期异常 |

## 8. 数据来源与原始字段明细

### 8.1 TikHub 接口清单

| 接口（`base_url=https://api.tikhub.io/api/v1`） | 方法 | 请求字段 | 返回关键字段 | 请求数 | 更新频率 |
|---|---|---|---|---|---|
| `/douyin/creator_v2/fetch_author_diagnosis` | POST | `cookie` | `Interact/NewFans/PlayCnt/PlayFinishRatio/PublishActivation` 各自 `OwnValue/SimilarValue/AuthorRank` | 1 | 每日 12 点后（账号「更新数据」时拉） |
| `/douyin/creator_v2/fetch_item_analysis_involved_vertical` | POST | `cookie,start_date,end_date`（字符串 YYYYMMDD） | `primary_verticals: string[]` | 1 | 同账号更新 |
| `/douyin/creator_v2/fetch_item_analysis_overview` | POST | `cookie,start_date,end_date,primary_verticals` | 9 个 `{metric_name,metric_value}` | 1 | 同账号更新 |
| `/douyin/creator_v2/fetch_item_list` | POST | `cookie,start_time,end_time,count,fields="metrics,review,visibility"` | `items[]`（`id/create_time/description/cover/metrics/review/visibility`） | 2（近 120 天分页） | 同账号更新（复用 `sync_account_creator_data`） |
| `/douyin/creator_v2/fetch_item_overview_data` | POST | `cookie,ids,fields="metrics,play_info,content_analysis"` | `items[0].metrics`（25 字段）、`video_info` | 1 | 作品「更新数据」 |
| `/douyin/creator_v2/fetch_item_play_source` | POST | `cookie,item_id` | `play_source: [{key,value}]` | 1 | 同上 |
| `/douyin/creator_v2/fetch_item_search_keyword` | POST | `cookie,item_id` | `inspire_search/show_from` | 1 | 同上（本页不展示，视频复盘用） |
| `/douyin/creator_v2/fetch_item_watch_trend` | POST | `cookie,item_id,analysis_type(1/7)` | `analysis_trend.current_item/similar_author` | 2 | 同上 |
| `/douyin/creator_v2/fetch_item_audience_portrait` | POST | `cookie,item_id` | `active/gender/age/province/city_level/career/new_user` | 1 | 同上；落库新列 |
| `/douyin/creator_v2/fetch_item_audience_others` | POST | `cookie,item_id` | `audience_preference/audience_search_most_keywords/audience_prefer_similar_authors` | 1 | 同上；落库新列 |
| `/douyin/app/v3/fetch_video_comments`（既有公开接口，经 `sync_post_comments`） | GET | `aweme_id,count≤50` | 评论列表 | 1 | 作品「更新数据」 |

**Cookie 安全**：只在请求体使用；不写日志、不进任务 payload、不出现在响应；`_post` 已保证不记录请求体。

### 8.2 原始字段 → 落库字段 → 页面用途

| 原始字段 | 中文含义 | 落库位置 | 页面用途 | 空值处理 |
|---|---|---|---|---|
| `PlayCnt.OwnValue` | 近 7 日账号播放量 | `app_kv` overview 缓存 `diagnosis.plays.own` | 账号总览「播放量」 | 保留上次成功值；无则「暂无数据」 |
| `PlayFinishRatio.OwnValue` | 近 7 日完播率 | 同上 `.finish_rate.own` | 同类对比区 | 缺失不显示该项 |
| `Interact.OwnValue` | 近 7 日互动指数 | 同上 `.interact.own` | 同类对比区 | 缺失不显示 |
| `NewFans.OwnValue` | 近 7 日净增粉丝 | 同上 `.new_fans.own` | 「净增粉丝」 | 同上 |
| `PublishActivation.OwnValue` | 近 7 日投稿数 | 同上 `.publish_count.own` | 同类对比区 | 同上 |
| `*.SimilarValue/AuthorRank` | 同类平均/排名分位 | 同上 `.similar/.rank` | 「同类创作者平均/超过 x%」 | 缺失不显示 |
| `metric_value`（analysis_overview 各键） | 条均指标 | 同上 `analysis.items` | 条均指标区 | 缺失「暂无数据」 |
| `item.id` | 作品 ID | `platform_posts.platform_post_id`（既有） | 列表/详情定位 | — |
| `item.create_time`（秒字符串） | 发布时间 | `platform_posts.publish_time`（既有） | 列表时间/排序 | 缺失「未记录」 |
| `item.description` | 标题/文案 | `platform_posts.title`（既有） | 列表标题 | 空字符串 |
| `item.cover.url_list[0]` | 封面 | `platform_posts.cover_url`（既有） | 列表封面 | 占位块 |
| `item.review.status` | 审核状态 | `douyin_post_metrics.raw.item.review` | 列表状态 | 「状态未知」 |
| `item.visibility.status` | 可见状态 | `douyin_post_metrics.raw.item.visibility` | 列表状态（私密优先） | 「状态未知」 |
| `item.metrics.view_count` | 播放量 | `platform_post_stats.plays`（既有）+ raw | 详情总览/趋势 | 0 即真实 0 |
| `like_count/comment_count/share_count/favorite_count/danmaku_count` | 互动 | `platform_post_stats` 对应列 + raw | 总览流量卡 | 缺失「暂无数据」 |
| `completion_rate/bounce_rate_2s/completion_rate_5s/avg_view_second/avg_view_proportion/favorite_rate` | 观看质量 | raw（既有） | 流量分析/作品诊断 | 同上 |
| `subscribe_count/subscribe_rate/unsubscribe_count/unsubscribe_rate/dislike_count/dislike_rate/fan_view_proportion` | 粉丝相关 | raw（既有）+ `douyin_post_metrics.follower_gain` 保留累计涨粉 | 总览粉丝卡/观众分析/涨粉趋势 | 同上 |
| watch_trend `analysis_type=1` 的 `current_item/similar_author` | 留存曲线 | `douyin_post_metrics.retention_trend/similar_author_trend`（既有） | 观看趋势（留存） | 空数组 → 「暂无数据」 |
| watch_trend `analysis_type=7` | 跳出曲线 | `bounce_trend`（既有） | 观看趋势（跳出） | 同上 |
| play_source `play_source[{key,value}]` | 流量来源 | `traffic_sources`（既有，中文名归一） | 流量来源 | 空 → 「暂无数据」 |
| audience_portrait `active/gender/age/province/city_level` | 观众画像 | **新增列** `audience_portrait` | 观众分析 | `{}` → 各维度「暂无数据」 |
| audience_others `audience_preference.total_data` | 受众兴趣 | **新增列** `audience_others` | 受众兴趣分布 | 空 → 「暂无数据」 |
| audience_others `audience_search_most_keywords` | 受众关注热词 | 同上 | 受众关注热词 | 空 → 「暂无数据」 |
| 公开评论 `text/likes/user_nick` | 评论 | `platform_post_comments`（既有） | 评论管理/评论热词 | 空 → 空状态 |

### 8.3 现有表字段复用

| 表 | 字段 | 用途 |
|---|---|---|
| `platform_posts` | id/account_id/platform_post_id/title/cover_url/cover_path/publish_time/video_url/raw | 近期作品列表与详情头部 |
| `platform_post_stats` | post_id/stat_date/plays/likes/comments/shares/favorites | 列表指标、详情流量卡、播放趋势、7 日 KPI 差值 |
| `douyin_post_metrics` | post_id/snapshot_date/captured_at/bounce_2s_rate/finish_5s_rate/finish_rate/avg_play_seconds/cover_click_rate/profile_visits/follower_gain/traffic_sources/search_terms/retention_trend/bounce_trend/similar_author_trend/raw | 详情指标、观看趋势、流量来源、7 日 KPI（主页访问量/涨粉趋势） |
| `platform_post_comments` | post_id/user_nick/text/likes/created_at | 评论列表、评论热词 |
| `creator_accounts` | id/nickname/avatar | 页面账号信息 |
| `douyin_creator_credentials` | status/enabled/last_success_at/last_error | 凭证状态与更新时间 |
| `creators` / `creator_accounts` | 当前主博主解析 | 数据归属 |
| `app_kv` | 新键 `douyin_dashboard:overview:{id}` | 账号诊断/投稿概览缓存 |
| `background_tasks` | 任务进度/结果 | 「更新数据」进行中与恢复 |

### 8.4 程序计算字段

| 派生字段 | 输入 | 公式/规则 | 输出位置 |
|---|---|---|---|
| 7 日 KPI 合计 | 作品快照两日差值 | 见 5.4 | GET overview `kpis` |
| 较前 7 日 | 上周期同样算法 | 见 5.4 第 5 条 | `kpis[].delta` |
| 逐日播放 | 相邻日快照差值 | 见 5.4 | `trend.points` |
| 播放趋势（作品） | 该作品 `platform_post_stats` 日序列 | `新增=max(0,今-昨)` | 详情 `play_trend` |
| 涨粉趋势（作品） | `follower_gain` 日序列 | 同上 | 详情 `audience.fan_trend` |
| 状态标签 | `review/visibility` | 见 5.6 表 | 列表 `status_label` |
| 活跃分布标签 | `active[].key` | 见 5.9 映射表 | `audience.active[].label` |
| 受众兴趣 Top | `total_data.ratio_data` | 降序、过滤「未分类」、取前 6 | `audience.interests` |
| 关注热词 Top | `query_cnt_7d` | 降序取前 8、万/亿格式化 | `audience.keywords` |
| 评论热词 | 评论 text 列表 | 见 5.11 | `comment_words` |
| 作品诊断结论 | `build_comparison.facts` | 见 5.13 | `diagnosis.conclusion/detail` |
| 同类排名百分比 | `AuthorRank` | `round(rank*100)` | 「超过 x%」 |
| 数据更新时间 | 各来源 `captured_at/updated_at` | 分来源取最近成功时间 | `data_time/needs_refresh/stale` |

### 8.5 作者输入字段

本页**不收集任何作者输入**（不改 Cookie、不填参数）；所有数据由 TikHub + 本地同步产生。作者只做「点选查看/点更新数据」操作。Cookie 的录入仍在「博主管理 → 编辑账号」（既有功能）。

### 8.6 空值、0 与更新时间统一规则

- **NULL**：平台未返回、未识别、无权限、历史不足 → 页面「暂无数据 / 数据积累中 / —」。
- **0**：平台明确返回 0 → 显示 0（例如弹幕量 0、播放量 0 的私密作品）。
- **空数组/空对象**：来源接口返回但没有项目 → 对应区块空状态 + 说明，不用 0 填充。
- **更新时间**：账号诊断/投稿概览用缓存 `captured_at`；作品详情用 `douyin_post_metrics.captured_at`；列表指标用 `platform_post_stats.stat_date`；评论用 `platform_post_comments.created_at`（同步时间）；页面分别显示，不合并成「实时」。
- **负数**：净增粉丝可为负（真实）；点赞/播放等增量类派生值出现负值按 0 处理并在 warnings 记录。

## 9. 测试、验证与实施计划

### 9.1 后端单测清单（`tests/test_r244_douyin_dashboard.py`）

1. `status_label` 映射：review=2/visibility=1→通过；visibility=3→私密；review=4→不适宜公开；缺字段→状态未知；raw 无状态→—。
2. `raw` 合并：先有 review/visibility，overview 刷新后仍保留。
3. 7 日 KPI：构造两条作品 × 多天快照（含新增作品首日、缺日期、负增量），断言合计/覆盖/较前 7 日 null 规则。
4. 逐日趋势：缺日期断开、<2 天 available=false。
5. 评论热词：停用词过滤、同评论去重、子串去重、阈值、空输入、确定性。
6. 活跃分布映射：`-1/1/2/3/4 → 未知/低活/轻度/中度/重度`。
7. 诊断归一化：真实样例 JSON → `plays.own/similar/rank`。
8. 接口冒烟（mock 模式）：GET overview 无账号 200 空状态；GET works 200；GET works/{id} 404；POST refresh 无账号 400。
9. 预算不足：mock `get_budget` 剩余 0 → POST 400 文案。
10. 详情缓存 6h：`captured_at` 新 → refresh 返回 200 skipped。

### 9.2 前端单测与点检

- `format.test.ts`：百分比（0.075→7.5%）、万/亿格式（20382486→2038.2 万）、增减符号、0/缺失差异、状态文案映射。
- `charts` 纯函数测试：折线点为空时断开、环形图占比总和、年龄柱顺序。
- 点检（Playwright）：进入 `#/dashboard` 无整页骨架闪烁；点作品后详情展开；5 个 tab 切换无白屏；「更新数据」按钮 spinner；刷新浏览器后进行中状态恢复；1440×900 与 390×844 无横向滚动。

### 9.3 验证命令

```
scripts/verify.sh            # ruff + mypy + pytest + 前端 lint/vitest/build + 文档一致性
cd frontend_v2 && npm run gen:api   # 后端在 8000 起来后生成 schema
# 真实联调（TikHub real + 作者账号）：后端 8000 + 前端 3000，点一遍账号/作品更新数据
```

### 9.4 实施顺序（作者说「继续」后）

1. 建分支 `feat/r244`；后端：模型列 + Alembic + TikHub 5 方法（含 mock）。
2. 后端：`douyin_dashboard.py` 服务（账号/缓存/KPI/趋势/详情/热词/诊断/任务）+ API + main/task_meta 注册。
3. 后端测试 + `docs/DATABASE.md` 同步；跑 `pytest`。
4. `gen:api` 生成前端类型；前端页面（列表 → 总览 → 详情 5 tab → 动效）+ 路由/导航。
5. 前端单测；`verify.sh` 全绿。
6. 真实联调（TikHub real）：账号总览、至少 1 条作品的 5 个 tab、更新数据/失败场景；截图点检。
7. 仓库文档（DATABASE/CHANGELOG/milestones/requirements README）+ 提交；`feat/r244` 合并 main 并 push。

### 9.5 风险与回滚

| 风险 | 应对 |
|---|---|
| TikHub 接口字段变化 | 解析放在 `douyin_dashboard.py` 单点，用 `.tmp/dashboard/` 真实样例做测试夹具；未知字段降级为「暂无数据」而非报错 |
| 活跃分布映射误标 | 已在设计留证据；若作者核对抖音页面发现不一致，只改一张映射表 |
| 快照覆盖不足导致数字与官方不一致 | 页面始终显示「覆盖 N 条作品」+「数据积累中」；播放量/净增粉丝大数字用官方诊断口径 |
| 额度被误刷 | 6h/24h 缓存 + 自动刷新每会话一次 + 预算预检 + 任务去重 |
| 详情刷新耗时（8 次请求） | 后台任务 + 进度 + 切页恢复；限速 10req/s 下约 1~2 秒 |
| 评论区写操作诉求 | 明确只读，说明去抖音操作；后续若 TikHub 支持再立项 |

回滚：只新增 2 列与 2 张表的读取逻辑不被其他功能依赖；回滚 `scripts/verify.sh` 通过后 revert 本需求 commit 并 downgrade Alembic 即可，不影响既有功能。
