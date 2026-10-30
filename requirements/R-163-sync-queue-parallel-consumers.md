# R-163 同步提速：任务进队列 + 消费者并行 + TikHub 全局限速（10 req/s）

- **日期**: 2026-09-28
- **状态**: ✅ 已完成（2026-09-28，M152）
- **关联**: `backend/app/services/platform/tikhub.py`、`backend/app/services/platform/budget.py`、
  `backend/app/services/sync_pool.py`（新增）、`backend/app/services/platform_sync.py`、
  `backend/app/services/media_ensure.py`、`backend/app/tasks.py`、`backend/app/db.py`、`backend/app/config.py`；
  R-070、R-085/R-086、R-093/R-094、R-109、R-151、R-162

## 原文（作者原话，未改动）
> 现在同步的速度太慢了，都是同步的操作，任务放到队列中，消费者应该并行，不过tikhup只支持10个请求/s

## 反问与确认结论（2026-09-28）
1. **限速口径**：TikHub 上限为「**全局合计 10 请求/秒**」，所有接口共享一个令牌桶；
   取代 R-151 的「按路由 1.2s/次」。为避免个别路由被服务端限流，保留**按路由 429 退避**作为兜底安全阀。
2. **并行范围**：**博主级 + 素材级都并行**——多个博主的同步任务并发消费，单个博主内多条素材的
   媒体补齐也并发消费。
3. **并发度**：可配置，`.env` 新增 `ECHO_SYNC_CONCURRENCY`（默认 4，博主级消费者数）；
   素材级独立小池 `ECHO_SYNC_MEDIA_CONCURRENCY`（默认 2），避免 CPU/ASR 冲击。
4. **SQLite**：允许开启 **WAL + busy_timeout**，降低并行写锁冲突。
5. **推进方式**：先登记需求 + 出详细方案，再按里程碑实施。

## 现状与根因
- 任务层已是并发（`tasks.py:start_task` 每任务一个 daemon 线程），但同步**内部串行**：
  - `run_all_top15_sync`（`platform_sync.py`）逐个博主串行；
  - `run_card_sync_queue`（`media_ensure.py`）逐条素材串行（评论→下载→转写）；
  - `_throttle_route`（`tikhub.py`）按路由 1.2s/次，同平台所有账号/帖子互相排队。

## 范围
- **后端**
  - `services/platform/tikhub.py`：全局令牌桶（`ECHO_TIKHUB_RATE_LIMIT` 默认 10 req/s、
    `ECHO_TIKHUB_RATE_BURST` 默认 10）+ 按路由 429 退避兜底；移除默认的「按路由 1.2s」串行。
  - `services/sync_pool.py`（新增）：进程内并发消费者基础设施（线程池、原子认领、结果收集）。
  - `services/platform_sync.py`：博主级并行（`run_all_top15_sync` / `run_daily_sync_all`），
    进度按「完成数/总数」聚合。
  - `services/media_ensure.py`：素材级并行（`run_card_sync_queue`），同合并作品去重加锁防竞态。
  - `services/platform/budget.py`：预算读写加进程内锁，保证并行下不超发。
  - `db.py`：连接时 `PRAGMA journal_mode=WAL; busy_timeout=30000; synchronous=NORMAL;`。
  - `config.py`：新增并发/限速配置项。
- **前端**：无需大改（已按 `status=running&limit=50` 轮询，天然支持多任务并行）。
- **文档**：`.env.example`、ARCHITECTURE、milestones、CHANGELOG 同步。

## 不包含
- 不改 LLM / 人工生成链路的任务调度。
- 不改同步深度与口径（仍为前15条 + 评论 + 缺视频下载/转写）。
- 不引入外部消息队列（Redis/Celery 等），仍为单进程内线程池（Docker 单进程约束）。

## 验收标准
- N 个博主「同步所有博主前15条」整体耗时明显下降（并发下趋近线性直到触限速上限）。
- TikHub 请求全局 ≤ 配置速率；日志中 429 重试显著减少或无。
- 每日预算计数准确、不超发；`BudgetExceeded` 能停止后续队列。
- 前端卡片/任务动画在并行下正常；重启后 pending 任务沿用既有「标记中断」语义。
- `scripts/verify.sh` 全绿 + 接口冒烟 + 前端点检；服务保持运行。

## 排期
M152（拆分：M152-A 限速器 → M152-B 消费者池 → M152-C 博主级并行 → M152-D 素材级并行 → M152-E WAL/预算/进度）
