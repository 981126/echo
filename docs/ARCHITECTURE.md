# 架构总览（ARCHITECTURE）

> 给任何 agent 的"快速上下文包"：读完本文件即可理解系统如何运转、目录如何组织、如何运行与测试。

## 1. 系统形态
单用户、轻量低内存的**单进程单体**应用，部署在 NAS（Intel N150 / 4C12G）的 Docker 中，开发在笔记本。
所有重活（LLM / ASR）走云端 API，本地只跑 Web 服务 + 数据库 + 定时任务。

```
┌────────────────────────── NAS（Docker Compose）──────────────────────────┐
│                                                                          │
│  ┌──────────────┐   ┌──────────────────────────────────────────────┐    │
│  │ Vue3 SPA     │   │ FastAPI（单进程）+ APScheduler               │    │
│  │ (响应式静态)  │──▶│  ├─ api/      路由层（薄）                   │    │
│  └──────────────┘   │  ├─ services/ 业务层（厚，适配器都在此）       │    │
│                     │  ├─ models/   SQLAlchemy 模型                 │    │
│                     │  ├─ scheduler.py  每日流水线                  │    │
│                     │  └─ tasks.py      DB 任务表 + 后台线程         │    │
│                     │                                              │    │
│                     │   SQLite（data/echo.db）+ 文件（视频/转写/归档）│    │
│                     └──────────────────────────────────────────────┘    │
│                              ▲          ▲          ▲                    │
└──────────────────────────────┼──────────┼──────────┼────────────────────┘
                    阿里云 ASR   DeepSeek   QQ SMTP   热点源/指标源(适配器)
```

## 2. 分层与依赖方向（强制）
```
api（路由，薄） → services（业务，厚） → models（数据模型）
                      ↕ 不反向
                adapters（LLM/ASR/热点/指标/推送，可插拔）
```
- api 只做参数校验与转发（Pydantic schema）
- services 承载业务逻辑；所有外部依赖收敛在 services 的适配器内
- models 只描述数据结构，不包含业务逻辑
- 禁止反向依赖、禁止跨层跳跃

## 3. 模块清单（backend/app）
| 模块 | 职责 |
|---|---|
| `api/videos.py` | 素材库：上传/列表/标签/状态 |
| `api/persona.py` | 人设档案查看/编辑/确认建议 |
| `api/topics.py` | 每日选题列表、匹配、手动触发流水线 |
| `api/drafts.py` | 脚本草稿：生成/改写/保存/版本 |
| `api/metrics.py` | 指标查询与增长曲线 |
| `api/review.py` | 复盘报告（ABCD）与赛道雷达 |
| `api/requirements.py` | 需求归档的展示与状态 |
| `api/chat.py` | AI 对话（DeepSeek 函数调用，只读直接答/写操作需确认） |
| `services/transcription.py` | ASR 适配器（阿里云） |
| `services/persona.py` | 人设分析/增量建议/红线边界/改稿差异分析 |
| `services/topic_mining.py` | 热点抓取适配器（抖音/B站/小红书）与匹配打分 |
| `services/generation.py` | DeepSeek 生成（标题/封面字/脚本/平台外壳）+ 风格样本本地检索 |
| `services/metrics.py` | 指标三通道（cookie/导出/手动）与归一化 |
| `services/review.py` | 复盘与赛道雷达（按主赛道聚合，按发布天数归一化） |
| `services/notify.py` | QQ SMTP 邮件推送 |
| `services/requirements.py` | 需求编号归档（R-xxx 写入 requirements/） |

## 4. 关键数据流
### 每日选题流水线（早间，APScheduler 触发）
```
抓三平台热点 → 人设×热点匹配打分(DeepSeek) → 生成3+选题与脚本 → 入库 → QQ邮件推送(带工作台链接)
```
幂等：同一天重复运行不生成重复内容、不重复发邮件；中断可续跑；Web 可手动触发。
### 每日指标流水线
```
三通道取数(cookie/导出/手动) → 指标快照入库 → 更新看板与增长曲线
```
新老视频对比按"发布天数"归一化。
### 人设学习闭环
```
新视频发布 → 导入（Web 上传 / data/inbox 监听）→ 阿里云ASR转写 → AI校对
→ 增量分析(DeepSeek，表现加权) → AI建议扩人设 → 作者确认 → 档案更新(版本化)
→ 改稿差异分析：作者在 Web 改写脚本的差异是强纠偏信号
```

## 5. 数据模型（概要）
- `videos`（视频、平台、状态：计划中/已发布、计划发布时间、实际发布时间、广告标记、主赛道、标签）
- `transcripts`（转写稿、原始文案、校对状态）
- `persona_tags`（标签+描述、红线边界、来源：AI建议/手动、版本、确认状态）
- `hot_topics`（每日热点快照，保留 30 天）
- `drafts`（标题/封面字/脚本、平台外壳、作者改写记录、版本）
- `metrics_snapshots`（每日指标快照，全留）
- `feedback`（打分、采用标记）
- `review_reports`（复盘报告）
- `requirements`（需求编号、原文、状态、渠道、关联）
- `chat_messages`（AI 对话历史）

## 6. 目录结构
```
echo/
├── AGENTS.md / README.md
├── docs/                    # PRD / ARCHITECTURE / WORKFLOW / DECISIONS / milestones
├── requirements/            # 需求归档（事实源）
├── backend/
│   ├── app/                 # main.py / config.py / db.py / api/ / services/ / models/ / schemas/ / scheduler.py / tasks.py
│   ├── alembic/             # 数据库迁移
│   ├── tests/               # pytest（mock API，离线可跑）
│   └── scripts/
├── frontend/
│   ├── src/                 # views/ components/ api/ router/（响应式）
│   ├── package.json
│   └── vite.config.ts
├── scripts/verify.sh        # 质量门禁
└── data/                    # 运行时（gitignore，NAS 卷）
    ├── echo.db / videos/ / transcripts/ / inbox/ / exports/ / backups/
```

## 7. 运行与测试
### 开发（笔记本）
- 后端：`cd backend && pip install -e . && uvicorn app.main:app --reload`
- 前端：`cd frontend && npm install && npm run dev`
- 测试：`cd backend && pytest`（全部 mock，离线可跑）
- 质量门禁：`scripts/verify.sh`
### 部署（NAS，Docker）
- 配置 `.env`（见 `.env.example`）
- `docker compose up -d --build`
- 更新：`scripts/update.sh`（git pull + 重建 + 健康检查）
- 备份：`data/` 热备份 + `docs/` + `requirements/` 快照

## 8. 时区与约定
- 容器时区强制 `Asia/Shanghai`；每日任务按北京时间
- 流水线失败必须发出"失败"邮件告警，不允许静默失败
- 全部秘密走 `.env`，不硬编码
