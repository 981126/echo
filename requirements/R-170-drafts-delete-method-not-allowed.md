# R-170 脚本工作台删除草稿报 Method Not Allowed

- **日期**: 2026-09-28
- **状态**: ✅ 已完成（2026-09-28，M159）
- **关联**: `frontend_v2/src/pages/drafts/index.tsx`；R-158（删除二次确认）、R-169

## 原文（作者原话，未改动）
> 我点击删除脚本工作台的脚本报错 Method Not Allowed

## 根因与修复
- 后端**没有** `DELETE /api/drafts/{draft_id}` 路由（`docs/API.md` 亦未收录）；草稿删除按设计是
  **逻辑删除**（`status='deleted'`，页面上任何 tab 都不可见），老前端就是走
  `PATCH /api/drafts/{id}` body `{status:'deleted'}`（`frontend/src/views/DraftsView.vue`）。
- 新前端 `doDelete()` 误用 `DELETE` 方法 → FastAPI 返回 405 Method Not Allowed。
- **修复**：改用与老前端/后端契约一致的 `PATCH {status:'deleted'}`（`DraftUpdate.status` 白名单本就含 `deleted`）。

## 验收
- 无头浏览器实测：点删除 → 二次确认 → 请求 `PATCH /api/drafts/36` 返回 **200**，卡片消失、提示「已删除」；
  修复前该请求为 405。
- `scripts/verify.sh` 全绿；后端(8000)/前端(3000) 保持运行。

## 排期
M159
