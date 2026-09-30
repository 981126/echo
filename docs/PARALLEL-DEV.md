# 多 agent 并行开发约定（PARALLEL-DEV）

> 适用：**多个 agent 同时改这个仓库**。单个 agent 顺序开发不需要本文档。
> 一句话原则：**一需求一 worktree 一分支；主干仓库只做调度与合并，不写业务代码。**
> 需求本身的流程（反问 → 登记 → PRD/里程碑 → 暂停确认 → 实施 → 自测 → 文档同步 → 提交）见 `docs/WORKFLOW.md`；本文档只管**并行时的环境与纪律**。

## 1. 什么会真正"污染代码"

| 污染源 | 后果 | 解法 |
|---|---|---|
| 多个 agent 共享同一个工作树 | 同一批文件互相覆盖；共用 index，`git status` 分不清谁的改动 | `git worktree`（独立工作文件 + index + HEAD） |
| `git add -A` / `commit -a` | 把别人未提交的半成品当自己的提交进去 | worktree 下 `add -A` 只看得到自己；再加纪律 `git add <具体文件>` |
| 改写历史 / `gc --prune=now` / 删 ref | 对象库与 `refs/*` 全仓库共享，会打断别人的分支与撤销链 | 只在所有 agent 空闲时做；不删别人的 ref |

其余情况（多人都改 `PRD.md`/`CHANGELOG.md`/`milestones.md`/`requirements/README.md`）属于**合并冲突**，git 会明确报错、人工合并即可。

> **判据**：①一 agent 一 worktree ②不 `git add -A` ③并行时段不 gc／不改写历史／不删 ref。
> **注意**：worktree 只解决"环境互踩"；"两个人改同一个文件/函数"仍然会冲突，靠分工与收口（§5.2）解决。

---

## 2. 开工

### 2.1 命名与编号

| 东西 | 形式 | 例 |
|---|---|---|
| 需求编号 | `R-<数字>`（`requirements/R-xxx-简短名.md`） | `R-221` |
| 分支 | `feat/r<数字>` | `feat/r221` |
| worktree 目录 | 与主干同级 `echo-r<数字>` | `/Users/yeah/document/project/echo-r221` |
| commit | `feat(R-<数字>): ...` | `feat(R-221): ...` |

**编号靠 git 原子抢占，不要自己读最大号 +1**（两个人同时读会拿到同一个号）：

```bash
cd /Users/yeah/document/project/echo
git worktree add /Users/yeah/document/project/echo-r221 -b feat/r221 main
# 已被占时报 fatal: a branch named 'feat/r221' already exists → 换号或找收口人
# 要基于别人的分支：git worktree add <目录> <已存在的分支名>
```

**谁建**：作者本人（或收口人）在主干仓库建。agent 会话的工作区被沙箱限制在自己目录内，通常无权在上级目录建目录。
**一个 worktree 只服务一个需求**：做完合并后收尾（§6）再开下一个；不要在一个 worktree 里轮着做两个需求。

### 2.2 端口算号

```bash
R=r221; N=21                                  # N = R 号 mod 100
API=$((8000 + N))                             # → 8021
WEB=$((3000 + N))                             # → 3021
```

| 实例 | 后端 | 前端 |
|---|---|---|
| 主干 | 8000 | 3000 |
| R-221 / R-222 | 8021 / 8022 | 3021 / 3022 |
| 边界 | R 号 `mod 100 == 0`（如 R-200）会算出 8000/3000 与主干撞 → 改用 +100（8100/3100） |
| 边界 | 同尾号需求（R-221 与 R-321）同时并行 → 后者 +100 |

**端口被占怎么办**（开工前 `lsof -nP -iTCP:$API -sTCP:LISTEN`）：

1. 先判断占用者是不是自己的僵尸进程：`lsof -p <PID> | head` 看它的 cwd/命令；确认是自己的才 `kill <PID>`。
2. **禁止 `pkill -f uvicorn` / `pkill -f vite`** —— 会连带杀掉主干和其它 agent 的正经服务。
3. 换端口：后端 `--port 8022`。**副 worktree 换前端端口没有意义**（`vite.config.ts` 的 proxy 写死 `http://localhost:8000`），副实例一律走 §4 的「build + 自己的后端」。
4. 端口跟编号一起在主干发放，不要现场随机挑。

### 2.3 库：拷库文件 + 指向拷贝（**素材目录不拷**）

顺序固定：**拷 `.env` → 拷库 → 校验 → 改 `ECHO_DB_PATH`**。

