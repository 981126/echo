# R-233-DEEPSEEK-SEARCH-REFS: 脚本生成联网参考（豆包 + DeepSeek 双源搜索 · Fetch 正文 · 去营销 · 生成方按人设选文）

- **日期**: 2026-10-18
- **提出渠道**: 对话
- **原文摘要**: 脚本生成的「网上抓取素材」新增 DeepSeek 搜索；豆包与 DeepSeek 同时 search、Fetch 正文；排除营销内容；由脚本生成方根据当前主博主人设选定某几篇作为参考参与生成。
- **状态**: ✅ 已确认（待实施）
- **排期**: M234
- **关联**: `backend/app/services/web_search.py`、`deepseek_search.py`（新）、`evidence.py`、`debate.py`、`models/web_search.py`、`frontend_v2/src/components/evidence-panel.tsx`、`docs/DATABASE.md`、R-227 / R-228 / R-229 / R-230

## 背景与现状

R-227 已给生成/洗稿接上「联网事实」，但只有豆包一路，且只用 `Summary`：

- 豆包 `Content` 实测与 `Summary` 等长（约 600–900 字），本质仍是摘要，模型拿不到正文细节；
- 没有任何正文抓取，事实颗粒度停在「一段二手概述」；
- 没有营销内容过滤，搜索结果里的卖课、引流、聚合号会被直接喂给模型；
- 来源是整份清单硬塞进 prompt，模型没有「选哪几篇」的决策权，人设与选题的匹配靠模型自己在写作时消化。

R-233 把这一层升级为：**双源并行搜索 → 正文补齐 → 去营销 → 生成方按人设选文 → 只把选中的正文注入生成**。

## 作者确认的边界（2026-10-18）

1. **接入范围**：脚本生成（双模型讨论）+ 洗稿两条链路；两者共用 `evidence.py`，一次改完，每日自动生成随之生效。
2. **选文方式**：先选后写——生成方模型先看「人设 + 候选标题/摘要」，输出 2–3 篇编号与理由，再把这些文章的正文喂给初稿。多一次 LLM 调用（约 5–10 秒），换取干净上下文与可核对留痕。
3. **数量与正文**：每家搜 5 条 → 去重/过滤后最多抓 4 篇 → 选 2–3 篇；每篇正文按与选题相关度抽段，不超过 2000 字。
4. **营销口径**（全部排除）：硬广带货、私域引流、卖课/培训/代运营/咨询招生、品牌软文/通稿、内容农场/标题党聚合站。
5. **过滤方式**：规则先筛（域名 + 关键词 + 引流话术）+ 选文提示词兜底；不额外跑模型判定。
6. **留痕与展示**：界面展示已选 2–3 篇（来源/标题/链接/选文理由）；库里保留全部候选与正文，便于事后核对与调 prompt。
7. **降级**：DeepSeek 复用现有 `ECHO_DEEPSEEK_API_KEY`；未配 key 时自动只跑豆包，不阻断生成。

## 方案

### 1. 双源并行搜索

- 新增 `backend/app/services/deepseek_search.py`：
  - `enabled()`：有 `deepseek_api_key` 即可用（可加总开关）；
  - `search(query, count)`：`POST {deepseek_base_url}/v1/tools/search`，`need_content=true`、`count=5`，返回归一化结构；
  - `fetch(url)`：`POST /v1/tools/fetch`，返回 Markdown 正文；
  - 429/408/5xx 重试一次（退避 0.5s），其余失败静默返回空；按账号 5 QPS 做进程内限速。
- `evidence.gather_online()` 用 `ThreadPoolExecutor(2)` 同时发豆包 / DeepSeek 两路请求；单路超时/失败不影响另一路。
- 归一化字段统一：`provider`（doubao/deepseek）、`title`、`url`、`snippet`、`summary`、`content`、`site`、`date`、`rank`、`authority`。

### 2. 合并、去重、过滤

顺序固定，每步都可单测：

