# R-116 对标页进行中状态切页保留

- **日期**: 2026-09-07
- **状态**: ✅ 已完成
- **排期**: M99（已完成，线上 bug 修复）
- **原文**: 博主对标【AI分析】点击切换页面回来动画就消失了，都不知道是不是在跑；包括点了洗稿按钮，切回来动画也没了。

## 根因
「AI分析 / 洗稿 / 转写补齐」都是同步 HTTP 请求，loading 状态放在组件本地 ref 里；切到别的路由组件卸载，返回时重建，进行中状态与结果丢失。

## 修复
- BenchmarkView 的 `preparingId / analyzingKey / rewritingKey / analysisMap` 改为模块级 `reactive` 共享状态（`ui`），不随组件卸载销毁。
- `load()` 只合并服务端已保存的 AI分析结果，不清空进行中状态。
- 请求完成后的 `finally` 仍写共享状态，切页返回后新组件实例立即读到同一状态 → 动画/结果接着显示。

## 验收
- 点击「AI分析 / 洗稿 / 转写补齐」后切走再回来，按钮仍在 loading；完成后结果/弹窗正常。
- `scripts/verify.sh` 全绿。

## 补充（后端留痕，真正可靠）
- 前述「模块级 reactive」并不跨组件实例（在 `<script setup>` 内，每次挂载重建），且刷新页面必丢。
- 改为后端留痕：`POST /api/benchmark/analyze`、`POST /api/benchmark/rewrite` 落后台任务（kind=benchmark_analyze / benchmark_rewrite），返回 task_id；结果写入 background_tasks.result（新增列）。
- 前端轮询 `/api/tasks/{id}`；切页回来 `resumeRunning()` 按 `status=running` 找回进行中任务，恢复按钮 loading 并继续轮询；完成后回填结果/弹窗。
- 迁移 `_migrate_task_result` 为 background_tasks 增列 result；`start_task` 完成后把 result 序列化写入。
