# R-250 开发设计：脚本工作台删除草稿时其他卡片不再「飞出去」

- **对应需求**: `requirements/R-250-drafts-delete-animation.md`
- **日期**: 2026-11-04
- **状态**: ✅ 已按本文实现（2026-11-04；v2 按作者反馈补充「可见但克制的重排动画」，verify 全绿 + 逐帧采样通过）
- **前置**: R-173（草稿卡片 AI 状态动画）、R-175（动效规范：不能白闪/乱跳）、R-199（列表换批 `popLayout` 经验）、R-158（删除确认）
- **原则**: 只改删除动画实现；不动删除接口/逻辑/确认弹窗/其它页面；保留被删卡片退场；`verify.sh` 全绿。

## 1. 开发背景

作者反馈「脚本工作台点删除，其他草稿动画会飞出去」。代码检查：

- 草稿网格容器是 `<motion.div layout>`；每张卡片 `DraftTile` 根节点是 `<motion.article layout ...>`，`transition={{ delay: index * 0.03 }}`；
- 删除流程：确认 → `PATCH status=deleted` → `invalidateQueries(['drafts'])` → 列表刷新；
- 被删卡片先播 `exit`（淡出+scale 0.94），**退场期间仍占着原来的格子**；退场结束后从 DOM 移除 → 网格重排 → Framer 对所有剩余卡片的 `layout` 做「旧位置→新位置」投影动画：跨列/跨行移动（单帧 65~372px）、网格高度变化带来非等比 scale，叠加每卡 `delay:index*0.03` 错峰、class 中 CSS `hover:-translate-y-0.5` 与投影 transform 冲突 → 视觉上整片卡片飞动。
- 复现数据（Playwright rAF 逐帧采样）：删除第 1 张后 t≈1014ms 连续多帧出现其它卡片 x 位移 65~372px、`matrix(1,0,0,1.07569,65.221,8.38274)` 等变形。

根因：**误用了 Framer `layout` 投影动画来表达「网格重排」**——网格位置变化本来就是瞬时的，而投影动画会把「大跨度换格」演绎成飞行。

## 2. 涉及的技术

| 技术 | 用途 |
|---|---|
| React 19 + TypeScript | 修改 `pages/drafts/index.tsx` 的列表容器与卡片根节点 |
| Framer Motion | 保留卡片入场（variants）与删除退场（exit）；移除 `layout` 投影；`AnimatePresence mode="popLayout"` 让退场卡不占位 |
| Tailwind CSS Grid | 其余卡片位置变化由浏览器原生重排（一帧完成） |
| Playwright rAF 逐帧采样 | 复现/验证「无多帧飞行」 |
| scripts/verify.sh（lint/vitest/build + 后端） | 门禁 |

无新增依赖、无接口/表/后端改动。

## 3. 开发流程图

```mermaid
flowchart TD
    A[点卡片右下角垃圾桶] --> B[确认弹窗「删除」]
    B --> C[PATCH /api/drafts/{id} status=deleted]
    C -->|失败| D[toast 错误，卡片保留]
    C -->|成功| E[invalidateQueries drafts 重新拉取]
    E --> F[列表数据中该 id 消失]
    F --> G[AnimatePresence popLayout：退场卡移出文档流]
    G --> H[被删卡片 exit 淡出+scale 0.94 约 0.1~0.2s]
    G --> I[其余卡片 CSS Grid 立即重排（一帧，无位置动画）]
    H --> J[退场结束从 DOM 移除]
```

## 4. 数据流转图

```mermaid
flowchart LR
    DB[(drafts 表)] -->|GET /api/drafts| LIST[前端 drafts 列表数据]
    LIST --> RENDER[CSS Grid 渲染卡片]
UAL[作者点击删除] --> API[PATCH /api/drafts/{id} status=deleted]
    API --> DB
    API --> INV[invalidateQueries]
    INV --> LIST
    LIST -->|被删 id 消失| EXIT[该卡 exit 退场]
    LIST -->|其余 id 保留| REFLOW[Grid 一帧重排（无 layout 动画）]
```

说明：本次不改变任何数据字段与接口；只改变「列表变化时如何动画」。

## 5. 实现细节

文件：`frontend_v2/src/pages/drafts/index.tsx`

### 5.1 移除网格容器的 layout 投影

```diff
-                <motion.div layout className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
+                <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
                   <AnimatePresence>
```

- 容器不再对高度/自身布局做投影动画；网格高度变化随浏览器重排即时完成（列表删除场景没有「容器收缩」必要动画）。

### 5.2 卡片改为 `layout="position"`，保留可见的平滑重排（v2）

```diff
-    <motion.article
-      variants={itemVariants}
-      initial="initial"
-      animate="animate"
-      exit={{ opacity: 0, scale: 0.94 }}
-      transition={{ delay: Math.min(index, 12) * 0.03 }}
+    <motion.article
+      layout="position"
+      custom={index}
+      variants={draftTileVariants}
+      initial="initial"
+      animate="animate"
+      exit={{ opacity: 0, scale: 0.96, transition: { duration: 0.16, ease: EASE_OUT_EXPO } }}
+      transition={{ layout: { duration: 0.26, ease: EASE_OUT_EXPO }, duration: 0.26, ease: EASE_OUT_EXPO }}
```

