# R-206 抽屉「讨论（双模型留痕）」tab 的动效修复（入场/跟随/状态条不再重挂）

- **日期**: 2026-09-29
- **状态**: ✅ 已完成（M196）
- **关联**: `frontend_v2/src/pages/drafts/edit-drawer.tsx`、`frontend_v2/src/pages/drafts/draft-ai-status.tsx`、`frontend_v2/src/pages/drafts/discuss-follow.ts`、`frontend_v2/src/components/ui/scroll-area.tsx`；R-173/R-175/R-177/R-199/R-202/R-205

## 原文（作者原话，未改动）
> 草稿页面的双模型讨论的动画很不错，为什么抽屉里面「讨论（双模型留痕）」tab页里面的动画经常不动

## 反问与确认结论（2026-09-29）
作者只提了「为什么」；经无头数值探针定位到三处独立原因并逐条确认了修复范围。

1. **范围**：只修「脚本工作台 → 草稿抽屉 → 讨论（双模型留痕）」tab 的动效；不动讨论业务逻辑与后端。**非目标**：不改草稿卡片（卡片那条本来就顺，是参照物）。
2. **场景**：① 切进该 tab 时；② 讨论进行中新留痕陆续入库时；③ 顶部状态条文案随轮次/步骤变化时。
3. **数据**：不加字段、不加接口；只消费既有 `GET /api/drafts/{id}/discussions` 与 `debate-status`。
4. **边界**：作者向上翻看历史时**不允许**被自动滚动打断；无留痕/未保存草稿/`id` 为空时保持原提示。
5. **验收**：headless 数值探针——切进 tab 有入场帧、新留痕在可视区内播动画、状态条不再出现「两条并存/三点节点被替换」；`scripts/verify.sh` 全绿。
6. **成本/性能**：纯前端；新增一个 24px 阈值判定与一个提示按钮，无额外请求。
7. **依赖/风险**：`ScrollArea` 需要暴露滚动视口 ref（`viewportRef`），是向后兼容的可选 prop。
8. **优先级**：现在做（这是 R-175/R-202 的 DoD 红线：该有的动画没有 = 功能不算完成）。
9. **动效（R-175）**：本需求本身就是动效修复。

### 作者拍板
- 修复范围：**A+B+C 全修**（状态条不再重挂、贴底自动跟随 + 不贴底给「N 条新留痕 ↓」、切进 tab 轻 stagger 入场）。

## 根因（无头探针实测，脚本 `frontend_v2/r202-discuss-tab-motion.mjs`）
- **① 切进 tab 时已有留痕没有入场动画**：列表外层 `AnimatePresence initial={false}` 让首次挂载的整批子元素跳过 `initial → animate`，直接以 `opacity 1 / transform none` 出现（实测 110 帧有留痕、**0 帧在动**）。Radix 每次切 tab 都会卸载重挂 Content，所以每次都是「啪一下全在」。
- **② 讨论进行中新留痕的入场动画播在屏幕外**：滚动区 `max-h-[52vh]` 且不跟随最新，实测 `scrollTop` 恒 0、视口高 494px、内容高 3615→3760px，新行落在可视区**下方 3667~3730px**（≈7 屏）。动画确实播了，只是播在看不见的地方（同 R-199「入场动画在屏幕外播」）。
- **③ 顶部状态条把 `note` 当 key → 每换一步整条重挂**：`key={debate.state + debate.note}` 配上 `DraftAiStatus` 的 `initial={{opacity: 0, height: 0}}`，每次文案更新（写初稿→评审→修订→收口）都「旧条高度收 0 淡出 + 新条从全透明零高度长出」，三点动画节点被替换、从头重播（实测 8s 内 4 次重挂、三点节点被换、34 帧里同时存在两条状态条）。违反动效规范（切换类动画禁止从 `opacity: 0` 起步、不做高度动画）。
- 对照：草稿页卡片的 `DraftAiStatus` 没有 key，三点连续（实测 1.5s 内 91 帧有 64 帧不同）——所以卡片看着顺。

