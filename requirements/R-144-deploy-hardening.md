# R-144 上线部署加固：镜像带脚本 + 启动结构自检 + schema 兼容性测试 + 迁移记录表

- **日期**: 2026-09-12
- **状态**: ✅ 已完成（2026-09-12，M133）
- **关联**: R-133（备份真实性）、R-136（文档一致性门禁）、`Dockerfile`、`docker-compose.yml`、`app/db.py`、`app/main.py`、`scripts/backup.sh`

## 原文（作者原话，未改动）
> ABCD都需要

（上下文：作者准备上线，AI 就「后续增量上线怎么保证新表/新字段不出事」提出 4 项加固，作者确认全做：
A 把 `scripts/` 打进镜像；B 启动时做「模型声明的列 vs 实际库的列」自检并报警；
C 用生产库结构快照做 schema 兼容性测试；D 加轻量 `schema_migrations` 记录表。）

## 背景（已查证的问题）
1. **A｜每日备份在容器里是断的**：`Dockerfile` 与 `docker-compose.yml` 都没有 `scripts/`（grep 计数为 0），
   而 `scheduler._backup_job` 会去找 `/app/scripts/backup.sh` → 每晚报「备份脚本不存在」，**备份永不执行**。
   没有备份就没有回滚预案，而增量上线的安全网正是它。
2. **B｜漏写迁移只能在运行时爆炸**：`create_all` 只建缺失的表、不给已有表补列（所以有 24 个手写 `_migrate_*`）。
   一旦「往模型加字段但忘了写迁移」，线上老库会在第一次访问该列时报 `no such column`，且**启动时毫无提示**。
3. **C｜测试抓不到漏写迁移**：pytest 全部用**全新库**（`Base.metadata.create_all` 直接建出最新结构），
   所以漏写迁移在本地 100% 绿，上线才炸。
4. **D｜不知道库升到哪一版**：没有迁移记录，排障只能人工 `PRAGMA table_info` 比对。

## 范围
1. **A**：`Dockerfile` 增加 `COPY scripts/ ./scripts/`；`scripts/backup.sh` 除读 `.env` 外也认**环境变量**
   `ECHO_DB_PATH`/`ECHO_DATA_DIR`（容器里没有 `.env` 文件，只有注入的环境变量）。
2. **B**：新增 `app/core/schema_guard.py`（接受显式 `bind`，便于测试）：
   `missing_schema(bind)` 返回「缺失的表 / 缺失的列」；启动时（`init_db` 之后）跑一次，
   有问题 → 日志 error + 站内通知（含缺哪些列、怎么修），并落 `app_kv` 供查看；**自检本身绝不能阻塞启动**。
3. **C**：把当前生产库的**结构快照**（只含 schema、不含数据）存为 `backend/tests/fixtures/schema_baseline.sql`；
   新增测试：用该快照建库 → 跑 `init_db()` → 断言「模型声明的每一张表、每一列都存在」。
   以后加字段若漏写迁移，这个测试直接红。
4. **D**：新增 `schema_migrations` 表（`name` 唯一 / `applied_at` / `note`）+ `db.py` 的
   `record_migration(name)`、`migration_status()`；首次运行写入基线行 `baseline_pre_r144`；
   启动日志输出「库结构版本」（已应用迁移数 / 最新迁移名）；新迁移的写法写进文档模板。

## 不包含
- 不引入 Alembic（仍是轻量幂等迁移；本次只是把「能不能漏」这件事变成可检测）；
- 不改现有 24 个迁移函数的语义（只在末尾补记迁移名机制）；
- 不做自动回滚（回滚仍是「退代码 + 换回备份库」的人工流程，写进 QUICKSTART）。

## 实施补充（查证时发现的另外两个 A 类问题，一并修）
1. **镜像没有 `.dockerignore`**：构建上下文会把宿主机 `frontend/node_modules`（192M）带进去，
   而 `COPY frontend/ ./` 会**覆盖镜像内 `npm install` 装好的 Linux 版 esbuild/rollup** → 前端构建必失败。
   已新增 `.dockerignore`（排除 `node_modules/.venv/data/.git` 等）。
2. **健康检查依赖 `curl`**：`python:3.12-slim` 没有 curl → 容器永久 unhealthy。已改为 python urllib + `start_period`。

## 验收结果（2026-09-12）
1. 镜像/构建契约有测试断言（`COPY scripts/`、`.dockerignore`、健康检查不用 curl、`backup.sh` 认环境变量）✅
2. 启动自检在真实库副本上验证：故意 `DROP COLUMN` 后 `ok=False` + 日志 + 站内通知 + 落 `app_kv`，且不影响启动 ✅
3. 老库升级测试通过（基线快照 → `init_db()` → 零缺失表/列），并在**真实生产库副本**上演练通过 ✅
4. `schema_migrations` 幂等、`migration_status()` 可读（库结构版本=`baseline_pre_r144`）✅
5. `docs/DATABASE.md` 28 张 +  增量上线 runbook ✅
6. `scripts/verify.sh` 全绿（263 例）✅
7. ⚠ 未做：本机 Docker daemon 未运行，镜像构建未在本地实测（已写进 CHANGELOG 待 NAS 首次构建确认）

## 验收标准
1. 镜像内含 `scripts/backup.sh`；容器里 `bash scripts/backup.sh` 可用（有测试断言 Dockerfile 契约）；
2. 启动自检能检出「模型有列、库里没有」，写日志 + 站内通知，且不阻塞启动（有测试）；
3. schema 兼容性测试：拿基线快照建库 → `init_db()` → 无缺失表/列（有测试）；
4. `schema_migrations` 记录迁移且幂等，`migration_status()` 可读（有测试）；
5. `docs/DATABASE.md` 表数同步为 28；
6. `scripts/verify.sh` 全绿；并用**真实生产库副本**演练一次「老库升级」。
