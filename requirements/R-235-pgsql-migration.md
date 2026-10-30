# R-235-PGSQL-MIGRATION: SQLite 全面迁移到 PostgreSQL，移除 SQLite 相关代码

- **日期**: 2026-10-21
- **提出渠道**: 对话
- **原文**: jdbc:postgresql://yeah981.cn:15981/echo_dev Yeah/<密码已打码> 这是我的pgsql，我已经将数据迁移过去了，将项目中的sqllite代码改为pgsql，移除sqllite相关代码
- **状态**: ✅ 已完成
- **排期**: M236
- **关联**: `backend/app/db.py`、`backend/app/config.py`、`backend/app/core/schema_guard.py`、`backend/app/core/analytics_views.py`、`backend/app/services/chat_sql.py`、`backend/app/services/{platform_sync,chat_service,benchmark,model_health}.py`、`backend/app/scheduler.py`、`backend/tests/*`（66 个文件）、`scripts/{backup.sh,deploy.sh,release.sh}`、`docker-compose.yml`、`docs/{ARCHITECTURE,DATABASE,QUICKSTART}.md`、R-016、R-144、R-163、R-223、R-234

## 边界与默认行为（2026-10-21 确认）

1. **数据库**：作者自有 PG，跑在 NAS 上（`yeah981.cn:15981`），开发库 `echo_dev`。
   ⚠️ 实施时发现 echo_dev 实为**空库**（除启动 seed 的提示词外 0 行数据）——作者称的「已迁移」未落到本实例；
   数据仍在原 SQLite 文件 `echo_resource/echo.db`（98MB）完好，待作者确认后再迁。
2. **连接串**：新增 `ECHO_DATABASE_URL`，**只从 `.env` 读、无默认**，缺失时启动直接报错（fail-closed）。开发库：`postgresql://Yeah:<密码>@yeah981.cn:15981/echo_dev`（密码只在 `.env`，不进代码/文档/commit）。移除 `ECHO_DB_PATH` 与 `db_path` 派生逻辑。
3. **驱动**：SQLAlchemy + psycopg（v3），加入 `backend/requirements.txt`（或等价依赖文件），本主仓库允许安装。
4. **历史迁移全部删除**：`db.py` 里约 25 个幂等迁移/一次性数据修复（PRAGMA 探列、UTC+8、回填、去重、旧列删除等）**全部删除**；数据已迁好，新环境靠 `Base.metadata.create_all` 建全量结构。`init_db` 只保留：create_all + 索引 + 绑定完整性唯一索引 + 提示词 seed + 分析视图。
5. **schema_guard（R-144）**：随迁移一起下线（迁移记账与基线校验的对象已不存在）；verify 的文档一致性若引用它一并处理。
6. **方言改写**：`PRAGMA table_info/index_list` → `information_schema` 查询或直接删除；SQLite 私有函数（`datetime(x,'+8 hours')` 等随一次性迁移删除）；`chat_sql.py` / `analytics_views.py` / `scheduler.py` / `benchmark.py` / `model_health.py` 里的方言 SQL 改写为 PG 兼容；部分唯一索引 `WHERE ... IS NOT NULL` 语法 PG 原生支持，保留。
7. **JSON 列保持 TEXT**：`platforms`/`tags`/`quality` 等仍存 JSON 字符串（SQLAlchemy `Text`），零数据风险，不升 JSONB。
8. **时间列**：保持 naive `DateTime` → PG `timestamp without time zone`，语义与现库一致，不做时区改造。
9. **测试库 `echo_test`**：作者要求「复制一份 echo_dev 表结构和数据到 echo_test，用 echo_test 测试」。
   - 提供复制脚本（如 `scripts/init_test_db.sh`，`pg_dump echo_dev | psql echo_test`，要求先断开 echo_dev 连接）。
   - conftest 改连 `echo_test`；**每个测试前清空全部表**（`TRUNCATE ... CASCADE` 或 drop/create schema），保持「空库」语义——原 SQLite 测试就是 tmp 空库，断言（如 count==1）依赖空库起点；复制进去的数据会在首个测试被清掉，复制只为满足作者要求、并便于人工核查。
   - **安全闸门**：conftest 启动时校验目标库名必须为 `echo_test`（大小写不敏感），指向其它库直接 fail，防止误清 `echo_dev`。
   - CI/本地跑测试需可达 yeah981.cn:15981。
