# R-204 tab 切换选中态过渡动画（滑块）

- **日期**: 2026-09-29
- **状态**: ✅ 已完成（M194）
- **关联**: `frontend_v2/src/components/ui/tabs.tsx`；R-174/R-175/R-203

## 原文（作者原话，未改动）
> tab页签切换，选中的tab页没有过度动画

## 反问与确认结论
- **范围**：全站 `Tabs`（`ui/tabs.tsx` 统一）——选中态的白色高亮由「瞬间换背景色」改为**共享 layout 的滑块在 tab 间平滑移动**；文案颜色过渡保留；不动 tab 内容/接口。
- **边界**：受控/非受控 Tabs 都要支持；页面上多个 Tabs 实例的滑块不能串（`layoutId` 用 `useId` 唯一）。
- **验收**：切换时滑块从旧 tab 平滑移到新 tab，最终与选中项对齐、且始终只有一个滑块；无 JS 报错。
- **动效（R-175）**：spring（stiffness 420 / damping 34），不用透明度闪烁。

## 做法
- `tabs.tsx`：新增 `TabsCtx`（记录当前 value + 每个 Tabs 实例的 useId）；`Tabs` 包一层同时兼容受控/非受控并维护内部值；`TabsTrigger` 在选中时渲染 `motion.span layoutId="tab-pill-{id}"` 作为滑块（`absolute inset-0 rounded-md bg-card shadow-sm`），文案用 `z-[1]` 浮在上层；去掉 trigger 上的 `data-[state=active]:bg-card/shadow-sm`（改由滑块承担）。

## 排期
M194

## 验收
- [x] `npm run build` + vitest（tabs 4 例）通过
- [x] headless：10 tab 切换，滑块 x 280→(动画中 345)→457 与选中项对齐、仅 1 个滑块、零 console 报错
- [x] `scripts/verify.sh` 全绿
