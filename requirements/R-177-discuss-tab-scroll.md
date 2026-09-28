# R-177 脚本工作台「讨论」tab 滚动不了

- **日期**: 2026-09-28
- **状态**: ✅ 已完成（2026-09-28，M166）
- **关联**: `frontend_v2/src/components/ui/scroll-area.tsx`、`frontend_v2/src/pages/drafts/edit-drawer.tsx`；R-173（讨论 tab 状态条）、R-165（抽屉滚不到底）

## 原文（作者原话，未改动）
> 1.脚本工作室 讨论tab页 滚动不了

## 根因（浏览器实测，不是猜的）
讨论 tab 的留痕列表包在 `<ScrollArea className="max-h-[52vh]">` 里，而 Radix ScrollArea 的结构是
`Root(overflow:hidden)` + `Viewport(overflow:scroll, h-full)`。**只给 Root `max-h`、没给显式 `height`** 时：

- Root 的 `height` 仍是 `auto`，百分比高度对它解析为 `auto` → Viewport 的 `h-full` 失效，高度 = 内容高度；
- 于是 Viewport 自己 `clientHeight == scrollHeight`（实测草稿 #38：**4215 / 4215**）→ 没有可滚动的余量；
- 真正的高只有 Root 的 `max-height: 468px`（52vh），而 Root 是 `overflow:hidden` → 超出的 3747px 内容**直接被裁掉**，
  既没有滚动条、滚轮也无效（实测 `scrollTop` 恒为 0）。

结论：能滚的场景（`h-72` / `flex-1` 这类**显式高度**）一直正常，只有「仅 max-h 约束」的写法全坏。

## 修复
`scroll-area.tsx` 的 Viewport 加 `max-h-[inherit]`：继承 Root 的高度上限，让 Viewport 在「只有 max-h」时也能定高成为滚动容器
（调用方仍只给 `max-h-*`，短列表不会被撑成固定高、不留空白）。**一处修复，同源场景一并修好**：
`multi-select`（标签多选 `max-h-64`）、`notification-bell`（`max-h-[60vh]`）、`prompts`（`max-h-72` / `max-h-56`）。

## 验收
- 草稿 #38 讨论 tab 实测（改后）：Viewport `clientHeight 468 / scrollHeight 4215` → 可滚；
  真实滚轮 `0 → 600 → 1200`，滚到底 `scrollTop 3747 = max`，最后一条留痕可见（改前恒为 0）。
- 同源场景实测：素材库「标签」多选下拉 Viewport `256 / 12960`、`scrollTop 0 → 300` 可滚，下拉样式正常。
- 新增 `frontend_v2/src/components/ui/scroll-area.test.tsx` 锁定「Viewport 必须继承 Root 的 max-height」。
- 动效：本次为布局修复，不新增/不改动动画（不涉及切换类动画，无闪帧风险）。
- `scripts/verify.sh` 全绿；后端(8000)/前端(3000) 保持运行。

## 排期
M166