## 做法
- **A 状态条**：`key` 改 `debate.state`（只在 running↔failed 切换时重挂）；`DraftAiStatus` 入场改 `opacity 0.85 / y -4 → 1 / 0`（`softIn`），去掉高度动画。
- **B 跟随最新**：`ScrollArea` 新增可选 `viewportRef`；滚动视口距底 ≤24px 视为「贴底」→ 新留痕自动跟随到底，否则只累加计数并在滚动区右下浮出「N 条新留痕 ↓」按钮（点击平滑滚到底）。切进 tab 且讨论在跑时直接贴底（最新在最下面）。
- **C 入场**：列表 `AnimatePresence initial={false}` 去掉，改成按可见序 `delay = min(index, 5) × 0.03` 的轻 stagger（仍从 `opacity 0.85 + y 10` 起步）。
- 纯逻辑抽到 `pages/drafts/discuss-follow.ts`（`isNearBottom` / `countNewRows`）并单测。

## 排期
M196

## 验收（2026-09-29 通过）
- [x] 切进 tab：留痕有入场帧（`animatingFrames=21`），首帧不透明度 0.85（≥0.6）、落定 `1 / none`
- [x] 新留痕：贴底时自动跟随进可视区（`freshVisible=true`，两次都对）；向上翻看时 `scrollTop` 13 不被抢、浮出「2 条新留痕 ↓」、点击后落到底且提示消失
- [x] 状态条：8s 内 note 文案变了 3 次，`remounts=0 / dotNodeChanges=0 / twoBarFrames=0`（三点动画连续、不再两条并存）
- [x] `scripts/verify.sh` 全绿（含新增 6 例单测）
- [x] 动效规范补记（状态条 key 规则、直播式列表跟随编排、`initial={false}` 吃动画、`TabsContent` 晚一个 commit）
- [x] 探针脚本 `frontend_v2/r206-discuss-tab-motion.mjs`（mock 接口，不花 API 费用，退出码即结论）

## 第二轮返工（2026-09-29，作者反馈「还是一样的没有动画」）
1. **先排除「改动没生效」**：作者用 `/v2`（后端托管 `frontend_v2/dist`），后端访问日志显示其页面加载的入口是
   `/v2/assets/index-DN48QJlf.js`，而该文件在新 dist 里已不存在（当前入口 `index-CPCh5VX7.js`，R-206 代码在 `index-BagAWsLI.js`）
   → SPA 不会自动重新拉包，作者看到的仍是改动前的代码。**已重新 `vite build`**；验收必须在作者实际入口做。
2. **入场动画本身也确实太轻**：第一版单条 `softIn`（0.85→1 + y 10、0.24s）虽全绿但逐帧截图肉眼分辨不出
   → 改回标准列表令牌 `listVariants` + `itemVariants`（`opacity 0→1` + y 14、0.34s、stagger 0.045，与草稿页卡片墙同一套）；
   实测 40 个动画帧 / 32 帧在淡入；截图序列：55ms 整列在淡入 → 188ms 落定。
   判据调整：面板/容器仍守「首帧 ≥0.6 不白闪」，列表子项走 `itemVariants`。
3. 受控 `Tabs` 的副作用：关闭抽屉时显式 `setTab('edit')`，保持「每次打开都从编辑 tab 开始」。

## 第三轮返工（2026-09-29，作者：「前面那三个跳动小点 依旧没有动画」）
- **根因（`/v2` 实测）**：抽屉的状态条外层 `<AnimatePresence initial={false}>` 把子组件 `initial` 置为 false，
  framer 对**关键帧数组**（三点跳动的 `opacity:[0.25,1,0.25]` + `y:[0,-2,0]`、`repeat:Infinity`）只停到第一帧：
  98 帧采样里 `transform`/`opacity` 各 1 种取值、`getAnimations()` 为空；草稿页卡片上同一组件 87/109 帧在动。
  显式补 `initial` **无效**（实测仍冻）。
- **修**：① 去掉状态条那层 `initial={false}`；② `ThinkingDots` 改纯 CSS 关键帧（`index.css`，参数与原版一致）。
- **验证**：`frontend_v2/r206-dots.mjs`（卡片 + 抽屉两处，mock running，不花钱）→ `/v2` 上 92 帧 / 78 帧均有变化。

## 额外发现（未改动，仅记录）
- 讨论 tab 的内容比 `DrawerBody` 可视区高约 40px（上方半屏表单 + 列表 `max-h-[52vh]`），所以 **body 自身要滚**：
  浮层钉在滚动区**底部**会被 body 裁掉一半（27px 胶囊只剩 10px 可见，实测）→ 本需求把「N 条新留痕」钉在**右上角**绕开；
  若后续要根治，需要把讨论 tab 改成「flex 撑满 + 列表 flex-1」的布局（属新需求）。
