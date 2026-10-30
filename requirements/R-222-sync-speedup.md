# R-222 同步提速：账号内并行 + 批量写库 + 消除 N+1

> 📌 2026-10-10：作者提出「后台请求有点慢，最慢的是同步数据」。12 个账号同步前 15 条需要 20 分钟以上，要求不走 Redis/MQ、不砍 B站 150 条历史指标补全，NAS 为 N150 4 核 12G。
> 方案：纯后端内部优化，最大化 IO 并行、批量写库、消除 N+1，保持现有 `sync_pool` 队列与 SQLite WAL。

- **日期**: 2026-10-10
- **状态**: 进行中
- **关联**: R-163（同步队列并发）、R-151（TikHub 限速与重试）、R-085/R-086（daily top15 带媒体）、R-109（对标同步）、R-219（同步进度可见性）

## 原文（作者原话，未改动）
> 页面不卡，不过我觉得后台请求有点慢，最慢的其实是同步数据

## 确认的问题与约束
1. 当前 12 个账号同步前 15 条需要 **20 分钟以上**。
2. 只同步每个平台前 15 条。
3. **不引入 MQ/Redis**：用项目自带的队列/线程池消费即可。
4. **不能减少 B站 150 条历史指标补全**：`_backfill_bili_stats()` 的 150 条上限保持不变。
5. NAS 资源：4 核 N150 CPU、12G 内存 → CPU 密集型（ffmpeg）不能狂并行，但 IO 型（TikHub 请求）可以大胆并发。

## 方案
### 1. 账号内请求并行化（最大收益）
- `services/platform_sync.py::sync_account()`：15 条作品 `_ensure_post()` 改走线程池并发。
- `services/platform_sync.py::_collect_comments()`：10 条作品的评论抓取并行。
- `services/platform_sync.py::_backfill_bili_stats()`：150 条 B站指标补全并行（受全局令牌桶 10 req/s 限制，但串行 → 并行收益巨大）。
- 单条作品「stats + comments」并发执行。
- `services/media_ensure.py`：每条素材的「评论同步 + 视频源解析 + 下载」拆分并行。

### 2. 批量写库，消除逐行 commit
- `services/platform_sync.py`：`_ensure_post()`、`_write_stat()`、`_upsert_comments()`、`_upsert_profile_snapshot()` 不再每行 `commit`；改为阶段末统一 commit 或每 10–20 条批量 commit。
- 批量 `INSERT ... ON CONFLICT` 替代逐条 upsert。
- `services/platform/budget.py`：`_charge()` 从每次请求都读写 `app_kv` 改成批量扣减（内存累计，阶段末一次性写）。

### 3. 消除 N+1
- `services/platform_sync.py::sync_account()` 开头一次性把该账号已有 `PlatformPost` 加载成 `(platform, platform_post_id) → post` 字典。
- `_upsert_comments()` 开头一次性加载该 post 已有评论成 `(text) → comment` 字典。
- `pool_ideas_from_comments()` 一次性加载当天已有 `TopicIdea` 字典。

### 4. 进度更新防抖
- `services/platform_sync.py::_job_progress()`：由每次完成一条都写库，改为每 2s 或每完成 10% 才写一次；最终完成强制写一次。

### 5. TikHub 连接复用与令牌桶批量
- `services/platform/tikhub.py`：线程局部复用 `httpx.Client`；令牌桶支持批量 `acquire(n)`，让并行请求能一次性拿足令牌。

### 6. 并发参数对齐
- `services/platform_sync.py` / `config.py`：当前账号级并发硬编码 3，改为读取配置；区分博主级/账号级/作品级/媒体级并发参数。
- 媒体并发保持 2（N150 扛不住更多 ffmpeg），下载线程可提到 4。

### 7. 封面下载解耦
- `services/platform_assets.py`：同步阶段只记 `cover_url`，封面下载与图片处理不阻塞作品入库。

## 明确不做
- 不引入 Redis/RQ/MQ 等中间件。
- 不减少 B站 150 条历史指标补全数量。
- 不迁移 SQLite → PostgreSQL。
- 不动前端代码。

## 验收
- [ ] 12 个账号 daily 前 15 条同步耗时从 20+ min 降到 10 min 以内，目标 6–8 min。
- [ ] `scripts/verify.sh` 全绿（ruff + mypy + pytest + 前端 build + 文档一致性）。
- [ ] 同步接口冒烟通过（mock 或 real 均可）。
- [ ] 服务保持运行（8000/3000）。
- [ ] 文档同步更新：ARCHITECTURE、CHANGELOG、API.md（如接口有变）、DATABASE.md（如表/索引有变）。