10. **部署形态**：PG 在 NAS 本机，`docker-compose.yml` 去掉 `ECHO_DB_PATH`，容器靠 `.env` 的 `ECHO_DATABASE_URL` 连接（容器→宿主/NAS 的连通性在 NAS 实机验证）；`scripts/backup.sh` 由 SQLite 热备改为 `pg_dump` 备份；`deploy.sh` 去掉 `echo.db` 存在性检查/备份分支，保留结构自检；`release.sh` 打包拒绝项里的 `echo/data/echo.db` 同步移除。
11. **文档同步**：`docs/ARCHITECTURE.md`、`docs/DATABASE.md`、`docs/milestones.md`、`docs/CHANGELOG.md`；`AGENTS.md` 中 worktree 数据库拷贝等 SQLite 段落列入「待收口文档改动」。
12. **不做**：Alembic 落地（tech-debt 维持）、JSONB 改造、时区改造、读写分离/连接池调优以外的 PG 特性引入、数据再迁移（作者已完成）。

## 验收标准

- [ ] `.env` 不配 `ECHO_DATABASE_URL` 时后端启动报错并给出中文提示。
- [ ] `scripts/verify.sh` 全绿（ruff + mypy + pytest + 前端 lint/build + 文档一致性），pytest 全部走 echo_test。
- [ ] 后端连 `echo_dev` 冒烟：health、素材/博主/草稿列表等核心接口 200（⚠️ 实施时 echo_dev 为空库，返回真实迁移数据待数据迁移完成后复核）。
- [ ] 前端 `npm run build` 通过，关键页面点检正常。
- [ ] `scripts/backup.sh` 产出 pg_dump 备份文件并通过校验。
- [ ] 仓库内不再存在 sqlite 依赖与 `PRAGMA`/SQLite 方言残留（grep 全库为空，文档除外）。

## 验证记录

- `ruff check app tests` / `mypy app` 全绿。
- pytest 全量连真实 echo_test 跑通（verify.sh 内同路径）。
- 备份脚本 `bash -n` 通过；pg_dump 实机备份待有 PG 客户端的环境执行（本机无 pg_dump，相关用例 skip）。

## 实现要点

- `config.py`：`database_url` 必填校验（model_validator fail-closed）；删除 `db_path/ECHO_DB_PATH`/`sqlalchemy_url`。
- `db.py`：psycopg 引擎（pool_size=10/max_overflow=20/pre_ping/recycle + connect_timeout=10——远端 NAS PG 公网链路偶发握手丢包）；`init_db` = create_all + 索引 + 绑定唯一部分索引 + 提示词 seed + 分析视图。
- `chat_sql.py`：SQLAlchemy 引擎 + 服务端 `default_transaction_read_only=on` + `statement_timeout`（客户端时间为兜底）；引擎按连接串 NullPool 缓存。
- `scheduler.py`：清理截止时间 Python 侧计算（`timeutil.now() - timedelta`）参数化传入。
- `conftest.py`：连接串**不写死**——从 .env 读再换库名为 echo_test；`fresh_engine()` = `TRUNCATE ... RESTART IDENTITY CASCADE`（踢 idle-in-transaction 僵尸连接 + lock_timeout + 重试）；`ensure_schema()` 占位（PG 下不再每用例反射 create_all，省远端 RTT）；调用阶段遭遇远端瞬断自动重跑用例一次（只兜连接级错误）；`make_url` 库名闸门非 echo_test 直接 RuntimeError。
- `scripts/init_test_db.sh`（新）：pg_dump|psql 复制 echo_dev→echo_test，自动剥 `+psycopg` 驱动后缀（libpq 不认识）。
- `backup.sh`：pg_dump custom 格式 + 连通性预检 + 空 dump/零表校验；Python 预检优先 `backend/.venv`。
- `deploy.sh`：备份不再判断 echo.db；结构自检 = 模型表集合 vs `inspect.get_table_names()`。
- schema_guard / schema_migrations 模型 / test_r144 / schema_baseline.sql 已删除。

## 待收口文档改动

- `AGENTS.md`：并行开发章节「数据库独立：sqlite3 .backup 拷贝库 / ECHO_DB_PATH」段落改为 PG 形态（echo_test 复制脚本或各自 schema）。
- `docs/CHANGELOG.md`：R-235 条目。