1. **URL 规范化去重**：去 `utm_*` 等追踪参数与 fragment，同 URL 合并，保留信息更全的一条并记双 provider；
2. **标题近重去重**：去标点/空白后 bigram Jaccard > 0.8 视为同篇；
3. **相关度过滤**：沿用 `filter_relevant()`（选题关键词 + 中文 bigram）；
4. **文章类型过滤**：剔除 GitHub/GitLab 的 `blob` 代码页、`skill`/`README` 类文件页、纯导航页（实测 DeepSeek 会把 GitHub 的 skill 文件搜进来）；
5. **营销过滤**（规则，命中即剔除并记原因）：
   - 站点黑名单（可配）：`k.sina.com.cn`、`baijiahao.baidu.com`、`*.sohu.com/a/`、`*.163.com/dy/`、`*.qq.com/omn/` 等自媒体聚合域；
   - 转化话术：加微信/加V/扫码/私信/进群/领取/报名/下单/购买/优惠/直播间/橱窗 等，≥2 个不同信号或出现在标题/前 200 字；
   - 招生话术：训练营/陪跑/代运营/一对一/招生/课程 + 报名/咨询/价格 组合；
   - 电商域：淘宝/天猫/京东/拼多多/1688 等。
   - 阈值与词表进配置，误杀可通过日志与留痕复盘调整。

### 3. 正文补齐（Fetch）

- 优先级：DeepSeek Search 的 `content`（实测 1.5k–3k 字，知乎可拿到）→ 内容过短（< 800 字）再调 `deepseek_search.fetch(url)` → 仍失败则退回 `summary`；
- 最多补抓 `online_fetch_max=4` 篇，并发 ≤3，单请求 15s，总预算 25s；超预算的直接用已有正文/摘要，不阻断生成；
- 正文裁剪：先保留开头 400 字，再按与「选题 + 人设关键词」的 bigram 相关度抽段拼接到 ≤2000 字，附 `content_chars` 供留痕与界面显示。

### 4. 生成方按人设选文

- 新增 `evidence.select_references()`：用**生成方槽位的模型**（`gen_llm`）跑一次轻量 `chat_json`：
  - 输入：当前主博主人设（标签/红线/风格画像摘要）+ 选题 + 候选清单（编号、标题、站点、日期、≤200 字摘要）；
  - 输出：`{"picks":[{"id":1,"reason":"提供什么事实/为何贴合人设"}],"reject":[{"id":3,"reason":"卖课"}]}`；
  - 约束：只能选 2–3 篇，营销/软文/课程招生一律不选；理由必须是「提供什么事实/案例/观点」，不能是「写得好」；
  - 解析失败/超时/编号越界 → 自动兜底按「相关度 + 权威度」取前 2 篇，理由标「自动兜底」。
- 选文只发生在初稿前一次；N 轮评审/修订沿用同一批已选正文（保证讨论基于同一事实集）。

### 5. 注入与引用

- 证据块只包含**已选文章**：
  ```
  【联网参考·生成方选文（营销内容已排除）】
  [参考1] 标题（站点 日期 URL）
      正文节选：…
  [参考2] …
  【引用规则】只能引用以上参考中的事实/数据/观点，口语化转述；引用编号写进 sources 字段。
  ```
- `sources` 编号只对已选清单解析（`resolve_used(selected, ...)`），越界仍剔除，防编造来源；
- 未选中候选不再进入 prompt，只在 `Draft.quality.online_sources` 留痕。

### 6. 留痕与展示

- `web_search_logs`：豆包、DeepSeek 各写一行（`source=doubao|deepseek`），`results` 保存该路完整候选（含正文/过滤原因），`used` 回写最终被选中的 URL；
- `Draft.quality` 新增/调整：
  - `online_sources`：全部候选（含 `provider`、`marketing` 标记）；
  - `references`：已选 2–3 篇（`provider/title/url/site/date/reason/content_chars`）；
  - `sources`：正文实际引用到的来源（与 `references` 对应）；
  - `search_queries`：两路 query + 原始条数 + 耗时。
- 前端 `evidence-panel`：来源 tab 顶部显示「已选参考 N」，每条带 provider 徽标与选文理由；可展开全部候选（含被过滤原因），沿用现有摘要卡样式。

### 7. 配置与降级