```bash
WT=/Users/yeah/document/project/echo-$R

# ① 拷主干的 .env（这一轮先别改）
cp /Users/yeah/document/project/echo/.env "$WT/.env"

# ② 拷贝库文件（~86MB）。主干 ECHO_DATA_DIR 有 21GB 素材（videos 19G + covers 387M），不拷
mkdir -p "$WT/echo_resource"
sqlite3 /Users/yeah/document/project/echo/echo_resource/echo.db ".backup '$WT/echo_resource/echo.db'"

# ③ 校验拷贝是真的（防"拷到空库"：R-133 里 backup.sh 曾"成功"备份出一个 4KB 空库）
sqlite3 "$WT/echo_resource/echo.db" "PRAGMA integrity_check; SELECT count(*) FROM sqlite_master WHERE type='table';"
#   期望 ok + 31 张表；若是 0 张表 → 停下排查，别启动后端

# ④ 只改 ECHO_DB_PATH 指向这份拷贝（ECHO_DATA_DIR 保持不动 = 继续共享主干素材）
#    必须绝对路径：相对路径按启动 CWD（cd backend）解析 → 落到 backend/ 下，还可能越出沙箱导致 SQLite 只读
sed -i '' -e "s|^ECHO_DB_PATH=.*|ECHO_DB_PATH=$WT/echo_resource/echo.db|" "$WT/.env"
```

最终 `.env` 两行（一个共享、一个独立）：

```bash
ECHO_DATA_DIR=/Users/yeah/document/echo_resource                             # 共享（21GB 素材）
ECHO_DB_PATH=/Users/yeah/document/project/echo-r221/echo_resource/echo.db   # 独立（86MB 拷贝）
```

> ⛔ **不要先改 `.env` 再拷库**：拷贝失败（路径写错/磁盘满/源库不存在）时，后端对着不存在的路径启动，`sqlite3.connect` 会**静默新建空库**，你会得到一个"看着正常、其实没数据"的环境。

### 2.4 依赖：硬链接 + 软链

```bash
# 前端：硬链接克隆（262MB / 1.7 万文件 → 约 4.4 秒、只多 ~10MB）
cp -al /Users/yeah/document/project/echo/frontend_v2/node_modules "$WT/frontend_v2/node_modules"
rm -rf "$WT/frontend_v2/node_modules/.vite"      # 必做：它是 node_modules 里唯一会被写的目录
# 后端：软链共享 venv
ln -s ../../echo/backend/.venv "$WT/backend/.venv"
```

### 2.5 最后一步

把 agent 会话的工作目录设成 `$WT`（否则沙箱不让写、后端会因数据库只读而起不来）。

---

## 3. 依赖共享规则（硬链 vs 软链）

| 目录 | 方式 | 命令 | 实测 |
|---|---|---|---|
| `frontend_v2/node_modules` | **硬链接**（真实文件条目，共享同一 inode） | `cp -al` | 262MB → 4.4 秒，多占 ~10MB |
| `backend/.venv` | **软链** | `ln -s` | `sys.prefix` 正确，fastapi/pip 正常 |

**前端为什么不能软链**：Node/Vite 按 **realpath** 解析模块 —— ① 模块被解析到主仓库真实路径，Vite `server.fs.allow` 可能 403；② 同一个包出现两个物理位置 → **React 双实例** → `Invalid hook call`；③ 两个 dev server 共用主仓库的 `.vite` 缓存 → 互相弄脏。硬链接是一个**真实目录树**（不是跳转），没有这些问题。

**后端为什么可以软链**：Python 靠自身位置找 `pyvenv.cfg` 定 `sys.prefix`，依赖都在绝对路径的 `site-packages`；应用代码从**各自 CWD** 导入。即「代码是我的，依赖是共享的」——对 Python 成立，对 Node 不成立。

### ⛔ 共享 = 只读

| | 允许 | 禁止 |
|---|---|---|
| 前端硬链 | `npm run dev/build/lint`、`npx vitest` | **在 worktree 里 `npm install <包>`**（原地改写会污染所有共享副本） |
| 后端软链 | 跑 uvicorn、pytest | **在 worktree 里 `pip install -r requirements.txt`**（装进共享 venv，连主干一起影响） |

**新增依赖**：回主干仓库装 → 提交 `package-lock.json` / `requirements.txt` → 各 worktree 重跑 `cp -al`（前端），后端软链自动跟随。
**边界**：`cp -al` 要求同一文件系统（都在 `/Users` 下没问题）；worktree 放到外接卷时改用 `npm ci`。

---

## 4. 运行时隔离

