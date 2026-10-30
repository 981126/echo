# echo（回声）— 自媒体复盘纠错平台

> 本文定位：项目一句话、当前能力概览、文档导航与快速入口。技术细节见 `docs/ARCHITECTURE.md`，agent 编码纪律见 `AGENTS.md`。
单用户、作者本人使用的个人系统：让 AI 越来越懂「你」的人设，每天自动产出与「人设 × 当日热点」匹配的选题与脚本，
并对已发布内容（抖音 / B站 / 小红书）做数据复盘与纠错，帮你找到适合的赛道（求职 / 面试 / 赚钱 / 知识）。
> 本仓库由 AI 编码工具协作维护：**任何 AI 工具打开本仓库前，先读 `AGENTS.md`**。
> 
## 运行
```bash
# 1. 环境：根目录 .env 已配置（ECHO_ 前缀），数据在 .env 指向的目录（当前 echo_resource/）
# 2. 后端（端口 8000）
cd backend
.venv/bin/python -m uvicorn app.main:app --host 0.0.0.0 --port 8000

# 3. 前端（frontend_v2，端口 3000，dev 反向代理 8000）
cd frontend_v2
npm install   # 首次
npm run dev
```
浏览器打开 http://localhost:3000 （访问令牌 = `.env` 的 `ECHO_ACCESS_TOKEN`）。
也可以 `cd frontend_v2 && npm run build` 后由后端 FastAPI 托管到 http://localhost:8000/。


## 文档导航
| 文档 | 内容 |
|---|---|
| `docs/ARCHITECTURE.md` | 架构总览（技术栈/进程/模块/数据/部署） |
| `docs/DATABASE.md` | 27 张表结构（人工维护 + 注释；verify 校验表数量与代码一致） |
| `docs/GLOSSARY.md` | 术语表 |
| `docs/milestones.md` | 里程碑与进度 |
| `docs/DECISIONS.md` | 关键决策记录 |
| `docs/CHANGELOG.md` | 变更历史 |
| `requirements/` | 需求事实源,索引见 `requirements/README.md`） |
