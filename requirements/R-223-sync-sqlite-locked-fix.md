# R-223 同步所有博主 database is locked 修复

> 📌 2026-10-10：作者反馈「同步所有博主」报 `(sqlite3.OperationalError) database is locked`，错误堆栈指向 `UPDATE creator_accounts SET sync_status=...` 与内层 `UPDATE app_kv ... tikhub_budget_used:2026-10-09`。

- **日期**: 2026-10-10
- **状态**: ✅ 已完成
- **关联**: R-163（同步队列并发）、R-151（TikHub 限速与重试）、R-085/R-086（daily top15 带媒体）、R-109（对标同步）、R-222（同步提速）

## 原文（作者原话，未改动）
> 同步所有博主抱错(sqlite3.OperationalError) database is locked [SQL: UPDATE creator_accounts SET sync_status=?, sync_message=? WHERE creator_accounts.id = ?] [parameters: ('failed', '(sqlite3.OperationalError) database is locked\n[SQL: UPDATE app_kv SET value=? WHERE app_kv."key" = ?]\n[parameters: (\'7\', \'tikhub_budget_used:2026-10-09\')]\n(Background on this error at: https://sqlalch', 3)] (Background on this error at: https://sqlalche.me/e/20/e3q8)

## 根因
`_ensure_post()` 与 `_upsert_profile_snapshot()` 在 SQLite 写事务内执行同步网络 I/O（下载封面图/头像，timeout 8s），导致写锁被长时间占用。并发同步多个博主/账号时，一个线程持锁下载图片，其他线程的 `_charge()` 要写 `app_kv` 表更新 TikHub 预算计数，等待写锁超过 `busy_timeout=30s`，抛出 `database is locked`。

## 方案
### 1. 封面下载移出数据库事务
- `services/platform_sync.py::_ensure_post()`：先提交作品与统计信息，释放写锁；再在事务外调用 `_cover_path_for()` 下载封面、生成缩略图；最后用独立短事务把 `cover_path` 写回 `PlatformPost`。

### 2. 头像下载移出数据库事务
- `services/platform_sync.py::_upsert_profile_snapshot()`：先提交 profile 快照与昵称变更，释放写锁；再在事务外调用 `_ensure_account_avatar()` 下载头像；最后用独立短事务把 `avatar_path` 写回 `CreatorAccount`。

### 3. 清理未使用的 `db` 参数
- `services/platform_assets.py::_cover_path_for()` 去掉未使用的 `db: Session` 参数。
- `services/platform_assets.py::_ensure_account_avatar()` 改为纯下载函数，返回 `str | None`，不再接收 `db` 也不再内部 `commit`。

### 4. 修复并发抓取中的 ORM 对象跨线程访问（R-222 伴生问题）
- `services/platform_sync.py::_fetch_comments_parallel()` 与 `_fetch_post_stats_parallel()` 的 inner thread 原本直接读取主 Session 的 `PlatformPost` / `CreatorAccount` ORM 对象属性，跨线程访问触发 `ObjectDeletedError`（flaky，与 pytest 输出捕获/时序相关）。
- 修复方式：主线程先把需要的 primitive 字段（`platform`、`platform_post_id`、`raw`）抽出来传给 inner thread；inner thread 不再触碰主 Session 的 ORM 对象；返回后再按 `platform_post_id` 映射回原始对象。

## 明确不做
- 不改 SQLite WAL / busy_timeout / 连接池配置（当前已开 WAL、busy_timeout=30s，问题不是等待时间不够）。
- 不改 TikHub 限速/重试逻辑。
- 不改同步并发度（仍由 `ECHO_SYNC_CONCURRENCY` 控制）。
- 不迁移数据库。

## 验收
- [x] `scripts/verify.sh` 全绿（ruff + mypy + pytest + 前端 lint/tsc/build + 文档一致性 31 表/146 路由）。
- [x] 后端重启后 `/health` 正常，结构自检通过。
- [x] 真实触发「同步所有博主」：日志中无 `database is locked`；因本次任务启动前服务重启遗留的 4 个博主被标记「任务中断」，其余 8 个博主同步成功。
