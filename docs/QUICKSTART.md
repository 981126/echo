# QUICKSTART — 快速上手 / 新设备部署

> 面向部署与运维：环境准备、首次启动、常见运维、Docker/NAS 部署。架构总览见 `ARCHITECTURE.md`，新需求流程见 `WORKFLOW.md`，agent 编码纪律见 `AGENTS.md`。

## 1. 你需要准备
- Python 3.12+（开发机已建 `backend/.venv`）
- Node 18+（前端）
- 真实服务密钥（放根目录 `.env`，**不要提交**）：
  - TikHub：`ECHO_TIKHUB_API_KEY`（平台数据/热搜）
  - DeepSeek / Kimi：`ECHO_DEEPSEEK_API_KEY` / `ECHO_KIMI_API_KEY`
  - 阿里云：ASR（AccessKey + AppKey）与 OSS（bucket/region）
  - 硅基流动 / 腾讯云（可选，二选一或都不用）：`ECHO_SILICONFLOW_API_KEY` / 腾讯云 `ECHO_TENCENT_ASR_SECRET_ID/SECRET_KEY`
  - QQ 邮箱 SMTP：`ECHO_SMTP_USER/AUTH_CODE/MAIL_TO`（可选，推送用）
  - 访问令牌：`ECHO_ACCESS_TOKEN`（登录用）

## 2. 目录与数据
- 代码：本仓库；**运行时数据不在仓库 `data/`**，由 `.env` 决定（本项目当前 `ECHO_DATA_DIR=/Users/yeah/document/echo_resource`，`ECHO_DB_PATH=…/echo.db`）
- 子目录：`videos/`（素材文件）、`covers/`（封面原图 + `thumbs/` 缩略图缓存，R-179：`/covers/x.jpg?w=400` 按需生成）、`uploads/`、`inbox/`（拖入自动入库）
- 备份：`scripts/backup.sh`（或每日 02:30 自动）；数据库建议用官方热备

## 3. 首次启动（笔记本）
```bash
# 后端
cd backend
.venv/bin/pip install -r requirements.txt   # 首次
.venv/bin/python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
# 首次启动自动：建表/迁移/seed 默认提示词/注册定时任务/启动 inbox 监听

# 前端（frontend_v2，当前默认前端）
cd frontend_v2
npm install          # 首次
npm run dev          # http://localhost:3000
```
登录：打开页面输入 `ECHO_ACCESS_TOKEN`。
也可只跑后端（已 `npm run build` 时 FastAPI 托管：http://localhost:8000/）。

## 4. 首次使用流程
1. **博主管理**：新建主博主 → 为它配置抖音/B站/小红书账号（填主页分享链接，系统自动解析平台 ID）
2. **同步数据**：点「同步前 15 条」或「全量同步」，页面显示进度条；完成后云端作品进入素材库/看板
3. **素材**：上传视频 → 编辑页「语音转文字」（服务商见「AI 设置 → 模型设置」，默认 .env 的 `ECHO_ASR_MODE`）→ 确认标签
4. **选题/生成**：主页「抓取更新」→ 挑灵感 → 工作台生成/改写 → 保存/发布
5. **选题/对标**：主页热点灵感 + 博主对标页分析/洗稿（数据看板与 ABCD 复盘已下线）

## 5. 模式开关（务必理解）
`.env` 三处模式字段只接受白名单，**行尾注释必须另起一行**，否则启动报错（R-068）：
```dotenv
ECHO_TIKHUB_MODE=real      # ← 正确写法
ECHO_HOT_SOURCE_MODE=real
ECHO_ASR_MODE=aliyun
# ECHO_TIKHUB_MODE=real# 注释 ← 错误：整串被当值，启动即报错
```

## 6. 质量门禁与测试
```bash
PATH=backend/.venv/bin:$PATH PYTHON=backend/.venv/bin/python scripts/verify.sh
# ruff + mypy + pytest(183) + 前端 lint/build + 文档完整性与一致性
```

## 7. 常见运维
- 改 `.env` 后重启后端（配置启动时读取）
- 数据迁移自动（启动时幂等补列）**并且启动时会自检**：把「模型声明的列」与实际库对一遍，
  缺列 → 日志 error + 站内通知「库结构自检发现问题」（多半是加了字段忘了写迁移）
- 库结构版本：`schema_migrations` 表记录已应用的迁移（`baseline_pre_r144` 为 R-144 前的基线）；
  启动日志会打印「结构自检通过：N 张表；库结构版本=…」
- 重大变更先 `scripts/backup.sh`
- **并发同步（R-163）**：TikHub 全局限速 `ECHO_TIKHUB_RATE_LIMIT`（默认 10 req/s）；消费者数
  `ECHO_SYNC_CONCURRENCY`（博主级，默认 4）/ `ECHO_SYNC_MEDIA_CONCURRENCY`（素材级，默认 2）。改后重启生效。
- SQLite 已开 **WAL**（`echo.db` 旁会出现 `-wal`/`-shm`，属正常；备份用官方 backup API，自动含 WAL 内容；
  请勿只 `cp echo.db` 热拷）
