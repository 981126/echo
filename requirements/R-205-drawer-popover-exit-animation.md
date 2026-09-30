# R-205 抽屉 / 移动端导航 / 通知弹层退出动画

- **日期**: 2026-09-29
- **状态**: ✅ 已完成（M195）
- **关联**: `frontend_v2/src/components/ui/drawer.tsx`、`components/layout/app-shell.tsx`、`notification-bell.tsx`、`active-work-indicator.tsx`、`ui/dropdown-menu.tsx`、`ui/select.tsx`、`ui/multi-select.tsx`；R-164/R-174/R-175

## 原文（作者原话，未改动）
> 现在抽屉没有退出动画，通知展开后退出也没有动画

## 根因（无头实测）
1. **抽屉**：消费方 `videos/edit-drawer.tsx`、`drafts/edit-drawer.tsx` 里有 `if (!open) return null` —— 关闭时**父组件先把整个 `Drawer` 卸载了**，抽屉内部的退场动画根本没机会播（`[role="dialog"]` 在关闭后 ~80ms 直接消失、x 不动）。
2. **抽屉组件本身**：退场依赖 framer `AnimatePresence`；本项目 React 19 + framer-motion v12 下 **AnimatePresence 的 exit 不生效**（移动端导航同样退不掉）。
3. **通知弹层**：Radix Popover 只有 `data-[state=open]:animate-in`，**缺 `data-[state=closed]:animate-out`** 退出类。

## 做法
- `Drawer`：去掉对 `AnimatePresence` 的依赖，改为**受控 animate + 延迟卸载**——关闭后先保持挂载、把 `animate` 切到关闭态，`window.setTimeout(340ms)` 再卸载；遮罩渐隐、面板弹簧右移。
- `AppShell` 移动端抽屉导航：同样改「受控 animate + 延迟卸载」。
- 两个 `edit-drawer`：删掉 `if (!open) return null`（由 `<Drawer>` 自己管生命周期；内部 effect 本就有 `if (!open) return` 守卫，不会多请求）。
- 通知弹层 + 全局「进行中」弹层 + 下拉/选择/多选：补 `data-[state=closed]:animate-out fade-out-0 zoom-out-95`（通知另加 `slide-out-to-top-2`）。

## 排期
M195

## 验收
- [x] headless 实测退场逐帧：抽屉面板 `x 760→941→1151→1427`（右滑出屏，~450ms）后卸载；移动端导航 `x 0→-147→-251→-276` 后卸载；通知弹层 `opacity 1→0.65→0.15→0.01→卸载`（`data-state=closed`、`animationName=exit`）
- [x] `npm run build` + vitest（52 例）通过；零 JS 报错
- [x] `scripts/verify.sh` 全绿
