# R-178 讨论留痕要显示并记录「真实模型 + 版本」，不要只写模型1/模型2

- **日期**: 2026-09-28
- **状态**: ✅ 已完成（2026-09-28，M167）
- **关联**: `frontend_v2/src/pages/drafts/edit-drawer.tsx`、`frontend_v2/src/pages/drafts/draft-ai-status.tsx`、`frontend_v2/src/pages/drafts/types.ts`、`backend/app/services/debate.py`、`backend/app/models/discussion.py`、`docs/DATABASE.md`；R-023（双模型讨论）、R-139（模型双槽位/降级）、R-142（留痕要记实际出结果的模型）、R-173（状态条）

## 原文（作者原话，未改动）
> 2.讨论的模型不要展示成model1、model2，展示成对应的模型和版本，并且要记录下来，不然我切模型了，都不知道之前用的什么模型

## 现状盘点（已核对代码与库里数据）
| 位置 | 现在显示 | 数据来源 |
|---|---|---|
| 讨论 tab 留痕每条的表头 | `model1 修订 · 第3轮` / `model2 评审 · 第1轮` | `draft_discussions.actor`（存的就是槽位名 `model1`/`model2`） |
| 讨论 tab 顶部状态条（R-173） | `model1 正在评审第 1/3 轮…` | 后端 `_status()` 文案里直接拼槽位名 → `app_kv` 状态 |
| 草稿卡片状态条 | `{模型} {阶段} 第 x/y 轮` | 同上（同样是 `model1`/`model2`） |
| 编辑 tab「本篇生成模型：…」 | **实际不显示**（死代码） | 前端读 `quality.gen_model/referee_model`，后端从未写这两个 key |

- 库里 `Draft.quality` 其实**有**真实模型信息：`models/used = "model1(deepseek/deepseek-flash)"` 这种「槽位(厂家/模型)」，
  但只在**最后一次**讨论时整块覆盖写一次，而且草稿 37/38 现在已是 `{}`（后续操作被重置）→ 「切模型后不知道之前用的什么」正是这个原因。
- `draft_discussions` 表只有 `actor/kind/round/content`，**没有**任何厂家/模型字段 → 历史留痕无法反推当时用的是哪个模型。

## 反问（待作者确认，按 WORKFLOW 反问清单）
1. **范围**：上面 4 处都要改成「真实模型 + 版本」吗？（推荐：**都改**，含编辑 tab 那条死代码一起修活）
2. **展示格式**：推荐 `DeepSeek · deepseek-flash`（厂家 · 模型 ID，与「AI 设置 → 模型设置」的分隔风格一致）；
   备选 `deepseek-flash（DeepSeek）`、`DeepSeek deepseek-flash`、只显示模型 ID。
3. **记哪一个**：记录**实际出结果**的模型（内部降级/兜底换过槽位时以事实为准，与 R-142 一致）——
   还是记录「当时配置的生成方/评审方」，还是两者都记？
4. **历史数据**：已有留痕（库里 22 篇草稿、上百条消息）只有 `model1/model2`，无法反推当时模型。怎么显示？
   推荐：`未记录模型（历史留痕）`；备选：保留 `model1/model2` 原样、或按当前配置反推（**会误导，不推荐**）。
5. **两个模型要不要一起显示**：讨论 tab 顶部是否加一行「本次讨论：生成方 XX × 评审方 YY」，
   这样不用逐条看留痕就知道这篇是哪两个模型讨论的？
6. **动效（R-175 必问）**：新增的模型标签/顶部这行是否要动效？

## 确认结论（作者 2026-09-28 逐项选择，均为推荐项）
1. **范围**：四处全改（①留痕表头 ②讨论 tab 状态条 ③草稿卡片状态条 ④编辑 tab「本篇生成模型」）+ 讨论 tab 顶部加「本次讨论：生成方 XX × 评审方 YY」；第④处顺手把读错 key 的死代码修活。
2. **格式**：`DeepSeek · deepseek-flash`（厂家 `vendor_label` · 模型 ID）。
3. **记录口径**：记**实际出结果**的模型（`RoutedLLM.used_slot/used_vendor/used_model`），另存**当时配置的两个槽位**备查。
4. **历史留痕**：显示`未记录模型（历史）`，不按当前配置反推。
5. **顶部摘要**：加，且保留**每一次**讨论的配置（切模型后仍能看到历史那次用的是谁）。
6. **动效**：模型标签淡入 `0.85 → 1`（不从 0 起步，R-175），状态条沿用现有三点跳动，不加多余动画。

