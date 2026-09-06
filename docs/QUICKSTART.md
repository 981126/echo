# QUICKSTART — 快速上手 / 新设备部署

> 面向「把系统跑起来」的人。完整架构见 ARCHITECTURE.md，配置项见 backend/app/config.py。

## 1. 你需要准备
- Python 3.12+（开发机已建 `backend/.venv`）
- Node 18+（前端）
- 真实服务密钥（放根目录 `.env`，**不要提交**）：
  - TikHub：`ECHO_TIKHUB_API_KEY`（平台数据/热搜）
  - DeepSeek / Kimi：`ECHO_DEEPSEEK_API_KEY` / `ECHO_KIMI_API_KEY`
  - 阿里云：ASR（AccessKey + AppKey）与 OSS（bucket/region）
  - QQ 邮箱 SMTP：`ECHO_SMTP_USER/AUTH_CODE/MAIL_TO`（可选，推送用）
  - 访问令牌：`ECHO_ACCESS_TOKEN`（登录用）

## 2. 目录与数据
- 代码：本仓库；**运行时数据不在仓库 `data/`**，由 `.env` 决定（本项目当前 `ECHO_DATA_DIR=/Users/yeah/document/echo_resource`，`ECHO_DB_PATH=…/echo.db`）
- 子目录：`videos/`（素材文件）、`covers/`、`uploads/`、`inbox/`（拖入自动入库）
- 备份：`scripts/backup.sh`（或每日 02:30 自动）；数据库建议用官方热备

## 3. 首次启动（笔记本）
```bash
# 后端
cd backend
.venv/bin/pip install -r requirements.txt   # 首次
.venv/bin/python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
# 首次启动自动：建表/迁移/seed 默认提示词/注册定时任务/启动 inbox 监听

# 前端
cd frontend
npm install          # 首次
npm run dev          # http://localhost:5173
```
登录：打开页面输入 `ECHO_ACCESS_TOKEN`。
也可只跑后端（已 `npm run build` 时 FastAPI 直接托管 http://localhost:8000）。

## 4. 首次使用流程
1. **博主管理**：新建主博主 → 为它配置抖音/B站/小红书账号（填主页分享链接，系统自动解析平台 ID）
2. **同步数据**：点「同步前 20 条」或「全量同步」，页面显示进度条；完成后云端作品进入素材库/看板
3. **素材**：上传视频 → 编辑页「语音转文字」（真实阿里云）→ 确认标签
4. **选题/生成**：主页「抓取更新」→ 挑灵感 → 工作台生成/改写 → 保存/发布
5. **复盘**：看板查看增长曲线/赛道雷达；跑 ABCD 复盘

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
# ruff + mypy + pytest(53) + 前端 lint/build + 文档完整性
```

## 7. 常见运维
- 改 `.env` 后重启后端（配置启动时读取）
- 数据迁移自动（启动时幂等补列）；重大变更先 `scripts/backup.sh`
- 定时任务在进程内（APScheduler）；改时间在 `.env`（如 `ECHO_PLATFORM_SYNC_TIMES=07:30,18:00`）
- 接口/表结构文档重新生成：见 docs/DATABASE.md 头注（API 用 app.openapi() 生成，模型用 SQLAlchemy metadata 生成）