### 4.1 资源一览

| 资源 | 规则 |
|---|---|
| 端口 | §2.2 算号；开工前 `lsof` 确认空闲 |
| 数据库 | **只拷这个**：每个 worktree 一份库文件，`ECHO_DB_PATH` 指向它（§2.3）。共用 = SQLite 写锁 + 数据互相污染 |
| 素材目录 | **不拷**：`ECHO_DATA_DIR` 保持共享主干（21GB）。风险与处置见 §4.3 |
| 浏览器会话 | 所有实例共用同一个 `ECHO_ACCESS_TOKEN`，前端存的是同一个 localStorage 键 `echo_v2_token` → **登录一次，各端口都有效**；反过来也意味着别拿 8021 的页面当成主干在操作 |
| 邮件链接 | `ECHO_WEB_BASE_URL` 指向主干（默认 `http://localhost:8000`），副实例发出的邮件链接会指到主干 |
| 备份 | **库有备份**（`scripts/backup.sh` + `schema_guard` 的 pre_upgrade 自动备份）；**素材没有备份** |
| 定时任务 | ⚠️ 已知行为：`setup_scheduler()` 在 `app/main.py` 无条件启动，每个后端实例都会跑每日流水线/平台同步/备份 → **起 N 个副后端 = N 份 TikHub/LLM 消耗**。目前无开关，约定：**副后端用完就停，不要长驻** |
| 前端 dev server | **同一时刻只归一个 worktree**（proxy 写死 8000） |
| 副 worktree 的前端验收 | 走 **build + 自己的后端**（零配置、无串台）：<br>`cd "$WT/frontend_v2" && npm run build`<br>`cd "$WT/backend" && ./.venv/bin/python -m uvicorn app.main:app --port 8021`<br>浏览器开 `http://localhost:8021/` —— 后端按**自身文件位置**托管 `frontend_v2/dist`（`app/main.py` 的 `Path(__file__).resolve().parents[2]`），只服务自己的产物 |
| 门禁与构建 | `verify.sh` 会跑 pytest + vitest + vite build，**很吃 CPU**：2-3 个 worktree 同时跑会互相拖慢甚至超时，交付前错开跑 |

### 4.2 数据库为什么必须独立

`.env` 被 gitignore，新 worktree 拷过去的就是主干的**绝对路径** —— `ECHO_DB_PATH` 不改就等于所有分支共用同一个库文件。

| 情况 | 实际用的库 | 结果 |
|---|---|---|
| 没拷 `.env` | config 默认 `data_dir=./data`（相对启动 CWD）→ `backend/data/echo.db` | 各一份，但是**空库**（各自建表 + seed） |
| 拷了 `.env` 但**没改 `ECHO_DB_PATH`** | `/Users/yeah/document/echo_resource/echo.db` | ❌ **所有 worktree 共用同一个库文件** |
| 按本规则改过 | `$WT/echo_resource/echo.db` | ✅ 各自独立 |

共用同一个库的后果：

1. **SQLite 单写**：`docs/QUICKSTART.md` 明确禁止多 worker；两个后端写同一文件 → `database is locked`、长任务/同步随机失败；且各实例的 `_housekeep_job` 会互相删对方的记录。
2. **迁移互相踩**：各分支启动都跑幂等 `_migrate_*`；A 改表时 B 启动 → `schema_guard` 报「缺列」，且**库结构被先启动的分支定型**。
3. **数据与配置互相污染**：A 的测试草稿出现在 B 的页面；A 清数据会删掉 B 的验证数据；`app_kv` 里的**模型设置与各功能预算**是全局的，一边改预算影响另一边。

**拷贝位置与文件名**：`$WT/echo_resource/echo.db`（放在 worktree 内，因为 ① 沙箱只允许写自己的会话工作区，写外面会变成 SQLite 只读；② `.gitignore` 已忽略 `echo_resource/`，不会被误提交）。想一眼看出是谁的，可以叫 `echo-r221.db`（同步改 `ECHO_DB_PATH`；SQLite 的 `-wal`/`-shm` 会同名伴随）。

**用不用拷真实库**：纯后端逻辑验证用**空库**最省（启动自动 `create_all` + seed 默认提示词）；要验真实数据渲染（素材库、草稿列表、平台统计）才拷。10 个 worktree ≈ 860MB。想「只读共享」同一个库不可行——启动必然要写（迁移、seed、`app_kv`、任务表）。

### 4.3 素材目录是共享的（刻意选择）

