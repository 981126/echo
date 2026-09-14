# R-153 素材库洗稿入口收敛：去掉卡片上的洗稿按钮，只保留编辑页

- **日期**: 2026-09-14
- **状态**: ✅ 已完成（2026-09-14，M142）
- **关联**: `frontend/src/components/MaterialCard.vue`、`frontend/src/views/VideosView.vue`；R-152

## 原文（作者原话，未改动）
> 1.保留编辑页面的洗稿，去掉素材卡片上的洗稿按钮

## 背景（承接 R-152）
R-152 ③④ 在素材库加了两处「洗稿」入口：卡片「同步」旁、编辑页 ASR「已转写」旁。作者验收后要求**收敛为一处**——
卡片列表上的洗稿按钮去掉，编辑页的保留。

## 范围
- `MaterialCard.vue`：删除云端卡与本地卡「同步」旁的「洗稿」按钮及 `canRewrite` / `rewritingKey` / `rewrite` 三个 props。
- `VideosView.vue`：移除传给卡片的洗稿 props 与 `canRewriteCard` / `rewriteCard`；**保留**编辑页链路
  （`canRewriteEditing` / `rewriteEditing`、`TranscribeSection` 的「洗稿」按钮、`RewriteDiffModal`、`composables/rewrite.js`）。
- 后端 **零改动**：`POST /api/benchmark/rewrite-source` 与 `VideoOut.creator_id` 继续由编辑页使用。

## 不包含
- 不动编辑页洗稿的任何行为（文案来源、双模型讨论、存草稿、原文对照）。
- 不动博主对标页的洗稿。
- 不改后端接口/表结构（`API.md` / `DATABASE.md` 无变化）。

## 验收标准
- 素材库非主博主的云端卡/本地卡上不再出现「洗稿」（卡片动作只剩同步/拆分/确认标签/删除等）。
- 非主博主素材编辑页 ASR「已转写」旁的「洗稿」仍在、点击行为不变。
- `scripts/verify.sh` 全绿 + 前端点检（卡片 0 个洗稿、编辑页有洗稿）；服务保持运行。

## 排期
M142（前置：M141 / R-152 已完成）
