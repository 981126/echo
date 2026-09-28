# echo（回声）— 自媒体复盘纠错平台

单用户、作者本人使用的个人系统：让 AI 越来越懂「你」的人设，每天自动产出与「人设 × 当日热点」匹配的选题与脚本，
并对已发布内容（抖音 / B站 / 小红书）做数据复盘与纠错，帮你找到适合的赛道（求职 / 面试 / 赚钱 / 知识）。

> 本仓库由 AI 编码工具（Codex 等）协作维护：**任何 AI 工具打开本仓库前，先读 `AGENTS.md`**。

## 当前真实能力（2026-09-06 快照）
- 素材库：本地素材（上传 / 数据目录下的 `inbox` 拖入（当前 `echo_resource/inbox`））+ 云端作品统一展示；封面、转写、标签、平台/赛道多选、跨平台同作品合并
- 语音转文字：手动触发，真实阿里云 ASR（上传前自动抽音轨，转写稿可 AI 校对）
- 平台数据：真实 TikHub 接入抖音/B站/小红书——博主账号管理、每日两轮 top15 同步（带实时进度条）、全量同步、
  单条/卡片同步、评论按点赞 Top50 入库展示、指标按天快照
- 每日选题与生成：热点（真实 TikHub 热搜）→ 人设/风格加权 →（生成方 × 评审方双模型讨论，R-139 起为唯一路径）→ 脚本草稿
- AI 设置：模型1/模型2 可分别配厂家+模型+API Key（保存即生效）；脚本生成的生成方/评审方、ASR 服务商与模型、讨论轮次、每日篇数都在这里；其余 AI 功能默认模型1、失败自动降级模型2（带日志/站内通知/稿子标记）
- AI 对话：多会话 ChatGPT 式流式问答，可调用系统数据工具
- 复盘：看板 + ABCD 复盘 + 赛道雷达（本地素材指标 + 平台数据）
- 工程：`scripts/verify.sh` 质量门禁（ruff + mypy + pytest 212 项 + 前端 lint/build + 文档一致性）、每日自动备份、需求归档

## 运行（开发机）
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
也可以 `cd frontend_v2 && npm run build` 后由后端 FastAPI 托管到 http://localhost:8000/v2/。

> ⚠️ 老前端 `frontend/`（Vue 3）**已废弃（R-168）**：只读保留、不再修改；
> 其构建产物仍由后端挂根路径（http://localhost:8000）作历史兜底。

## 质量门禁
```bash
PATH=backend/.venv/bin:$PATH PYTHON=backend/.venv/bin/python scripts/verify.sh
```

## 文档导航
| 文档 | 内容 |
|---|---|
| `docs/PRD.md` | 产品需求与功能范围（当前状态标注） |
| `docs/PRODUCT.md` | 产品/用户视角说明 |
| `docs/ARCHITECTURE.md` | 架构总览（技术栈/进程/模块/数据/部署） |
| `docs/DESIGN.md` | 开发设计细节（模块与数据流、关键逻辑） |
| `docs/API.md` | 全部接口（人工维护，`scripts/check_doc_consistency.py` 在 verify 中校验与 OpenAPI 一致） |
| `docs/DATABASE.md` | 27 张表结构（人工维护 + 注释；verify 校验表数量与代码一致） |
| `docs/QUICKSTART.md` | 小白/新设备上手 |
| `docs/GLOSSARY.md` | 术语表 |
| `docs/FAQ.md` | 常见问题 |
| `docs/milestones.md` | 里程碑与进度（M0–M52） |
| `docs/DECISIONS.md` | 关键决策记录 |
| `docs/WORKFLOW.md` | 新需求标准流程 |
| `docs/CHANGELOG.md` | 变更历史 |
| `requirements/` | 需求事实源（R-001~R-071 索引见 `requirements/README.md`） |

## 数据安全
- 密钥只在 `.env`（gitignore）；数据库与素材文件在数据目录（当前 `echo_resource/`）
- 每日 02:30 自动备份（`scripts/backup.sh`，保留最近 10 份）；也可手动执行
- 平台同步不会触碰本地视频 / 转写稿 / 脚本文案；同步按「平台 + 作品ID」幂等去重更新
