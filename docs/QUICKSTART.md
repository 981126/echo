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
  - 抖音创作者 Cookie 加密密钥：`ECHO_DOUYIN_COOKIE_KEY`（R-237；不是 Cookie 本身，可用 `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"` 生成。Cookie 由「视频复盘 → 抖音数据设置」加密保存）
    - 获取 Cookie：浏览器登录 `https://creator.douyin.com` → F12 Network → 任一 creator 请求 → 复制完整 Cookie 请求头（必须含 `sessionid`/`sid_tt`）→ 粘贴到页面保存并验证。Cookie 过期后重新复制保存即可。

## 2. 目录与数据
- 代码：本仓库；**运行时数据不在仓库 `data/`**，由 `.env` 决定（本项目当前 `ECHO_DATA_DIR=/Users/yeah/document/echo_resource`）
- 数据库：PostgreSQL，连接串 `.env` 的 `ECHO_DATABASE_URL`（无默认、缺失启动报错；驱动写法 `postgresql+psycopg://…`）
- 子目录：`videos/`（素材文件）、`covers/`（封面原图 + `thumbs/` 缩略图缓存，R-179：`/covers/x.jpg?w=400` 按需生成）、`uploads/`、`inbox/`（拖入自动入库）

## 3. 首次启动（笔记本）
```bash
# 后端
cd backend
.venv/bin/pip install -r requirements.txt   # 首次
.venv/bin/python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
# 首次启动自动：Alembic 建表/视图/默认提示词、注册定时任务、启动 inbox 监听

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
- 库结构演进（R-236 起）：启动时执行 Alembic `upgrade head`；结构变更必须新增 revision，不在运行时临时补列。
- **并发同步（R-163）**：TikHub 全局限速 `ECHO_TIKHUB_RATE_LIMIT`（默认 10 req/s）；消费者数
  `ECHO_SYNC_CONCURRENCY`（博主级，默认 4）/ `ECHO_SYNC_MEDIA_CONCURRENCY`（素材级，默认 2）。改后重启生效。
- 定时任务在进程内（APScheduler）；改时间在 `.env`（如 `ECHO_PLATFORM_SYNC_TIMES=06:00,17:00`，主博主+对标统一每日两轮，R-109）
- 接口/表结构文档为人工维护；`scripts/check_doc_consistency.py` 会校验表数量/路由与代码一致（verify.sh 已接入）
- **测试**：pytest 固定连 `echo_test` 库（conftest 有库名安全闸门，指向其它库直接拒绝启动）；创建空 `echo_test` 后会由 Alembic 自动建结构，逐用例只清业务数据。

## 8. NAS 部署（Docker Compose）

### 一键部署（R-234，推荐）

```bash
cd /vol1/1000/docker/echo        # 你的仓库目录（以 fnOS 文件管理器实际路径为准）
cp .env.example .env             # ⚠ 不要直接拷笔记本的 .env（路径是 macOS 的）
vi .env                          # 至少改下面几项
#   ECHO_HOST_DATA_DIR=/vol1/1000/docker/echo/data   # 宿主机数据目录（绝对路径）
#   ECHO_ACCESS_TOKEN=<强口令>
#   ECHO_WEB_BASE_URL=http://192.168.50.214:8000
#   其余 DeepSeek / TikHub / ASR key 照抄
sudo bash scripts/deploy.sh
```

脚本依次做：**预检 `.env`/Docker → `git fetch` + 快进 `origin/main` → `docker compose build`（前端多阶段 + 后端）→ `up -d` → 健康检查 → 结构自检**。日志在 `data/logs/deploy-*.log`（保留最近 30 份）。

常用参数：

```bash
sudo bash scripts/deploy.sh --branch main      # 指定分支
sudo bash scripts/deploy.sh --no-pull          # 不拉代码，用当前工作区重建/重启
sudo bash scripts/deploy.sh --force            # 代码没变也强制重建
sudo bash scripts/deploy.sh --dry-run          # 只检查、打印将执行的命令
sudo bash scripts/deploy.sh --help
```

失败时非零退出并打印容器日志；上一版镜像保留为 `echo:previous`，可人工 `docker tag echo:previous echo:local && docker compose up -d --no-build` 回退（**数据库迁移不会自动回滚**）。

手动等价命令（首次或脚本不可用时）：

```bash
docker compose build
docker compose up -d
docker compose logs -f echo     # 看「结构自检通过」与定时任务注册
```

- 数据卷是 `${ECHO_HOST_DATA_DIR:-./data}:/app/data`（素材/封面/上传等运行时文件）；
  容器内 `ECHO_DATA_DIR` 已由 compose 固定为 `/app/data`，不要在这项写宿主机路径；宿主机目录用 `ECHO_HOST_DATA_DIR`；
  数据库不在卷里——容器靠 `.env` 的 `ECHO_DATABASE_URL` 连接（本项目的 PG 就跑在 NAS 本机）。
- 健康检查用 python urllib（slim 镜像没有 curl）。
- `.dockerignore` 排除了 `node_modules/.venv/data`：**必须**，否则宿主机的 `node_modules`
  会覆盖镜像内的 Linux 版前端依赖，`npm run build` 直接失败。
- **单进程**：不要加 `uvicorn --workers`（APScheduler 会重复触发）。

### 一键打包 / 一键部署（R-145 / R-234）

```bash
# ── 本地：打包（只含被 git 跟踪的文件，天然排除 .env / data / node_modules）
git commit -am "feat(R-xxx): ..." && git tag v0.3.0
bash scripts/release.sh            # → dist_release/echo_v0.3.0_<时间戳>.tar.gz
                                   #   工作区有未提交改动会直接拒绝打包（防止发半成品）

# ── NAS：部署（拉码 → 构建 → 启动 → 健康检查 → 结构自检）
#   包部署：tar -xzf echo_v0.3.0_*.tar.gz --strip-components=1 -C /volume1/echo && cd /volume1/echo
#   git 部署：cd /volume1/echo
sudo bash scripts/deploy.sh        # 推荐；update.sh 已保留为兼容入口
# 解包部署（非 git 仓库）：sudo bash scripts/deploy.sh --no-pull
```

**启动时迁移**（R-236 起）：后端执行 Alembic `upgrade head`。空库依次应用全部 revision；无版本表的完整旧库经一致性校验后 baseline；结构不匹配会拒绝启动，不会静默修补。

### 增量上线 runbook（新表 / 新字段 / 改结构）

```bash
# ── 本地：模型与 migration 一起修改
cd backend
.venv/bin/alembic revision -m "describe schema change"
# 编辑新生成的 versions/*.py；新表同时修改 app/models/__init__.py
# 视图或结构相关数据变更也新增 revision；已合入的 revision 不再修改
# 同步 docs/DATABASE.md 并跑空库/旧库迁移测试
cd ..
PATH=backend/.venv/bin:$PATH PYTHON=backend/.venv/bin/python scripts/verify.sh
git add <具体文件> && git commit -m "feat(R-xxx): ..." && git push

# ── NAS
cd /volume1/echo
sudo bash scripts/deploy.sh
curl -fsS localhost:8000/health
```

> 维护约定：deploy.sh 的「结构自检」会比对模型声明与实际库表；Alembic 版本表不属于业务表。回滚代码不会自动回滚数据库。
