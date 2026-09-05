# echo（回声）— 自媒体复盘纠错平台

让 AI 越来越懂你的人设：每日自动产出匹配选题与脚本，对已发布内容复盘纠错，辅助找到适合的赛道（抖音 / B站 / 小红书）。

## 快速开始
1. 配置环境变量：首次克隆时执行 `cp .env.example .env`，然后编辑 `.env` 填入配置（DeepSeek / 阿里云 ASR / QQ 邮箱授权码 / 访问令牌 `ECHO_ACCESS_TOKEN`）。`.env` 已被 gitignore，绝不上传
2. 本地开发启动：见下文「本地开发启动」
3. 部署：NAS 上 `docker compose up -d --build`
4. 更新：`scripts/update.sh`

## 本地开发启动（笔记本）

前置要求：Python 3.10+（推荐 3.12）、Node.js 18+ / npm。

### 1. 后端（FastAPI，端口 8000）

```bash
cd backend
python3 -m venv .venv             # 首次：创建虚拟环境
source .venv/bin/activate         # Windows: .venv\Scripts\activate
pip install -r requirements.txt   # 首次：安装依赖
uvicorn app.main:app --reload     # 启动开发服务器（代码变更自动重载）
```

验证：浏览器打开 http://localhost:8000/health ，返回 `{"status":"ok"}` 即成功。
后端启动时会自动初始化 SQLite 数据库（`data/echo.db`）、注册每日定时任务（APScheduler），并监听 `data/inbox/` 自动导入新视频。

### 2. 前端（Vue3 + Vite，端口 5173）

```bash
cd frontend
npm install    # 首次：安装依赖
npm run dev    # 启动开发服务器（热更新）
```

验证：浏览器打开 http://localhost:5173 即可访问工作台（Vite 已将 `/api` 与 `/health` 代理到后端 8000 端口）。
页面提示输入访问令牌时，填写 `.env` 中 `ECHO_ACCESS_TOKEN` 的值。

### 3. 质量门禁（每次改动后运行）

```bash
scripts/verify.sh   # lint + 类型检查 + 测试 + 前端构建
```

> 更详细的运行与架构说明见 `docs/ARCHITECTURE.md` §7；NAS 部署、备份见仓库根目录 `docker-compose.yml` 与 `scripts/update.sh`。

## 文档索引
| 文档 | 内容 |
|---|---|
| `AGENTS.md` | AI 行为手册（任何 agent 打开项目先读它） |
| `docs/PRD.md` | 产品需求（精简） |
| `docs/PRODUCT.md` | 产品功能手册（全部功能+流程图） |
| `docs/QUICKSTART.md` | ⭐ 小白上手指南（先读它） |
| `docs/ARCHITECTURE.md` | 架构总览与运行方式（详细版） |
| `docs/DESIGN.md` | 开发设计文档（算法/任务/扩展点） |
| `docs/API.md` | 完整接口文档（90 个接口，OpenAPI 生成） |
| `docs/DATABASE.md` | 数据库表结构设计（26 表，模型生成） |
| `docs/GLOSSARY.md` | 术语表（新手向） |
| `docs/FAQ.md` | 常见问题排查 |
| `docs/WORKFLOW.md` | 标准流程与需求反问清单 |
| `docs/DECISIONS.md` | 关键决策记录 |
| `docs/milestones.md` | 里程碑进度 |
| `requirements/` | 需求归档（R-xxx，事实源） |

## 对 AI 用户的一句话
在这个仓库里提需求 = 说一句话，agent 会先反问、再留档、再排期、你确认后实现。