## 实施计划（M167，待作者说「继续」后开工）
**后端**
1. `models/discussion.py` + `db.py`：`draft_discussions` 加 3 列——`used_slot`(实际槽位)、`vendor`(厂家 id)、`model_id`(模型 ID/版本)；
   按 AGENTS 手写幂等 `_migrate_draft_discussions_model_fields`（`create_all` 不给已有表补列），同步 `docs/DATABASE.md`。
2. `debate.py`：
   - 新增 `_model_label(vendor, model)`（复用 `model_settings.VENDORS[*]["label"]`，产出 `DeepSeek · deepseek-flash`）；
   - `_add(...)` 增传入实际模型三元组，写库时落 `used_slot/vendor/model_id`；
   - 每次讨论开头写一条 `kind='run'` 的**运行头**（JSON：配置的生成方/评审方 + 轮次），结束时回填 `rounds_done/degraded` → 「另存配置备查」+ 顶部摘要的数据源；
   - `_status()` 文案由槽位名改真实模型（`DeepSeek · deepseek-flash 正在评审第 1/3 轮…`）→ 卡片与讨论 tab 状态条同时生效；
   - `run_debate` 与 `run_rewrite_debate`（洗稿）两条路径都覆盖。
3. `api/drafts.py` `GET /{id}/discussions`：返回 `used_slot/vendor/model_id` + 服务端算好的 `model_label`；同步 `docs/API.md`。
**前端（frontend_v2）**
4. `types.ts`：`Discussion` 补字段 + `roleLabel/kindLabel` 与 `未记录模型（历史）` 兜底；纯函数便于单测。
5. `edit-drawer.tsx`：留痕表头改「生成方 DeepSeek · deepseek-flash · 修订 · 第3轮」；顶部「本次讨论」摘要卡；`kind='run'` 行渲染成历史分隔行；编辑 tab「本篇生成模型」优先用最近一次运行头（quality 兜底）→ 死代码修活。
6. 动效：模型标签 `opacity 0.85 → 1` 淡入（`lib/motion.ts` 令牌），收口到 `1/none`。
**测试与自测**
7. 后端 pytest：`_model_label`、`_add` 落库实际模型、迁移幂等；前端 vitest：表头/历史兜底渲染（`未记录模型（历史）`）。
8. 真实冒烟：在临时草稿上跑一次**最短讨论**（跑完逻辑删除该草稿），确认留痕/状态条/摘要显示 `DeepSeek · deepseek-flash`、切模型后旧留痕不变；rAF 点检淡入无空白首帧（R-175）；`scripts/verify.sh` 全绿；服务保持运行。

## 非目标
- 不改模型调用链路（生成方/评审方解析、降级顺序）本身。
- 不为历史留痕伪造模型信息。
- 本次不动「AI 对话」里的模型展示（那是另一个页面，如需要另开需求）。

## 交付与自测（2026-09-28 完成）
- **落库**：`draft_discussions` 新增 `used_slot/vendor/model_id` 三列（幂等迁移 `_migrate_discussion_model_fields`，已在实时库应用）；
  每次讨论写 `kind='run'` 运行头（配置的生成方/评审方 + 轮次），结束回填 `rounds_done/degraded`。
- **显示**：留痕表头「生成方 [DeepSeek · deepseek-flash] 初稿 · 第0轮」、讨论 tab 顶部「本次讨论：生成方 X × 评审方 Y · 讨论 n/N 轮」、
  状态条「Kimi（月之暗面） · kimi-k2.6 正在评审第 1/1 轮…」、编辑 tab「本篇生成模型」；老留痕「未记录模型（历史）」。
- **真机冒烟**：临时草稿（#40）跑 1 轮真实双模型讨论 → 6 条留痕全带真实模型、运行头 1/1 轮；跑完 `debate_rounds` 已还原为 3。
- **测试**：`pytest tests/test_r178_discussion_models.py` 5 passed；`vitest discussion-model.test.ts` 6 passed；
  浏览器点检无控制台报错；`scripts/verify.sh` 全绿。

## 排期
M167（已完成）

