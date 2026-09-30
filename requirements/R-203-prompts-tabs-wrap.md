# R-203 AI 设置 tab 太多一排放不下 → 换行

- **日期**: 2026-09-29
- **状态**: ✅ 已完成（M193）
- **关联**: `frontend_v2/src/pages/prompts/index.tsx`；R-138/R-202

## 原文（作者原话，未改动）
> ai设置功能里面的tab页太多了，一页都放不下了，换行

## 反问与确认结论
- **范围**：仅 AI 设置页顶部 tab 栏由「横向滚动」改为「自动换行」；不动 tab 内容/接口。
- **验收**：tab 栏 `flex-wrap` 多行展示、无横向溢出（`scrollWidth <= clientWidth`）；无 JS 报错。
- **动效（R-175）**：tab 切换入场动效不变（`ui/tabs.tsx` 统一）。

## 做法
- `prompts/index.tsx`：去掉包 `TabsList` 的 `ScrollArea`，给 `TabsList` 加 `h-auto w-full flex-wrap justify-start`。

## 排期
M193

## 验收
- [x] `npm run build` 通过；headless：10 个 tab 自动换 2 行、无横向溢出、零 console 报错
- [x] `scripts/verify.sh` 全绿
