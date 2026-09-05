# AGENTS.md — 项目运行手册

> 本文件是本项目的"操作系统"。任何 AI 编码工具（Codex / Cursor / Claude Code / WorkBuddy 等）
> 打开本仓库后，**必须先读本文件并严格遵守**。
> 项目名：echo（回声）—— 自媒体复盘纠错平台。单用户，作者本人。

## 项目一句话
让 AI 越来越懂作者的人设：每日自动产出与"人设 × 当日热点"匹配的选题与脚本，对已发布内容复盘纠错，辅助作者找到适合的赛道（抖音 / B站 / 小红书；求职 / 面试 / 赚钱 / 知识）。

## 开始任何工作前（必读，按顺序）
1. `docs/PRD.md` —— 产品需求（这项目要做什么）
2. `docs/ARCHITECTURE.md` —— 架构总览（模块 / 数据流 / 目录 / 如何运行与测试）
3. `docs/milestones.md` —— 当前进度（做到哪、下一步做什么）
4. `docs/WORKFLOW.md` —— 标准流程细则（含需求反问清单）
5. `docs/DECISIONS.md` —— 关键决策记录（为什么这么设计，别改坏）

## 技术栈速览
- 后端：Python FastAPI + APScheduler（单进程单体，轻量低内存）
- 前端：Vue 3 + Vite SPA（响应式，桌面/手机浏览器均可用）
- 数据库：SQLite + Alembic 迁移；运行时数据在 `data/`（gitignore，NAS 挂载卷）
- LLM：DeepSeek API；ASR：阿里云；邮件：QQ 邮箱 SMTP
- 部署：Docker Compose（NAS）；开发在笔记本
- 扩展方式：适配器模式（LLM / ASR / 热点源 / 指标源 / 推送均可插拔）

## 目录速览
```
echo/
├── AGENTS.md           # 本文件（入口）
├── README.md           # 人类快速上手
├── docs/               # 项目大脑：PRD / ARCHITECTURE / WORKFLOW / DECISIONS / milestones
├── requirements/       # 需求归档（事实源）：R-xxx.md + README 索引
├── backend/            # FastAPI：app/（api/services/models）tests/ scripts/
├── frontend/           # Vue 3：src/（views/components/api/router）
├── scripts/            # 项目级脚本（verify.sh 质量门禁）
└── data/               # 运行时数据（gitignore）：app.db / videos / transcripts / inbox / backups
```

## 当人类提出新需求时（强制流程）
1. **反问**：按"需求反问清单"（下方）逐项追问作者可能未考虑的问题；作者回答/修改后再继续
2. **登记**：原文**原样**追加到 `requirements/R-xxx.md`（自动编号，禁止改写删减）；反问与确认结论一并记录
3. **PRD**：更新 `docs/PRD.md`
4. **里程碑**：在 `docs/milestones.md` 更新/拆分排期
5. **暂停确认**：展示计划，等作者说"继续"再写代码
6. **实施**：按里程碑实现；每完成一个里程碑运行 `scripts/verify.sh` 并修复全部失败
7. **记录**：更新需求状态与 CHANGELOG；commit 信息带需求编号（如 `feat(R-003): ...`）

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
- **性能**：异步 IO；SQLite 索引；分页；长任务后台线程不阻塞 UI；前端按需加载

## 质量门禁（硬性）
任何改动必须通过 `scripts/verify.sh`（lint + 类型检查 + 测试 + 构建），**不通过不算完成**。

## 硬性规则
- 未先更新 PRD/里程碑且未获作者确认前，禁止写业务代码
- 每次改动必须过 `scripts/verify.sh`，不允许带着失败继续推进
- 每个里程碑/需求一个 commit，提交信息带编号且清晰
- 不得悄悄扩大范围；新范围 = 新需求登记
- 遇到无法解决的问题，停下来说明，不要自作主张绕路
- API key 等秘密只放 `.env`（已被 gitignore），绝不写进代码/文档/commit
- **交付前 AI 自测（强制）**：任何功能开发或修复完成后，必须自测通过才算完成——scripts/verify.sh 全绿 + 相关后端接口冒烟 + 前端关键交互点检（弹窗/按钮/勾选/跳转），并说明自测结论
- 文档与代码同步更新：改功能必须同步 PRD / ARCHITECTURE / CHANGELOG
