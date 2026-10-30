# R-224 草稿 AI 生成标题/封面字/素材标签

- **日期**: 2026-10-13
- **状态**: ✅ 已完成（M206）
- **关联**: `frontend_v2/src/pages/drafts/edit-drawer.tsx`、`frontend_v2/src/pages/drafts/index.tsx`；`backend/app/services/draft_meta_suggest.py`、`backend/app/api/drafts.py`；R-212（实时保存）、R-138/R-139（模型1 与统一路由）、R-173/R-202（后台任务与状态恢复）

## 原文（作者原话，未改动）
> 脚本工作台里的草稿，我需要一个生成视频标题/封面字/素材标签的功能

## 反问与确认结论（2026-10-13）
1. **入口**：在草稿编辑抽屉「提词器」按钮左侧新增「AI标题」按钮。
2. **输入**：当前草稿的 `script` 正文。
3. **参考人设**：调用时把当前用户的全部 `PersonaTag`（标签+描述）作为上下文喂给模型。
4. **输出形式**：生成候选列表。
   - 标题、封面字：改为**可输入下拉框**（Combobox），可手动输入也可下拉选择。
   - 素材标签：改为**可输入多选下拉框**。
   - 默认展示/选中当前已有值作为第一候选；素材标签默认勾选候选前 5 个（不足则全选）。
5. **追加生成**：一个按钮，多次点击追加候选；新增结果按 `Set` 精确去重（字符串完全相等即去重）。
6. **模型**：使用 AI 设置中的**模型1**。
7. **数量**：每次生成标题、封面字、素材标签各 5 条。
8. **状态**：按钮点击后转圈；刷新页面后若生成未结束，继续展示转圈（后台任务 + localStorage 恢复任务 ID）。
9. **错误**：生成失败时在按钮左侧通过 `toast.error` 提示，保留已有候选。
10. **风格**：参考人设，但更要考虑吸睛爆款。
11. **保存**：新建/已有草稿都改为实时保存；抽屉内任何字段改动都自动落库。

## 做法

### 后端
- 新增 `backend/app/services/draft_meta_suggest.py`：
  - `suggest_meta_task(db, payload)`：按 `draft_id` 读取草稿正文，聚合当前用户全部 `PersonaTag` 作为人设上下文。
  - 调用 `llm_router.primary_llm('draft_meta', ...).chat_json(...)`，要求模型输出 JSON 契约 `{titles: list[str], cover_texts: list[str], tags: list[str]}`，每个数组 5 条。
  - Prompt 强调：参考人设但优先吸睛爆款；封面字口语化、有冲击；标签覆盖场景/情绪/卖点。
- `backend/app/api/drafts.py`：新增 `POST /api/drafts/{draft_id}/suggest-meta`，启动 `start_task("draft_suggest_meta", {"draft_id": ...}, suggest_meta_task)`，返回 `{task_id}`。
- `backend/app/core/task_meta.py`：`KIND_LABELS` 新增 `"draft_suggest_meta": "生成标题封面标签"`，`target()` 返回 `/drafts?id={draft_id}`。
- `backend/app/services/llm_router.py`：`FEATURE_LABELS` 新增 `"draft_meta": "标题封面标签生成"`。

### 前端
- 新增 `frontend_v2/src/components/ui/creatable-select.tsx`：单选可输入下拉框。
- 新增 `frontend_v2/src/components/ui/creatable-multi-select.tsx`：基于现有 `MultiSelect` 扩展可输入新增标签。
- `frontend_v2/src/pages/drafts/edit-drawer.tsx`：
  - 新增状态 `titleOptions`、`coverTextOptions`、`tagOptions`、`suggesting`、`suggestTaskId`。
  - 初始化时用 `draft.title / draft.cover_text / draft.tags` 填充候选并默认选中/勾选。
  - 抽屉打开时从 `localStorage` 读取 `draft_suggest_meta:${draftId}` 恢复任务并轮询 `/api/tasks/{task_id}`。
  - 在「提词器」按钮左侧插入「AI标题」按钮，生成中时转圈禁用。
  - 将标题、封面字、素材标签输入替换为新 Combobox / MultiSelect。
  - 下拉/输入变化触发实时保存。
- `frontend_v2/src/pages/drafts/index.tsx`：把实时保存从「仅新建草稿」扩展到所有草稿；【保存】按钮语义改为 flush，【取消】按钮改为关闭抽屉。

### 状态流转
```
点击 AI标题
  → POST /api/drafts/{id}/suggest-meta
  → localStorage.setItem(`draft_suggest_meta:${id}`, taskId)
  → 轮询 /api/tasks/{taskId}
  → done: 解析 result → Set 追加候选 → 默认选中/勾选 → 清除 localStorage
  → failed: toast.error(error) → 清除 localStorage → 保留已有候选
```

## 排期
M206

## 验收
- [x] 提词器按钮左侧有「AI标题」按钮，生成中时转圈并禁用。
- [x] 标题、封面字为可输入下拉框，默认选中当前值作为第一候选。
- [x] 素材标签为可输入多选下拉框，默认勾选候选前 5 个（不足全选）。
- [x] 每次生成标题、封面字、素材标签各 5 条；多次生成追加且按 `Set` 去重。
- [x] 刷新页面后，若生成未结束仍展示转圈，完成后自动填充候选。
- [x] 生成失败时 `toast.error` 提示，已有候选保留。
- [x] 新建/已有草稿的所有抽屉字段均实时保存。
- [x] 风格参考人设且优先吸睛爆款。
- [x] `scripts/verify.sh` 全绿。

## 待收口文档改动
- `docs/API.md`：新增 `POST /api/drafts/{draft_id}/suggest-meta` 接口说明。
