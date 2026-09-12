# AGENTS.md — 项目运行手册（入口）

> 本文件是项目的「操作系统」。任何 AI 编码工具（Codex / Cursor / Claude Code / WorkBuddy 等）打开本仓库后，
> **必须先读本文件并严格遵守**；涉及业务细节时按下方文档顺序继续深入。
> 项目名：echo（回声）—— 自媒体复盘纠错平台。单用户，作者本人。

## 项目一句话
让 AI 越来越懂作者的人设：每日自动产出与「人设 × 当日热点」匹配的选题与脚本，对已发布内容做复盘纠错，辅助作者找到适合自己的赛道（抖音 / B站 / 小红书；求职 / 面试 / 赚钱 / 知识，当前仍在试错）。

## 开始任何工作前（必读，按顺序）
1. `docs/PRD.md` —— 产品需求（要做什么、当前已实现范围）
2. `docs/ARCHITECTURE.md` —— 架构总览（技术栈 / 进程 / 模块 / 数据 / 运行方式）
3. `docs/DESIGN.md` —— 开发设计细节（模块实现、数据流、关键逻辑、错误/并发处理）
4. `docs/milestones.md` —— 进度（做到哪、下一步做什么）
5. `docs/WORKFLOW.md` —— 标准流程细则（含需求反问清单）
6. `docs/DECISIONS.md` —— 关键决策记录（为什么这么设计，别改坏）
7. 按需：`docs/QUICKSTART.md`（本地跑起来）、`docs/API.md`（接口，人工维护）、`docs/DATABASE.md`（表结构，人工维护）、`docs/GLOSSARY.md`（术语）、`docs/FAQ.md`

> 注意：`docs/API.md` 与 `docs/DATABASE.md` 由**人工维护**（仓库内没有生成器脚本，此前"自动生成"的描述与实际不符，R-136 已更正）。
> 改代码后如涉及接口/表结构，请同步改这两份；`scripts/check_doc_consistency.py` 会在 `scripts/verify.sh` 中校验
> 「表数量/表名」与「路由数量/每条路由是否收录」，不一致会直接让门禁失败。

## 技术栈速览（现状，均为真实接入）
- 后端：Python FastAPI + APScheduler（单进程单体，轻量低内存）
- 前端：Vue 3 + Vite + Naive UI SPA（响应式，桌面/手机浏览器均可用）
- 数据库：SQLite + SQLAlchemy 2.x；运行时数据目录由 `.env` 的 `ECHO_DATA_DIR`/`ECHO_DB_PATH` 决定（当前 `echo_resource/`，**不是**仓库 `data/`）；schema 用幂等轻量迁移（Alembic 是 tech-debt，未落地）
- 真实外部服务（2026-09-06 起全部 real，配置非法会启动报错，见 R-068）：
  - 平台数据：TikHub（抖音/B站/小红书，含主页/作品/统计/评论）
  - LLM：DeepSeek（V4.1 Flash，模型 ID `deepseek-flash`）+ Kimi（生成默认 Kimi，可切 deepseek/alternate）
  - ASR：阿里云录音文件识别 FileTrans（+OSS 中转），上传前 ffmpeg 抽音轨
  - 热点：TikHub 热搜（real）
  - 邮件：QQ 邮箱 SMTP
- 部署：Docker Compose（NAS）；开发在笔记本

## 目录速览
```
echo/
├── AGENTS.md           # 本文件（入口）
├── README.md           # 人类快速上手
├── docs/               # 项目大脑：PRD/PRODUCT/ARCHITECTURE/DESIGN/WORKFLOW/DECISIONS/milestones/CHANGELOG/API/DATABASE/QUICKSTART/GLOSSARY/FAQ
├── requirements/       # 需求归档（事实源）：R-xxx.md + README 索引
├── backend/            # FastAPI：app/（api/services/models/core/schemas）tests/ scripts/
├── frontend/           # Vue 3：src/（views/components/api/router）
├── scripts/            # 项目级脚本：verify.sh（质量门禁）/ backup.sh / update.sh / check_doc_consistency.py
└── data/               # 仓库内遗留空目录（实际数据在 .env 指向的 echo_resource/）
```