- **`layout="position"`**：只对位置做布局动画，不对尺寸做缩放（旧版普通 `layout` 在跨行时会把高度差做成 scale，叠加错峰后看起来像「飞」）；
- **入场 stagger** 移到本地 `draftTileVariants` 的 `animate` 函数里（`custom={index}`），只作用于 `opacity/y`，不再给 layout 动画加延迟；
- **退场**：`exit` 0.16s 淡出 + scale 0.96，配合 `AnimatePresence mode="popLayout"` 先让出位置；
- **hover**：卡片 class 去掉 `hover:-translate-y-0.5`（CSS transform 与 layout 内联 transform 冲突），保留 `hover:border-accent/40` 高亮反馈。

### 5.3 AnimatePresence 使用 popLayout

```diff
-                  <AnimatePresence>
+                  <AnimatePresence mode="popLayout">
```

- 被删卡片进入退场时**移出文档流**（不占位），其余卡片立刻重排，不会出现「退场 0.3s 后整体再跳一下」的两段式跳动；
- 退场卡片的淡出/缩小仍然可见（约 0.1~0.2s）。

### 5.4 规则 / 阈值 / 降级

| 项 | 规则 |
|---|---|
| 触发删除 | 仅确认弹窗「删除」后；取消/失败不触发 |
| 退场时长 | 沿用 Framer 默认（~0.2s），被删卡片 opacity→0、scale→0.94 |
| 其余卡片 | `layout="position"` 平滑滑到新位置：0.26s、只平移不缩放、同时开始（不做错峰） |
| 快速连续删除 | 每次列表更新独立处理；由于无 layout 投影，不会叠加动画 |
| 数据失败 | 现有 toast 错误 + 列表不变（invalidate 失败也不产生动画） |
| 其它动画 | 入场/stagger、hover、记反馈展开、tab 切换逻辑全部不变 |

## 6. 新增/修改表结构

**无。** 不改 `drafts` 表/列/索引，不需要 Alembic revision，`docs/DATABASE.md` 不变。

## 7. 新增/修改接口

**无。** 删除仍为 `PATCH /api/drafts/{id}`（body `{"status":"deleted"}`），请求/响应/错误码不变；列表仍为 `GET /api/drafts?limit=500`。

## 8. 数据来源与原始字段明细

| # | 页面/功能 | 数据来源 | 原始字段 → 前端字段 | 用途 | 更新时间 | 空值/失败处理 |
|---|---|---|---|---|---|---|
| 1 | 草稿卡片列表 | `drafts` 表 → `GET /api/drafts?limit=500` | `id/title/cover_text/script/source/status/updated_at/debate/quality/...` → `Draft` | 渲染卡片、tab 分组 | 进页面/删除后刷新 | 请求失败 toast；空列表显示空态 |
| 2 | 删除动作 | 作者点击 → 确认弹窗 → `PATCH /api/drafts/{id}` | `{status:"deleted"}` | 逻辑删除（任何 tab 不可见） | 点击确认时 | 失败 toast、卡片保留 |
| 3 | 删除退场动画 | 前端 Framer Motion（程序行为） | 列表数据中该 id 消失 → `exit` | 被删卡片视觉退场 | 删除成功后 | 无 |
| 4 | 其余卡片重排 | 浏览器 CSS Grid（程序行为） | 列表数据变化 | 位置归位 | 删除成功后同一帧 | 无 |

- 不新增第三方数据源；所有字段与更新时机不变，仅动画实现变化。

## 9. 验证与实施记录（2026-11-04）

| 检查项 | 方法 | 结果 |
|---|---|---|
| 删除第 1 张 | Playwright rAF 逐帧采样（`getBoundingClientRect` + `transform` + `opacity`） | ✅ v1 无乱飞；v2 平滑重排可见（12 帧）、无 scale 变形 |
| 删除中间一张 | 同上，3 篇测试草稿删除中间一篇 | ✅ v2：剩余卡片移动 12 帧（约 183ms）、总位移 370px（整列归位）、变换矩阵始终 `1.00x1.00` 纯平移 |
| 被删卡片退场 | 逐帧记录被删卡片 opacity/scale/存在性 | ✅ 0ms opacity≈0.968 → 60ms opacity≈0.003 + scale 0.94 → 120ms 移除 |
| 控制台 | Playwright console/pageerror | ✅ 0 error |
| 其它交互 | 页面点检 | ✅ 卡片入场/hover/tab 计数/记反馈展开正常 |
| 门禁 | `scripts/verify.sh` | ✅ 全绿（后端 758 / 前端 161 / 文档 37 表） |

备注：复现与验证使用临时创建并删除的测试草稿，真实草稿数据未改动；测试草稿已全部逻辑删除清理。