- 定时任务在进程内（APScheduler）；改时间在 `.env`（如 `ECHO_PLATFORM_SYNC_TIMES=06:00,17:00`，主博主+对标统一每日两轮，R-109）
- 接口/表结构文档为人工维护；`scripts/check_doc_consistency.py` 会校验表数量/路由与代码一致（verify.sh 已接入）

## 8. NAS 部署（Docker Compose）

```bash
# 首次
cp .env.example .env        # ⚠ 不要直接拷笔记本的 .env（路径是 macOS 的）
# 生产 .env 必须改：
#   ECHO_DATA_DIR=/app/data
#   ECHO_DB_PATH=/app/data/echo.db
#   ECHO_ACCESS_TOKEN=<强口令>   ECHO_WEB_BASE_URL=http://<NAS地址>:8000
docker compose build && docker compose up -d
docker compose logs -f echo     # 看「结构自检通过」与定时任务注册
```

- 数据卷是 `./data:/app/data`（**唯一持久化位置**：库/素材/封面/上传/备份）；
  若 `.env` 仍写本机绝对路径，数据会落进容器可写层，重建即丢。
- 镜像内置 `scripts/`（每日 02:30 备份依赖它）；健康检查用 python urllib（slim 镜像没有 curl）。
- `.dockerignore` 排除了 `node_modules/.venv/data`：**必须**，否则宿主机的 `node_modules`
  会覆盖镜像内的 Linux 版前端依赖，`npm run build` 直接失败。
- **单进程**：不要加 `uvicorn --workers`（APScheduler 会重复触发、SQLite 单写会锁）。

### 一键打包 / 一键部署（R-145）

```bash
# ── 本地：打包（只含被 git 跟踪的文件，天然排除 .env / data / node_modules）
git commit -am "feat(R-xxx): ..." && git tag v0.3.0
bash scripts/release.sh            # → dist_release/echo_v0.3.0_<时间戳>.tar.gz
                                   #   工作区有未提交改动会直接拒绝打包（防止发半成品）

# ── NAS：部署（备份 → 拉码 → 构建 → 启动 → 健康检查 → 打印库结构版本）
#   包部署：tar -xzf echo_v0.3.0_*.tar.gz --strip-components=1 -C /volume1/echo && cd /volume1/echo
#   git 部署：cd /volume1/echo
bash scripts/update.sh             # 解包部署可加 SKIP_PULL=1；任一步失败即非零退出
```

**启动时会自动增量升级**（这就是「打包上去、启动就好」的原理）：

| 变更类型 | 谁来做 | 部署侧要做什么 |
|---|---|---|
| 新增**表** | `Base.metadata.create_all` 启动时自动建 | 什么都不用做 |
| 新增**字段** | 那一版代码里的 `_migrate_*`（在 `init_db()` 里注册） | 什么都不用做（但**发布侧必须写迁移**，见下） |
| 改了字段含义/删表 | 手写迁移 + 「先停用后清理」两步走 | 无（但别在一个版本里直接删） |

启动顺序（`app/main.py` lifespan）：**判断待应用变更 → 自动备份 → 升级 → 结构自检**。
即：只要检测到「模型声明的表/列 与 实际库不一致」，就会先自动备份到
`data/backups/pre_upgrade/<时间戳>.db`（SQLite 官方 backup API + `integrity_check`，保留最近 5 份），
**再**执行升级；备份失败只告警、不阻断启动（宁可先起来，也别让服务停着）。

### 增量上线 runbook（新表 / 新字段 / 改结构）

```bash
# ── 本地：改代码 + 写迁移（发布侧唯一必须的人工动作）
#   新增表   → 加模型 + 在 app/models/__init__.py import（否则 create_all 看不见它）
#   新增字段 → 在 app/db.py 加 _migrate_xxx（PRAGMA table_info 判存在 → ALTER TABLE ADD COLUMN），
#              并在 init_db() 里注册；干完调用 schema_guard.record_migration(engine, "<名字>")
#   改文档   → docs/DATABASE.md 表数/章节（verify 会校验）
bash scripts/verify.sh
# 用生产库副本演练（不要用全新库！全新库建的是最新结构，测不出漏写迁移）
cp <生产库> /tmp/upgrade_drill.db
ECHO_DB_PATH=/tmp/upgrade_drill.db python -c "from app.db import init_db; init_db()"
git commit -am "feat(R-xxx): ..." && git tag vX.Y.Z && git push --follow-tags

# ── NAS
cd /volume1/echo
bash scripts/backup.sh              # ① 先备份（回滚预案的前提）
git pull --ff-only                  # ② 或 bash scripts/update.sh（含 build + up + 健康检查）
docker compose build && docker compose up -d
curl -fsS localhost:8000/health     # ③ 验证
# 回滚：git checkout <上个 tag> → build → up -d → 用升级前的备份换回 echo.db
```

> 维护约定（见 `tests/test_r144_schema_guard.py`）：
> ① `fixtures/schema_baseline.sql` 是「从哪个版本升级」的起点快照，**不要随手刷新**；
> ② 老库升级测试会对「模型每一列都存在」做断言 —— 漏写迁移会直接红，这是有意的。
