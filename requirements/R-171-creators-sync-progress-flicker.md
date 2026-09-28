# R-171 博主管理同步进度条闪烁（内嵌组件导致卡片 remount）

- **日期**: 2026-09-28
- **状态**: ✅ 已完成（2026-09-28，M160）
- **关联**: `frontend_v2/src/pages/creators/index.tsx`；R-162（同步所有博主前15条）、R-163（并发消费者）

## 原文（作者原话，未改动）
> 博主管理点击同步后，进度条会消失又出现，很奇怪

## 根因与修复
- 无头浏览器实测（mock `/api/platform/jobs` 返回**递增**进度的 running 任务）：
  进度条 `<div>` 与其所在账号行的 DOM 节点在每次 jobs 数据变化时被**替换**（tag 探针判定 `barSame/rowSame=false`），
  即整块 `CreatorBlock` 子树被 **remount**。
- 根因：`CreatorBlock` 定义在 `CreatorsPage()` **函数体内部**，每次渲染都是新的组件类型 →
  React 视作不同组件而卸载重建；`SyncProgressBar` 的 `initial={{opacity:0,height:0}}` 进入动画随之每次重放，
  视觉上就是「消失又出现」。jobs 轮询（4s）+ SSE `sync.job` 失效会不断触发重渲染，于是反复闪烁。
- **修复**：把 `CreatorBlock` 提升到模块作用域（`React.memo` 无需），改为纯 props（`job/running/syncingAll/hasBenchmarks/h`），
  回调统一放进 `handlers`；组件类型稳定后卡片不再 remount。

## 验收
- 无头实测（递增进度 mock）：修复后 `barSame/rowSame` 持续 `true`（修复前进度一变即为 `false`）；
  其它页面不受影响。
- `scripts/verify.sh` 全绿（ruff/mypy/pytest/vitest/eslint/tsc+构建/文档一致性）；后端(8000)/前端(3000) 保持运行。

## 排期
M160
