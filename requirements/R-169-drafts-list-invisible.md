# R-169 脚本工作台列表草稿不可见（Framer Motion 变体未传播）/ 重启服务

- **日期**: 2026-09-28
- **状态**: ✅ 已完成（2026-09-28，M158）
- **关联**: `frontend_v2/src/pages/drafts/index.tsx`；R-164（前端重设计）、R-167（草稿抽屉空白防御）

## 原文（作者原话，未改动）
> 重启项目
>
> 脚本工作台，每次刷新页面重新打开，里面的明明有2篇草稿，却看不到

## 根因与修复
**可复现**：`/api/drafts?limit=500` 正常返回 2 篇 `status=draft` 草稿（id 31、35），
tab 计数也显示「草稿 (2)」，但列表区看不到卡片。

- 无头浏览器实测：两张 `<article>` 卡片确实渲染在 DOM 里，但计算样式为
  `opacity: 0; transform: translateY(14px)`——即 Framer Motion 的 `itemVariants.initial`
  状态，且从未动画到 `animate`（父级 `listVariants` 的变体标签没能传播到草稿卡片）。
- 结构差异：草稿卡片被包在 `TabsContent`（Radix，激活时才挂载）→ 无 variants 的
  `motion.div layout` → `AnimatePresence` 多层之下；其余页面（主页/提示词/博主管理）的
  列表项是 section 的直接子节点，故正常。
- **修复**：给 `DraftTile` 的 `motion.article` 显式加 `initial="initial" animate="animate"`
  （不再依赖祖先变体传播），卡片正常显示（实测 opacity 1 / transform none）。

## 验收
- 无头浏览器断言：`/drafts` 两张草稿卡片 opacity=1、transform=none（修复前为 0）；
  主页/提示词/博主/人设页无隐藏大块（0）。
- `scripts/verify.sh` 全绿；后端(8000)/前端(3000) 保持运行。

## 排期
M158