## 当人类提出新需求时（强制流程）
1. **反问**：按「需求反问清单」（WORKFLOW.md 内）逐项追问作者可能未考虑的问题；作者回答/修改后再继续
2. **登记**：原文**原样**追加到 `requirements/R-xxx.md`（自动编号，禁止改写删减）；反问与确认结论一并记录
3. **PRD**：更新 `docs/PRD.md`
4. **里程碑**：在 `docs/milestones.md` 更新/拆分排期
5. **暂停确认**：展示计划，等作者说「继续」再写业务代码（线上明显的 bug 修复可在说明根因后直接修复并登记）
6. **实施**：按里程碑实现；每完成一个里程碑运行 `scripts/verify.sh` 并修复全部失败
7. **记录**：更新需求状态与 CHANGELOG；commit 信息带需求编号（如 `feat(R-070): ...` / `fix(R-068): ...`）

## 需求反问清单（收到新需求必须逐项过，不许跳过）
1. **范围与边界**：具体包含什么？明确不包含什么（非目标）？
2. **场景与影响**：在什么场景用？对现有功能/工作流有什么影响？
3. **数据**：需要哪些新数据？来源可靠吗？拿不到时怎么办？
4. **边界与异常**：空数据、失败、重复、极端情况怎么处理？
5. **验收标准**：怎么算完成？可测试吗？
6. **成本与性能**：会增加 API 成本或拖慢系统吗？
7. **依赖与风险**：依赖外部服务吗？它挂了怎么办？
8. **优先级**：现在做还是排期？

## 工程标准（五维，强制）
- **简单**：不过度设计；新增依赖必须说明理由；拒绝重复代码；路由薄、业务厚
- **易读**：统一风格（Python: ruff；前端: ESLint/Prettier）+ 类型标注 + 小函数 + 清晰命名
- **可靠**：测试覆盖（pytest + mock，离线可跑）+ 统一异常/重试/降级 + 日志 + 失败告警 + 备份
- **扩展**：适配器模式；分层依赖方向 api → services → models，不反向；接口契约稳定（Pydantic）
- **性能**：异步 IO（第三方请求用 httpx）；SQLite 索引；分页；长任务后台线程不阻塞 UI；前端按需加载

## 质量门禁（硬性）
任何改动必须通过 `scripts/verify.sh`（lint + 类型检查 + 测试 + 构建），**不通过不算完成**。
提示：沙箱/无 venv PATH 时用 `PATH=backend/.venv/bin:$PATH PYTHON=backend/.venv/bin/python scripts/verify.sh`。

## 硬性规则
- 未先更新 PRD/里程碑且未获作者确认前，禁止写业务代码（线上 bug 直接修复除外）
- 每次改动必须过 `scripts/verify.sh`，不允许带着失败继续推进
- 每个里程碑/需求一个 commit，提交信息带编号且清晰
- 不得悄悄扩大范围；新范围 = 新需求登记
- 遇到无法解决的问题，停下来说明，不要自作主张绕路
- API key 等秘密只放 `.env`（已被 gitignore），绝不写进代码/文档/commit
- **配置模式（重要）**：`.env` 中 `ECHO_TIKHUB_MODE` / `ECHO_HOT_SOURCE_MODE` / `ECHO_ASR_MODE` 只允许合法值
  （`mock`/`real`/`aliyun`）；行尾注释必须换行书写（`KEY=real` 后单独一行 `# 注释`），
  否则值会被整串解析 → 非法配置会**启动报错**（R-068 防静默回退 mock 写假数据）
- **交付前 AI 自测（强制）**：任何功能开发/修复完成后必须自测通过才算完成——`scripts/verify.sh` 全绿
  + 相关后端接口冒烟（真实或 mock 均可，跑通关键链路）+ 前端关键交互点检，并说明自测结论
- **改完必须保持服务运行（强制）**：每次改动/修复完成后，确保后端(8000)与前端(5173)处于运行状态且已加载最新代码；
  如被重启/中断需重新拉起并做 health 检查，再交付给作者验收
- 文档与代码同步更新：改功能必须同步 PRD / ARCHITECTURE / DESIGN / CHANGELOG；改接口/表结构需同步更新 API.md / DATABASE.md（verify 会校验一致性）
