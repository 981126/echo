# R-173 草稿卡片讨论中动画 / 抽屉讨论状态条 / 卡片动画重放 / 讨论结束判定

- **日期**: 2026-09-28
- **状态**: ✅ 已完成（2026-09-28，M162）
- **关联**: `frontend_v2/src/pages/drafts/index.tsx`、`frontend_v2/src/pages/drafts/edit-drawer.tsx`、
  `backend/app/services/debate.py`、`backend/app/api/drafts.py`、`backend/app/services/draft_flow.py`、`backend/app/tasks.py`；
  R-118（洗稿多轮讨论）、R-134（讨论进度/失败清状态）、R-155（基于原文讨论）、R-169/R-171（同类 remount bug）

## 原文（作者原话，未改动）
> 1.草稿点开抽屉后，草稿卡片为什么会重新触发动画
> 2.如果草稿卡片正在进行多模型讨论，草稿卡片应该给出动画
> 3.我在素材库点击洗稿后，草稿卡片为什么只讨论了一轮
> 4.如果草稿正在进行讨论，讨论的tab页，正在思考的模型需要讨论的动画，不然不知道是不是讨论结束了

## 现状排查（实测证据，2026-09-28）
1. **卡片动画重放**：`DraftTile` 与 `Actions` 定义在 `DraftsPage` 函数体内 → 每次 re-render 都是新组件类型
   → React 卸载重建整棵卡片子树 → `initial/animate` 重放。无头探针：点开抽屉后原 `<article>` 节点消失
   （`sameNodes=0`），opacity `0.72→0.93→0.99` 重播。与 R-171 `CreatorBlock` 同根因。
2. **卡片没有讨论中状态**：进度只写 `app_kv['debate:{draft_id}']`，卡片与列表完全不知道。
3. **「只讨论了一轮」= 显示滞后，不是真只跑一轮**：作者 17:57 从素材库发起的洗稿（task 3253）当时仍在跑，
   `debate:37 = "MODEL1 正在按评审修订第 3/3 轮…"`，留痕已有第 0/1/2/3 轮（`debate_rounds=3`）。
   但抽屉只在「**自己**在抽屉里点过【讨论】」（`discussing=true`）时才轮询；从素材库发起时抽屉打开只拉一次快照
   → 停在当时那一轮，看起来像"只讨论了一轮"。
4. **讨论结束判定失效（真 bug）**：`GET /api/drafts/{id}/debate-status` 只返回 Kv 里的长文案或 `null`，
   **从不返回 `done`/`idle`/`failed`**，而前端正是等这三个值收尾 → 轮询永不停止、不提示「讨论完成」、
   正文不刷新。另外洗稿路径（`benchmark_rewrite`）失败/服务重启中断时不会清理 `debate:{id}`（只有
   `draft_discuss` 路径清了）→ 动画会永久转圈。

## 反问与确认（2026-09-28）
1. **动画覆盖范围** → 作者选：**讨论 + 其它 AI 长任务（回炉、AI 生成草稿）都要在草稿卡片上给动画**。
2. **失败/中断表现** → 作者选：**不转圈 + 标记「上次讨论中断（可重新讨论）」**（不自动重跑，避免重复花钱）。
3. **抽屉「正在思考」形式** → 作者选：**顶部状态条：模型名 + 三点跳动 + 第 x/y 轮**。
4. 其他约定（AI 自行收敛，待作者确认）：轮询只在「确实有任务在跑」时进行（3s）；无新增 LLM 调用；
   不新增表/字段（状态继续放 `app_kv`，键由 `debate:{id}` 泛化为 `draft_ai:{id}`）。

## 实施计划（已实施）
- **后端**
  1. `debate.py`：`_status` 改写 JSON `{state,kind,note,actor,phase,round,rounds,at}`（键 `draft_ai:{id}`）；
     跑完 `_clear_status`；异常 → `mark_failed(reason)`；兼容读取旧 `debate:{id}` 并在启动时清理。
  2. `api/drafts.py`：`/debate-status` **新增** `state: 'running'|'failed'|null` + `note/actor/phase/round/rounds`，
     原 `status`（人类可读文案，老前端 `DraftsView.vue` 只读它做展示）语义**保持不变**；
     `GET /api/drafts` 列表每条附带 `debate` 状态（单次查询，无 N+1）。
  3. `_rework_task` / `start_rework` / `start_generation` / `start_discussion`：统一写同一状态键（kind=rework/generate/discuss/debate）。
  4. `tasks.py` 启动自愈：残留 `running` → `failed`（「服务重启，任务中断」）。
- **前端**
  5. `drafts/index.tsx`：`Actions`/`DraftTile` 提到模块作用域（纯 props + handlers），修掉动画重放；
     卡片显示「{模型} {阶段} 第 x/y 轮」跳动条 / 「上次讨论中断」标记；列表仅在有人跑任务时 3s 轮询。
  6. `drafts/edit-drawer.tsx`：打开即读 `/debate-status`，他人发起的讨论也能显示状态条并轮询；
     以 `state != running` 收尾（null=完成：停止轮询 + 「讨论完成，正文已更新」+ 刷新正文；failed=中断提示）。

## 验收（实测）
- **无头探针（/drafts，1440 视口）**：
  ① 点开抽屉后卡片 DOM **未重建**（`sameNodes=1/1`）、opacity 恒 `1.000`（修复前 `0` + 重播 0.72→0.99）；
  ② mock `debate.state=running` → 卡片状态条「洗稿讨论 MODEL1 正在按评审修订第 2/3 轮…（第 2/3 轮）」+ 三点跳动；
     mock `failed` → 「上次讨论中断 洗稿中断：timeout，可【重新讨论】」且无跳动点；
     轮询实测：running 时 7s 内 2 次（≈3s），failed 时 **0 次**（不再打扰后端）；
  ③ 抽屉讨论 tab 顶部状态条随轮次推进（第 1/3 → 第 3/3）→ 结束时消失 + toast「讨论完成，正文已更新」
     + 留痕补齐（1→5 条）+ 结束**后 0 次轮询**（修复前判定条件永不成立、永远轮询且不提示）；
  ④ `state=failed` 时打开抽屉 → 显示中断条 + 【重新讨论】按钮。
- **单测**：`backend/tests/test_r173_draft_ai_status.py` 9 例（状态往返/新键优先/旧键兼容/启动自愈/列表字段/接口形状/
  跑满清状态/中途失败留标记 + quality.rounds_done=1）；`frontend_v2/src/pages/drafts/draft-ai-status.test.tsx` 3 例。
  后端全量 `pytest` **382 passed**；`scripts/verify.sh` 全绿（其中 docs 一致：30 表 / 129 路由）。
- 真实链路：作者 17:57 那次素材库洗稿（task 3253）实测跑满 3 轮（18:08:20 完成）——「只讨论了一轮」确认为显示滞后。
- 服务保持运行：后端 8000（重启加载新代码，`/health` 200）、前端 3000。

## 排期
M162
