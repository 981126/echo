# R-174 对标页封面尺寸对齐素材库 / 展示口径改「前3+最新」/ TAB 切换动画

- **日期**: 2026-09-28
- **状态**: ✅ 已完成（2026-09-28，M163）
- **关联**: `frontend_v2/src/pages/benchmark/index.tsx`、`frontend_v2/src/components/ui/tabs.tsx`、
  `backend/app/services/benchmark.py`、`backend/app/api/benchmark.py`；
  R-152（前2+最新口径）、R-109（15 条候选 + 自动补齐）、R-164（前端重设计/动效令牌）

## 原文（作者原话，未改动）
> 1.博主对标的封面图不需要那么大，和素材库的图一样大就行
> 2.博主对标 改为 前3 + 最新一篇，其他逻辑不变
> 3.AI设置、脚本工作台，切换TAB页没有动画

## 现状排查（实测）
1. **封面尺寸**：素材库网格 `grid-cols-2 sm:grid-cols-3 lg:grid-cols-4`（1440 视口 → 封面 265×199），
   对标页网格 `lg:grid-cols-3`（→ 344×258）。"大"的根源是列数不同，不是封面框本身。
2. **展示口径**：`benchmark.target_units` = `ranked[:2]`（互动分前2）+ 最新一篇，重叠时按互动分顺延、`picked[:3]`
   （候选不足 3 条时有多少返回多少）；`ensure_top3_with_text` 同口径，转写补齐保底 3 条有文案（R-152/R-109）。
   前端文案「前2 + 最新一篇」「转写补齐（前2+最新）」；接口 docstring 与 `schema.d.ts` 同步描述同一口径。
3. **TAB 动画**：`components/ui/tabs.tsx` 的 `TabsContent` 只是 `div`（无动效）；全站 6 处 Tabs
   （主页、脚本工作台页、脚本抽屉、素材抽屉、云端作品抽屉、AI 设置）切换时内容瞬切。

## 反问与确认（2026-09-28）
1. **封面怎么对齐** → 作者选：**把对标页网格改成和素材库一致（2/3/4 列）**（1440 下 265×199 逐像素一致，一屏 3→4 张）。
2. **最新一篇已在前 3 时** → 作者选：**顺延补位，固定 4 条**（与现有前2+最新同规则；候选不足时有多少算多少），
   转写补齐同步改为保底 4 条有文案。
3. **TAB 动画范围** → 作者选：**全站统一**（在 `ui/tabs.tsx` 的 `TabsContent` 里加淡入+上移，新页面自动继承）。

## 实施计划（已实施）
- **对标口径（R-152 增补）**：`target_units` → `ranked[:3]` + 最新 + 顺延，`picked[:4]`；
  `ensure_top3_with_text` → 同步改 4 条，函数与字段名去掉 `top3` 字样（`ensure_top_with_text` /
  `top_with_text`），其它规则（15 条候选、广告/同款过滤、有文案优先、缺文案自动下载转写、无文案顺延、
  「最新」按 publish_time）**一律不变**；`/api/benchmark/top`、`/prepare`、重跑任务的文案与 docstring 同步。
- **前端**：对标页网格改 `grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4`；页头与按钮文案「前2」→「前3」。
- **TAB 动画**：`ui/tabs.tsx` 的 `TabsContent` 包一层 `motion.div`（`key=value`，淡入 + y 8px，复用
  `EASE_OUT_EXPO`/0.25s），与全站页面转场风格一致；不做横向滑动，避免与内部列表动效叠加打架。
- **测试/文档**：`tests/test_r152_benchmark_two_plus_latest.py` 断言改 4 条（含重叠顺延、候选不足、有文案优先）；
  API.md、CHANGELOG、milestones 同步；`schema.d.ts` 重新生成。
- **验收**：无头探针量封面尺寸（对标 265×199 == 素材库 265×199）；接口冒烟确认每个对标返回 4 条（不足除外）；
  TAB 切换有入场动画（计算样式 opacity/y 变化、且切换后稳定为 1/0）；`scripts/verify.sh` 全绿 + 服务保持运行。

## 排期
M163

## 验收（实测）
- **封面尺寸**：`/benchmark` 44 张封面框唯一尺寸 **255×191**（原 344×258）；同视口素材库 265×199
  （差 4%，来自对标分区的 Card 内边距；已告知作者，若要像素级一致需把该分区从 Card 里拿出来）。
- **展示口径**：`/api/benchmark/top` 冒烟——11 个对标**全部返回 4 条**（第 4 条=最新一篇），无文案的照旧由
  「转写补齐（前3+最新）」处理；页面每个 section 实测 4 张卡。
- **TAB 动画**：无头实测 AI 设置（10 个 tab）切换 opacity `0.52→1.000`、脚本工作台（4 个 tab）`0.31→1.000`，
  落定 `opacity 1 / transform none`（无卡死）；dom 层确认 Radix 在未选中时卸载 Content → 每次切回都是重新挂载，
  动画必然重播（vitest 用「切回同一 tab 后 wrapper DOM 节点不同」断言这一机制）。
- **单测**：`pytest` **383 passed**（`test_r152` 改为前3口径 + 新增「候选不足返回全部」用例；`test_benchmark_ads`
  补一条正常帖后断言 4 条）；`vitest` 新增 `components/ui/tabs.test.tsx` 3 例；`scripts/verify.sh` 全绿。
- 服务保持运行：后端 8000（重启加载新口径，`/health` 200）、前端 3000。
