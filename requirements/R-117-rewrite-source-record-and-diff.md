# R-117 洗稿来源记录 + 原文/洗稿左右对照

- **日期**: 2026-09-07
- **状态**: ✅ 已完成
- **排期**: M100（已完成）
- **原文**:
  1. 洗稿后的文案、需要和原文案有个对比窗口
  2. 需要记录这个文案是通过那个素材洗出来的

## 实施
- `drafts` 新增 `source_ref`（JSON：kind/key/source_title/benchmark_name/post_id/work_id），洗稿落库时记录来源素材。
- `DraftOut` 暴露 `original_script` / `source_ref`；草稿列表显示「对标洗稿 · 来源标题」，编辑器新增「原文案」tab。
- 对标页洗稿完成弹窗改为左右对照：前端 `lib/diff.js` 字符级 LCS diff，红色标记被改写/删除，绿色标记新增/修改。

## 验收
- 洗稿弹窗可左右对照并高亮差异；草稿能追溯到来源素材与原文案。
- `scripts/verify.sh` 全绿。
