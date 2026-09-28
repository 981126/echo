# R-199 素材库换批结果卡没有入场动画

- **日期**: 2026-09-28
- **状态**: ✅ 已完成（M188）
- **关联**: `frontend_v2/src/pages/videos/index.tsx`、`videos/material-card.tsx`、`lib/motion.ts`（`listReplace`）；R-179/R-175/R-164

## 原文（作者原话，未改动）
> 1.素材库切换博主查询的时候，查询出来之前会把卡片清掉 这个有动画没问题，但查询出来的结果卡片没有动画

## 根因（无头浏览器逐帧实测）
1. **退场与入场同时发生**：结果到达时旧卡 key 全部消失、新卡 key 全部出现，`AnimatePresence mode="popLayout"`
   把退场卡**绝对定位在原来的格子里**，新卡又立刻在自己的格子里从 `opacity: 0` 淡入 —— 两组卡在同一批网格位置上交叉淡入，
   新卡的入场动画被旧卡的退场动画盖住。实测：可见卡片数全程 ≥20，用户看不到「结果飞进来」。
2. **新卡还额外「隐身」**：入场错峰 `delay = index × 0.035`（最多 0.56s），这段时间新卡一直是 `opacity: 0`，
   叠加第 1 点后半屏看起来就是「卡住了 / 没有动画」。
3. **顺带查出的真 bug（同一处）**：查询 key 用了「下拉里选的博主」(`filters.creatorId`)，而请求参数用的是「点了查询才生效的博主」
   (`applied.creatorId`)。只切博主下拉、没点查询时，key 变了 → 发一次**参数没变**的空请求（实测 `?limit=20`，无 `creator_id`），
   并把上一个博主的数据写进新博主的缓存条目。实测：那种情况下卡片完全不重挂，更没有任何动画。

## 做法
- `lib/motion.ts` 增 `listReplace` 令牌（R-175 要求动效令牌统一）：`exitDuration 0.18`（旧卡快退）、
  `baseDelay 0.2`（新卡等旧卡退干净）、`stagger 0.018`（比首屏更紧凑）、`maxItems 20`（一屏 20 张各自错峰，不留整块同时进场）。
- `MaterialCard` 增 `replace` 属性：退场用显式短过渡（原来退场会继承入场 transition，时长/延迟随 index 乱）；
  换批时入场延迟 = `baseDelay + index × stagger`（只对首批新卡，滚动加载的 append 卡仍走 `softIn` 轻淡入）。
- `index.tsx`：用「首卡 key 变了」判定换了一批结果（`replaced`，ref + effect，不参与渲染副作用），下传 `replace`。
- `index.tsx`：查询 key 收敛为只用 `applied`（= 真正的请求参数），key 与请求不再分叉；切博主下拉不再发空请求，
  与其他筛选一致「点查询才生效」。
- 动效收口：序列 = 旧卡 0.18s 退场 → ~50ms 空档 → 新卡 0.3–0.9s 逐张飞入，全部落到 `opacity 1 / transform none`。

## 验收
- 无头实测逐帧（切换博主 → 查询，真实 110 条数据，console 错误 0）：
  - 只切下拉：**无请求**（修前会发 `?limit=20` 空请求）；
  - 点查询：`?limit=20&creator_id=2`，旧卡 0.54→0.01→0 退场（约 0.15s）→ 空档 ~50ms → 新卡可见数 1→4→7→10→12→15→18→20，t≈900ms 全部落定为 1；
  - 首卡与末卡内容确实换成新博主（`云端连七大姑…`）。
- 单测 `lib/motion.test.ts` 3 例（基础延迟 ≥ 退场时长 / 错峰覆盖一屏 / 总时长 <1s）；`tsc` + `eslint` + `vitest`（46 例）全绿。
- `scripts/verify.sh` 全绿。

## 排期
M188
