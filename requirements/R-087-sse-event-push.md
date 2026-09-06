# R-087-SSE-EVENT-PUSH: SSE 事件推送（通知/任务进度/完成）

- **日期**: 2026-09-06
- **提出渠道**: 对话（架构咨询后确认）
- **原文摘要**: 按“SSE 事件推送”方向做一版
- **状态**: ✅ 已完成（一期：notification.new + task.update）
- **排期**: M69（已完成）
- **关联**: backend/app/services/events.py、api/events.py（GET /api/events）、tasks.py 发布、NotificationBell、VideosView、lib/sse.js + eventbus.js

## 设计
- 单进程内存事件总线（asyncio.Queue 按连接订阅）；后台任务在 daemon 线程用 `loop.call_soon_threadsafe` 投递。
- `GET /api/events`：SSE（text/event-stream，15s 心跳），前端用 fetch + ReadableStream 带 `X-Access-Token` 连接（同 AI 对话流式方式），断线 5s 自动重连。
- 一期发布两类事件：
  - `task.update`：后台任务每次进度/note 更新、完成、失败（id/status/progress/note/error）
  - `notification.new`：任何新通知写入（含同步完成、转写完成等）
- 前端：NotificationBell 收到 notification.new 立即刷新（原 5s 轮询降为 15s 兜底）；VideosView 收到 task.update 立即更新卡片覆盖层进度/文字，完成即结束（原 1.5s 轮询降为 5s 兜底），并保留 R-081 的 6s 任务扫描兜底。
- 采用 SSE 而非 WebSocket：单向服务端推送即可，HTTP 长连接 + 自动重连，无双向需求。

## 自测
- verify.sh 全绿；events 模块单进程收发冒烟；/api/events 长连接心跳冒烟（curl）。

## 原文（作者原话，未改动）
> 按“SSE 事件推送”方向做一版