`ECHO_DATA_DIR` 指向主干，于是 `videos/covers/uploads` 共用。**作者已确认（2026-09-30）：开发分支允许删除/重命名共享素材**——以下是知情信息，不是禁令：

- 删**库记录**只影响自己那份拷贝；删**文件**是从共享目录删**唯一原件**。`api/videos.py`（`delete_video` / `remove_video_file` / `delete_cover` / `attach_video` / 换封面）与 `api/creators.py`（换头像）里的 `unlink` 删的都是别人的库仍在引用的文件 → 用到时才 404，不会自愈。
- **改标题会改真实文件名**（落盘名 = 标题-视频/封面，R-058 的 `rename_to()`；触发点 `videos.py` 改标题/批量改名、`platform.py` 同步改名），影响同上，且**双向**：主干改名也会让分支的旧库记录失效。
- **孤儿清理最危险**：分支的库是快照，主干/别的分支之后新增的文件在它库里查不到 → 被当"孤儿"删掉。项目真实先例见 §8。
- 想避开这些影响（例如专门验删除/清理逻辑）的分支，把**会写的目录**单独指到 worktree 即可（`config.py` 支持逐个覆盖，不必拷整个数据目录；删除走 `unlink(missing_ok=True)`，对不存在的文件静默跳过）：
  ```bash
  ECHO_VIDEOS_DIR=$WT/echo_resource/videos      # 或只隔离 uploads / covers
  ECHO_COVERS_DIR=$WT/echo_resource/covers
  ECHO_UPLOADS_DIR=$WT/echo_resource/uploads
  ```

---

## 5. 共享资源的纪律

1. **提交只加自己的文件**：`git add <具体文件>`，**永不 `git add -A`**；commit 带需求号，一需求一 commit（不夹带别人改动）。
2. **聚合文档单写者**：并行期间 `docs/PRD.md`、`docs/CHANGELOG.md`、`docs/milestones.md`、`requirements/README.md` **只由收口人改**（默认作者本人）。其它 agent 只写自己的新文件 `requirements/R-xxx.md`（新文件永不冲突），并在文件末尾附「待收口文档改动」，把要加的行草拟好。
3. **共享 `.git` 的禁令**：并行时段**不做** `git gc --prune=now`、不改写历史、不删别人的分支/ref、不用 `git stash`（`refs/stash` 是全局的，别人 `pop` 可能弹出你的东西）。
4. **不杀别人的进程**：只能按 `lsof` 查到的 PID 精确 `kill`（§2.2）。
5. **冲突解完必须重跑门禁**：聚合文档冲突两边都保留；解错不会报错，但 `scripts/verify.sh` 会校验「表数量/表名」与「路由数量/每条路由」，不一致直接红。
6. **不停别人的服务**：收尾只停自己 worktree 起的进程（§6.2）。

---

## 6. 收尾

**顺序不可颠倒：先停服务，再删目录。** 进程的 CWD 就在目录里，删了目录而进程还在跑会出现：① SQLite 写到已被 unlink 的 inode；② 定时任务继续烧 TikHub/LLM；③ 端口不释放挡住主干启动。

### 6.1 合并（在主干仓库做；分支上应只有一个 commit）

```bash
R=r221; N=21; WT=/Users/yeah/document/project/echo-$R
API=$((8000 + N)); WEB=$((3000 + N))

cd /Users/yeah/document/project/echo
git switch main && git status --short          # 必须干净
# 推荐：先在 worktree 里 git rebase main → 解冲突 → 重跑 verify → 回主干快进（历史线性）
git merge --ff-only feat/$R                    # ff 不了时用 git merge --no-ff feat/$R
PYTHON="$PWD/backend/.venv/bin/python" scripts/verify.sh   # 合并结果必须再绿一次
git push origin main                           # 走远端协作时
```

### 6.2 停服务

```bash
lsof -nP -iTCP:$API -sTCP:LISTEN               # 拿 PID；先 lsof -p <PID> 确认归属
kill <后端PID> <前端PID>; sleep 2
lsof -nP -iTCP:$API -sTCP:LISTEN || echo "后端端口已释放"
lsof -nP -iTCP:$WEB -sTCP:LISTEN || echo "前端端口已释放"
# 用工具的后台任务起的服务，也要把那个后台任务停掉
```

### 6.3 删 worktree

```bash
sqlite3 "$WT/echo_resource/echo.db" ".backup /Users/yeah/document/echo_resource/verify_$R.db"   # 可选：留档验证库
git worktree remove "$WT"                      # 被拒时先看 git -C "$WT" status --short 再决定 --force
git worktree list                              # 应只剩主干
git branch -d feat/$R                          # 已合入才删得掉（-d 会校验）；-D 强制
git worktree prune                             # 手工删过目录时清残留登记
```