| 配置 | 默认 | 说明 |
|---|---|---|
| `ECHO_DEEPSEEK_SEARCH_ENABLED` | true | 有 key 才生效；可单独关 |
| `ECHO_DEEPSEEK_SEARCH_COUNT` | 5 | 单路返回条数 |
| `ECHO_ONLINE_FETCH_ENABLED` | true | 是否补抓正文 |
| `ECHO_ONLINE_FETCH_MAX` | 4 | 单次最多补抓篇数 |
| `ECHO_ONLINE_FETCH_TIMEOUT_SECONDS` | 15 | 单请求超时 |
| `ECHO_ONLINE_FETCH_CHARS` | 2000 | 单篇正文上限 |
| `ECHO_ONLINE_BUDGET_SECONDS` | 25 | 搜索+抓取总预算 |
| `ECHO_ONLINE_REF_PICK` | 2–3 | 选文篇数 |
| `ECHO_ONLINE_SITE_BLACKLIST` | 见上 | 逗号分隔 |
| `ECHO_ONLINE_SEARCH_ENABLED` | true | 测试总开关（conftest 置 0 防真联网） |

- 任一路不可用 → 只用另一路；两路都不可用 → 证据块为空，生成照旧；
- 选文失败 → 自动兜底 2 篇；
- 全部候选被营销/相关度过滤 → 不硬塞，证据块为空（与 R-227 口径一致）。

## 已实测的技术事实（2026-10-18）

- `POST https://api.deepseek.com/v1/tools/search` 用现有 key 调通；`need_content=true` 时知乎文章返回 2656 字正文；
- `POST /v1/tools/fetch` 对知乎返回 404（站点反爬），对 GitHub blob 只返回页面壳子 → **不能只靠 Fetch**；
- 豆包 `Content` 与 `Summary` 等长（600–900 字），没有更长正文；
- DeepSeek 结果会混入 GitHub skill/代码文件，必须做文章类型过滤；
- 计费：Search / Fetch 各 5 元/1000 次成功请求；账号级各 5 QPS；单次生成成本 < 1 分钱。

## 验收标准

1. 一次真实生成（脚本生成或洗稿）后，`web_search_logs` 有 doubao + deepseek 两行，`query`/`results`/`used` 齐全；
2. `Draft.quality.references` 恰好 2–3 篇，每篇有 `reason`，且正文块只含这些文章；
3. 候选里能明确识别并剔除营销样本（课程招生、加微信、电商、聚合号），留痕可查过滤原因；
4. DeepSeek key 置空时，生成仍成功且只用豆包结果；
5. 前端依据面板能看到「已选参考 N」、provider、链接与理由；展开可见全部候选；
6. 知乎类正文能拿到（走 Search content），Fetch 失败的站点自动退回摘要且不报错；
7. `scripts/verify.sh` 全绿；作者用同一选题做新旧 A/B，正文事实密度与「像作者」不退化。

## 明确不做

- 不引入向量库/爬虫集群/第三方正文解析服务；
- 不做「让用户手动勾选参考文章」的交互（选文由生成方完成；作者可事后在留痕里核对）；
- 不改洗稿/生成的既有模型路由与降级策略（选文复用生成方槽位）；
- 不把营销过滤做成单独的模型调用（本版只用规则 + 提示词兜底）；
- 不动灵感池/随手记（它们当前不经过 `gather_online`）。

## 风险

- 国内站点反爬导致 Fetch 成功率不稳定 → 以 Search `need_content` 为主路径，Fetch 仅补齐；
- 营销词表误杀知识类文章 → 词表配置化 + 留痕记录原因，按真实样本迭代；
- 多一次选文 LLM 调用拉长生成链路 → 设 20s 超时与自动兜底，整体仍在原讨论耗时的可接受范围；
- 并发生成时触发 DeepSeek 5 QPS → 进程内限速 + 429 重试。

## 原文（作者原话，未改动）

> 脚本生成网上抓取素材新增deepseek搜索（https://api-docs.deepseek.com/zh-cn/guides/search），豆包和deepseek同时search，Fetch正文，排除营销内容，由脚本生成方根据当前主博主人设来选定某几篇作为参考参与生成
