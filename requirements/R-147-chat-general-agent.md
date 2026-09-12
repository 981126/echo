# R-147 AI 对话升级为通用型 agent（P0 多步可见 + P1 只读 SQL + P2 写操作确认）

- **日期**: 2026-09-12
- **状态**: ✅ 已完成（2026-09-12，M136）
- **关联**: R-017（AI 对话）、R-146（工具必须暴露总数）、R-139/R-143（模型路由与预算）、`services/chat_service.py`、`api/chat.py`、`ChatView.vue`

## 原文（作者原话，未改动）
> 有办法让ai对话像个通用型agent吗
>
> p0-p2都做了

（上下文：AI 给出 P0「多步与过程可见」/ P1「只读 SQL 任意查询」/ P2「写操作人机确认」三档方案，
并说明 P3「沙箱跑代码」风险过高建议不做；作者确认 **P0+P1+P2 都做**。）

## 现状与差距
| 能力 | 现状 | 目标 |
|---|---|---|
| 多步 | `for _ in range(3)`，超限抛「未收敛」 | 回合上限可配（默认 8）+ 工具调用预算 + 墙钟超时，超限**优雅收尾**（用已有信息作答） |
| 过程可见 | SSE 是"全算完再打字机吐字"，多轮时只看到转圈 | **步骤级流式**：每步工具名/参数/结果摘要实时下发，前端画步骤条 |
| 任意查询 | 只有 9 个写死函数 | 新增**只读视图** + `sql_query` 工具（只允许查视图、单条 SELECT、只读连接、自动 LIMIT、超时） |
| 写操作 | 只靠提示词要"同意" | **代码级确认协议**：写工具只产出 `pending_action`，作者点确认才执行 + `agent_actions` 审计 |

## 范围
### P0
1. `ChatService.reply(..., on_step=None, max_rounds=None)`：回合上限取 `app_kv`/`.env`（默认 8），
   并限制工具调用总次数（默认 16）与墙钟（默认 120s）；到限时**带上已获得的数据继续作答**，不再抛错。
2. 每轮把 `{kind: "tool", name, args, summary}` 通过 `on_step` 回调抛出；`api/chat.py::/stream`
   改为**后台线程跑 agent + 队列转发 SSE**，实现真正的步骤级流式（`event: step`）。
3. `ChatView.vue`：助手气泡里渲染步骤条（正在查素材库… / 查到 292 条）。

### P1
4. `db.py` 启动时建**只读分析视图**（幂等 `DROP VIEW IF EXISTS` + `CREATE VIEW`）：
   `v_videos` / `v_drafts` / `v_feedback` / `v_persona_tags` / `v_topics` / `v_ideas` / `v_metrics` / `v_platform_posts`。
   **明确排除** `app_kv`（含明文模型 Key）、`ai_prompts`（提示词正文）、`chat_*`、`schema_migrations` 等敏感/内部表。
5. `sql_query(sql)` 工具：
   - 只允许 `SELECT` / `WITH…SELECT` 单条语句（拒绝 `;` 多语句与全部写/管理关键字）；
   - **表引用必须全部来自允许的视图白名单**（正则抽取 FROM/JOIN 标识符后校验）；
   - 只读连接 `file:…?mode=ro` + `PRAGMA query_only=1`；自动补 `LIMIT`（≤200）；超时中断；单元格截断；
   - 返回 `{columns, rows, row_count, truncated}`（延续 R-146：**必须让模型知道总数/是否被截断**）。
6. 系统消息注入**视图 schema 卡片**（视图名 + 列名 + 中文说明），否则模型写不出对的 SQL。

### P2
7. 新增 `agent_actions` 表（审计）：`action / payload / preview / status(pending|confirmed|cancelled|done|failed) / result / error / task_id / conversation_id / message_id / created_at / decided_at`。
8. 写工具改为**只提议不执行**：`_dispatch` 对 `generate_draft` / `rework_draft` / `set_draft_status`
   创建 `pending` 行并返回 `{status:"pending_confirmation", action_id, preview}`；系统规则要求模型
   明确告诉作者「请点击确认后才会执行」，不得声称已完成。
9. 新接口：`POST /api/chat/actions/{id}/confirm`、`POST /api/chat/actions/{id}/cancel`、
   `GET /api/chat/actions?conversation_id=`；确认后：`generate_draft`/`rework_draft` 入队后台任务
   （复用已有任务体，完成走既有通知），`set_draft_status` 立即执行（软删）。
10. `ChatView.vue`：把待确认操作渲染成卡片（动作 + 预览 + 确认/取消），确认后刷新状态。

## 不包含
- **不做 P3**（沙箱跑代码/shell）：风险过高，需独立容器 + 只读数据副本 + 禁网，单独立项再评估；
- 不做向量检索/RAG；
- 不给模型任何原始表写权限，也不放开 `app_kv`/`ai_prompts` 的读权限；
- 不改 R-139/R-143 的模型选择与降级策略。

## 验收结果（2026-09-12 真实调用）
- **P0+P1**：一次提问「先看素材库总数，再看草稿各状态，最后汇总」→ 4 个 `event: step`，
  模型**自己选择 `sql_query` 并写对 SQL**（2 次查询），答案与库完全一致：
  素材 292 条；草稿 22 篇 = draft 8 + used 1 + archived 4 + deleted 9。
- **P2**：「把草稿 22 标记为不采用」→ 只产出待确认提案（库中仍为 `draft`），点确认后变 `archived`，
  `agent_actions` 留下审计（action/status/result/created_at/decided_at）；测试后已还原为 draft。
- SQL 越权 10 例全部拒绝（含 `app_kv`、多语句、写操作、注释绕过、子查询偷查原表）。
- 新增 27 例测试；总 310 例；verify 全绿（29 张表 / 127 路由一致）。

## 验收标准
1. 问一个需要多步的问题（如"抖音里互动率最低的 3 条是哪些，把它们的转写稿要点给我"）能连续调用多个工具并给出答案；
   步骤在 SSE 里实时可见（有测试断言 `event: step`）；
2. 回合/预算/超时超限时**返回答案而非报错**（有测试）；
3. `sql_query` 只能查视图：`SELECT * FROM app_kv`、`DROP TABLE`、多语句、跨表 JOIN 原表等**全部被拒绝**并返回可读原因（有测试）；
4. 写操作（生成/回炉/改状态）**不会直接执行**，只产出 `pending` 动作；确认后才执行、取消后不动数据（有测试）；
5. `docs/DATABASE.md` 29 张表 + `docs/API.md` 127 路由同步（verify 会校验）；
6. `scripts/verify.sh` 全绿；真实对话冒烟（多步 + SQL + 提案确认三条链路）。
