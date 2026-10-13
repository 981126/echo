# AGENTS.md — 编码纪律检查清单

> 任何 AI 编码工具打开本仓库后，先读本清单，再动手。技术细节见 `docs/ARCHITECTURE.md`，开发流程见 `docs/WORKFLOW.md`，工程与动效规范见 `docs/DESIGN.md` §8/§9。

## 新需求流程

1. **先聊天反问**：与作者确认边界、场景、验收标准、动效、非实时返回等（清单见 `docs/WORKFLOW.md`）。
2. **确认后再登记**：原文原样写入 `requirements/R-xxx.md`（编号取当前最大 +1）。
3. **更新 PRD/里程碑**：同步 `docs/PRD.md` 与 `docs/milestones.md`。
4. **等作者说「继续」**：不动业务代码；线上明显 bug 可先说明根因并修复，再登记。

## 编码纪律

- [ ] 在自己的分支上：`feat/r<数字>`，如 `feat/r221`；多 agent 并行时还在自己的 worktree 里。
- [ ] 一个需求一个 commit，commit 信息带编号：`feat(R-xxx): ...` / `fix(R-xxx): ...`。
- [ ] 禁止 `git add -A` / `git commit -a`；只 `git add <具体文件>`。
- [ ] 后端 `ruff` + `mypy`，前端 `ESLint` + `Prettier`；Python/TypeScript 必须带类型标注。
- [ ] 分层方向 `api → services → models`，不反向；拒绝重复代码，路由薄、业务厚。
- [ ] 改接口同步 `docs/API.md`，改表同步 `docs/DATABASE.md`。
- [ ] API key / 密钥只放 `.env`（已被 gitignore），不进代码/文档/commit。

## 并行开发（多 agent 时）

- [ ] 一需求一 worktree 一分支；每个 worktree 只服务一个需求。
- [ ] 并行时段不做 `git gc --prune=now`、不改写历史、不删别人的分支/ref、不用 `git stash`。
- [ ] 聚合文档（`docs/PRD.md`、`docs/CHANGELOG.md`、`docs/milestones.md`、`requirements/README.md`）只由收口人改；你只改自己的 `requirements/R-xxx.md`，并在末尾附「待收口文档改动」。
- [ ] 不杀别人的进程；按 `lsof` 查到的 PID 精确 `kill` 自己的进程。
- [ ] 冲突解完后必须重跑 `scripts/verify.sh`。

> worktree/端口/拷库/依赖/收尾的具体操作见 `docs/OPS-PARALLEL.md`（作者/收口人操作手册，agent 不必读）。

## 交付前（必须全绿）

- [ ] `scripts/verify.sh` 全绿（ruff + mypy + pytest + 前端 lint/build + 文档一致性）。
- [ ] AI 自测：相关后端接口冒烟（mock 或真实均可）+ 前端关键交互点检。
- [ ] 动效点检：新交互都有动效且流畅，切换类无空白闪帧（规范见 `docs/DESIGN.md` §8）。
- [ ] 非实时结果可见：耗时/后台任务有进行中动效，切页/刷新回来仍能恢复「进行中」（规范见 `docs/DESIGN.md` §8.6）。
- [ ] 服务保持运行：后端 `http://127.0.0.1:8000` 与前端 `http://localhost:3000` 已启动并加载最新代码，health 与页面可访问。

## 一句话

**少读文档、多 checklist：边界先聊清，分支要拉对，改完 verify 绿，服务要跑着。**
