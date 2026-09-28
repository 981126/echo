# R-176 AI 对话一发消息就报「Input should be a valid dictionary or object to extract fields from」

- **日期**: 2026-09-28
- **状态**: ✅ 已完成（2026-09-28，M165）
- **关联**: `frontend_v2/src/pages/chat/index.tsx`、`frontend_v2/src/api/client.ts`；R-164（新前端重写）、R-167（同一功能的错误文案修复）

## 原文（作者原话，未改动）
> 1.现在ai对话 进行对话就报错出错了：Input should be a valid dictionary or object to extract fields from

## 根因
- 报错来自 `POST /api/chat/stream` 的 **422** 请求体校验，不是模型/接口本身出错（同一接口带正确头请求 200 正常流式返回）。
- 新前端（R-164 重写）的发送逻辑用裸 `apiFetch` 发字符串 body，**漏了 `Content-Type: application/json`**；
  `fetch` 对字符串 body 默认 `text/plain;charset=UTF-8`，FastAPI 拿不到 JSON body，
  于是把整串文本当 body 交给 Pydantic → `model_attributes_type`：
  `Input should be a valid dictionary or object to extract fields from`（前端把它当错误消息显示在气泡里）。
- 老前端 `frontend/src/views/ChatView.vue` 一直显式带 `Content-Type: application/json`，所以是重写时引入的回归。
- 复现（改前）：`POST /api/chat/stream` + `Content-Type: text/plain` → `422` + 上述 msg；`Content-Type: application/json` → `200` 流式正常。

## 修复
1. `frontend_v2/src/pages/chat/index.tsx`：SSE 请求显式声明 `headers: { 'Content-Type': 'application/json' }`（与老前端契约一致）。
2. `frontend_v2/src/api/client.ts`（兜底，防同类复发）：`apiFetch` 在 **body 是字符串且调用方未指定 Content-Type** 时
   自动补 `application/json`；调用方显式指定的头不覆盖，`FormData` 不动（浏览器自带 boundary）。
3. `frontend_v2/src/api/client.test.ts`：新增 3 条断言（字符串 body 兜底 JSON / 显式头不被覆盖 / FormData 不设头）。

## 验收
- 单测：`vitest run src/api/client.test.ts` 6 passed（含新增 3 条）。
- 端到端：Playwright 无头浏览器走真实链路（登录令牌 → 对话页 → 输入并发送）——
  请求 `POST /api/chat/stream` 返回 **200**，气泡正常流式输出，无「出错了」；修复前该请求为 **422**。
- `scripts/verify.sh` 全绿；后端(8000)/前端(3000) 保持运行。

## 排期
M165
