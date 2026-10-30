# R-149 下线「需求管理」网页（保留需求归档与 AI 查询工具）

- **日期**: 2026-09-12
- **状态**: ✅ 已完成（2026-09-12，M138；作者选定范围 A「正式下线网页」）
- **关联**: R-136（复盘正式下线的先例）、`App.vue`、`router.js`、`RequirementsView.vue`、`api/requirements.py`、`services/requirements_service.py`、`core/requirement_file.py`、AI 对话的 `list_requirements` 工具

## 原文（作者原话，未改动）
> 需求管理这个菜单不用了

## 依赖盘点（2026-09-12 查证）
- **前端**：只有两处引用 —— `App.vue` 菜单项、`router.js` 路由；没有其它页面链接进来。
- **后端**：`api/requirements.py` 4 条路由（`GET /api/requirements`、`GET /{rid}`、`POST /api/requirements`、`PATCH /{rid}`）
  + `services/requirements_service.py` + `core/requirement_file.py`。
- **AI 对话依赖它**：工具 `list_requirements` → `requirements_service.list_requirements()`（读归档，用户会用「上次那个需求是啥」这类提问）。
- **归档不能删**：`requirements/R-xxx.md` + `README.md` 是工作流事实源（AGENTS.md 强制、`verify.sh` 校验 README 存在、`backup.sh` 会快照）。
- **文档/测试**：`docs/API.md` 有 4 条 requirements 路由；测试只有 R-148 那条（断言 `RequirementsView.vue` 的布局契约）。

## 建议范围（等作者确认）
**A. 正式下线网页（推荐）**
1. 删前端：`App.vue` 菜单项、`router.js` 路由、`views/RequirementsView.vue`；
2. 删后端：`api/requirements.py` 整个 router + `main.py` 的注册 + `schemas/requirement.py`；
   删 `requirements_service` 的 `create_requirement` / `update_status` / `get_requirement`（新建与状态变更只服务该页）；
   删 `core/requirement_file.py` 的 `next_requirement_id` / `STATUSES`（只被创建接口用）—— 即 R-136 的「不留死代码」口径；
3. **保留**：`requirements/` 归档与 `README.md`、`parse_requirement_file`、`list_requirements`（AI 对话工具继续用），
   以及 R-148 的标题清洗与护栏（AI 读归档时同样受益）；
4. `docs/API.md` 删掉 4 条路由（路由数 127 → 123）、CHANGELOG 记录下线。

**B. 只摘菜单**（不建议）：页面与 4 条接口留在仓库里成为无法到达的死代码，正是 R-136 清理过的问题。

## 影响与须知
- 下线后**网页不能再登记/改状态**；新需求仍按 AGENTS.md 既定流程由 AI 直接写入 `requirements/R-xxx.md`（写入能力不受影响）。
- AI 对话「查需求归档」能力保留。
- 无数据库变更（需求数据一直在文件里，不在库中）。

## 验收结果（2026-09-12）
- 前端：`App.vue` 菜单项、`router.js` 路由、`views/RequirementsView.vue` 全部移除；构建通过（0 error）。
- 后端：删除 `api/requirements.py`（4 条路由）、`schemas/requirement.py`、`main.py` 的注册；
  `requirements_service` 只留 `list_requirements`（AI 工具用）；`requirement_file` 只留 H1 解析
  （删掉只服务「网页新建」的 `next_requirement_id` / `STATUSES` / `ID_RE` 及其用例）。
- 路由数 **127 → 123**，OpenAPI 实测 123、`docs/API.md` 同步，`check_doc_consistency.py` 一致。
- 保留：`requirements/` 归档 + README 索引、R-148 的标题清洗与「真实归档全量」护栏（AI 读归档同样受益）。
- 死代码检查：全仓 `grep RequirementsView|api/requirements|next_requirement_id` 无残留引用。

## 验收标准
1. 菜单与路由不再出现「需求管理」，`/requirements` 直接访问落到 404 页；
2. `docs/API.md` 路由数与 OpenAPI 实际一致（`verify.sh` 的文档一致性检查通过）；
3. AI 对话问「R-146 是什么需求」仍能正确回答（工具保留）；
4. 仓库无 requirements 页相关的死代码（`grep` 无残留引用）；
5. `scripts/verify.sh` 全绿。