`git worktree remove` 失败的两个常见原因：① 目录里有未提交/未跟踪文件（`.env`、`echo_resource/` 是 gitignore 的，不算脏）；② 某个 shell 的 CWD 还在该目录里（先 `cd` 出来）。

### 6.4 主干拉最新 + 启动 + health

```bash
git switch main && git pull --ff-only
git diff --name-only HEAD@{1} HEAD -- frontend_v2/package-lock.json backend/requirements.txt
#   有 package-lock.json → cd frontend_v2 && npm ci
#   有 requirements.txt   → cd backend && ./.venv/bin/python -m pip install -r requirements.txt
lsof -nP -iTCP:8000 -sTCP:LISTEN; lsof -nP -iTCP:3000 -sTCP:LISTEN   # 确认没被占
cd backend && ./.venv/bin/python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
cd frontend_v2 && npm run dev                  # 3000

TOK=$(grep '^ECHO_ACCESS_TOKEN=' .env | cut -d= -f2-)
curl -s -o /dev/null -w 'backend  %{http_code}\n' http://127.0.0.1:8000/health
curl -s -o /dev/null -w 'frontend %{http_code}\n' http://localhost:3000/
curl -s -o /dev/null -w 'api      %{http_code}\n' -H "X-Access-Token: $TOK" 'http://127.0.0.1:8000/api/drafts?limit=1'
```

⚠️ 切回主干 = 用的是**真实数据库**，与 worktree 里那份验证库不是同一个；别在主干上做破坏性验证。

---

## 7. 检查表

**开工前 30 秒**

```bash
R=r221; N=21; WT=/Users/yeah/document/project/echo-$R; API=$((8000+N)); WEB=$((3000+N))
pwd                                                          # ① 我在自己的 worktree 里吗
git branch --show-current                                    # ② 分支名 = feat/rxxx 吗
lsof -nP -iTCP:$API -sTCP:LISTEN                             # ③ 我的端口空着吗
sqlite3 "$WT/echo_resource/echo.db" "SELECT count(*) FROM sqlite_master WHERE type='table';"   # ④ 库是拷贝来的、非空（~31 张表）
grep -E '^ECHO_(DATA_DIR|DB_PATH)=' .env                     # ⑤ DB_PATH 指向自己的拷贝（绝对路径）；DATA_DIR 仍是主干共享
git log --oneline -1 main                                    # ⑥ 主干有新提交吗（有就先 rebase）
# 后端起来后：lsof -p <后端PID> | grep echo.db                # ⑦ 确认进程连的是拷贝，不是主干的库
```

**收尾**

- [ ] 分支在自己 worktree 里 `verify.sh` 全绿
- [ ] `git rebase main` → 解冲突 → **重跑 verify**
- [ ] 主干 `merge` → **主干再跑一次 verify** → push
- [ ] 停掉该 worktree 的后端 + 前端进程（含工具后台任务）→ `lsof` 确认端口释放
- [ ] 需要就留档验证库（§6.3）
- [ ] `git worktree remove` + `git branch -d` + `git worktree list` 只剩主干
- [ ] 主干 `git pull --ff-only`；lock 变了才 `npm ci`
- [ ] 主干起服务 → 日志两行（`echo 后端启动完成`、`schema_guard: 结构自检通过`）+ health 三项

---

## 8. 真实翻车记录（别再犯）

| 事故 | 根因 | 现在怎么避免 |
|---|---|---|
| 一个会话清理缓存期间，另一个会话的 `data/r172-*.png` 被删掉 | 两个 agent 共享同一个工作树 | §2 worktree 隔离 |
| 对面半成品的 `use-card-tasks.test.ts` 被 `git add -A` 暂存，`verify.sh` 被卡红 | 共享 index + `add -A` | §5.1 只 `git add <具体文件>` |
| 密钥清洗时 `git filter-branch` + `gc --prune=now` 跑在共享对象库上，还删了一个 `refs/codex/...` 检查点 ref（可能弄断对端的撤销链） | 共享 `.git` 的 refs 与对象库 | §5.3 并行时段不做 gc/改写历史/删 ref |
| 清理脚本误删 `videos/` 中"未被数据库引用"的原始视频（后从 `/Users/yeah/document/chenP` 恢复） | 拿**快照库**当权威名单，去删**共享目录**里的文件 | §4.3：库里查不到 ≠ 文件是垃圾；素材无备份兜底 |
