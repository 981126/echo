# AGENTS.md — 编码纪律检查清单

> 任何 AI 编码工具打开本仓库后，先读本清单，再动手。技术细节见 `docs/ARCHITECTURE.md`，开发流程见 `docs/WORKFLOW.md`，工程与动效规范见 `docs/DESIGN.md` §8/§9。

## 新需求流程

1. **先聊天反问**：与作者确认边界、场景、验收标准、动效、非实时返回等（清单见 `docs/WORKFLOW.md`）。
2. **确认后再登记**：原文原样写入 `requirements/R-xxx-<short-description>.md`（编号取当前最大 +1，slug 用英文关键词短横线连接）。
3. **更新 PRD/里程碑**：同步 `docs/PRD.md` 与 `docs/milestones.md`。
4. **等作者说「继续」后开工**；开发完成且 `scripts/verify.sh` 全绿后，agent 主动将 `feat/rxxx` 合并到 `main` 并 push。

## 编码纪律

- [ ] 在自己的分支上：`feat/r<数字>`，如 `feat/r221`；多 agent 并行时还在自己的 worktree 里。
- [ ] 一个需求一个 commit，commit 信息带编号：`feat(R-xxx): ...` / `fix(R-xxx): ...`。
- [ ] 禁止 `git add -A` / `git commit -a`；只 `git add <具体文件>`。
- [ ] 后端 `ruff` + `mypy`，前端 `ESLint` + `Prettier`；Python/TypeScript 必须带类型标注。
- [ ] 分层方向 `api → services → models`，不反向；拒绝重复代码，路由薄、业务厚。
- [ ] 改接口同步 `docs/API.md`，改表同步 `docs/DATABASE.md`。
- [ ] API key / 密钥只放 `.env`（已被 gitignore），不进代码/文档/commit。
- [ ] 开发完成且 `scripts/verify.sh` 全绿后，agent 自行合并：单 agent / 多 agent 各自负责自己的 `feat/rxxx`。合并命令 `git checkout main && git pull --ff-only && git merge --ff-only feat/rxxx && git push`；合并后删除本地分支 `git branch -d feat/rxxx`，**保留远程分支**。

## 并行开发（多 agent 时）

> 简化自 `docs/OPS-PARALLEL.md`，语义不变。详细命令与翻车记录见该文档。
> **原则：一需求一 worktree 一分支；主干只做调度与合并，不写业务代码。**

### 开工

- [ ] 由作者/收口人在主干仓库建 worktree：`git worktree add /Users/yeah/document/project/echo-r221 -b feat/r221 main`。
- [ ] 编号靠 git 原子抢占；若分支已存在，换号或找收口人，不要自己读最大号 +1。
- [ ] 端口按需求编号算：`API=8000+(R mod 100)`，`WEB=3000+(R mod 100)`。开工前 `lsof` 确认空闲。
- [ ] 数据库独立（R-235 起为 PostgreSQL）：先拷主干的 `.env`，再把 worktree 的 `ECHO_DATABASE_URL` 指向自己的库——推荐在 PG 上为每个 worktree 建独立库（如 `echo_r221`，用 `scripts/init_test_db.sh SOURCE_URL=… TARGET_URL=postgresql+psycopg://…/echo_r221` 从 echo_dev 复制结构+数据），`.env` 里改库名即可；端口不变。`ECHO_DATA_DIR` 保持共享主干。
- [ ] 依赖共享：前端 `node_modules` 用硬链接（`cp -al`）并删 `.vite`；后端 `.venv` 用软链。worktree 内禁止 `npm install`/`pip install`。

### 运行隔离

- [ ] 每个 worktree 独占一个分支、一份数据库、一组端口。
- [ ] 素材目录共享；但分支里删/改名文件会真的删掉共享原件，清理"孤儿"时尤其危险。
- [ ] 浏览器 token 共享，别把副实例页面当主干操作。
- [ ] 副后端定时任务会真实跑 TikHub/LLM，用完就停，不要长驻。
- [ ] 副 worktree 前端验收走 `npm run build` + 起自己后端；不要同时跑多个前端 dev server。

### 并行纪律

- [ ] 一需求一 worktree 一分支；每个 worktree 只服务一个需求。
- [ ] 不 `git gc --prune=now`、不改写历史、不删别人的分支/ref、不用 `git stash`。
- [ ] 聚合文档（`docs/PRD.md`、`docs/CHANGELOG.md`、`docs/milestones.md`、`requirements/README.md`）只由收口人改；你只改自己的 `requirements/R-xxx.md`，并在末尾附「待收口文档改动」。
- [ ] 只杀自己的进程；按 `lsof` PID 精确 `kill`。禁止 `pkill -f uvicorn`/`vite`。
- [ ] 冲突解完后必须重跑 `scripts/verify.sh`。

### 收尾

- [ ] 顺序：先停服务，再删目录。
- [ ] 在 worktree 里 `git rebase main` → 解冲突 → 重跑 `verify.sh`。
- [ ] 每个 agent 自己执行合并：`git checkout main && git pull --ff-only && git merge --ff-only feat/rxxx && git push`。
- [ ] 合并后再跑 `verify.sh` 兜底，主干起服务并 health 通过。
- [ ] 停掉本 worktree 的后端/前端/后台任务，`lsof` 确认端口释放。
- [ ] `git worktree remove <目录>` + `git branch -d feat/rxxx`（**保留远程分支**）+ `git worktree prune`。
- [ ] 主干 `git pull --ff-only`；lock 文件变了才 `npm ci` / `pip install`。

## 交付前（必须全绿）

- [ ] `scripts/verify.sh` 全绿（ruff + mypy + pytest + 前端 lint/build + 文档一致性）。
- [ ] AI 自测：相关后端接口冒烟（mock 或真实均可）+ 前端关键交互点检。
- [ ] 动效点检：新交互都有动效且流畅，切换类无空白闪帧（规范见 `docs/DESIGN.md` §8）。
- [ ] 非实时结果可见：耗时/后台任务有进行中动效，切页/刷新回来仍能恢复「进行中」（规范见 `docs/DESIGN.md` §8.6）。
- [ ] 服务保持运行：后端 `http://127.0.0.1:8000` 与前端 `http://localhost:3000` 已启动并加载最新代码，health 与页面可访问。

## 一句话

**少读文档、多 checklist：边界先聊清，分支要拉对，改完 verify 绿，服务要跑着。**
