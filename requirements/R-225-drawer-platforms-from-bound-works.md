# R-225-DRAWER-PLATFORMS-FROM-BOUND-WORKS: 素材库抽屉平台勾选由绑定作品决定

- **日期**: 2026-10-15
- **提出渠道**: 对话
- **原文摘要**: 素材库里面明明一个视频发了多个平台，而且卡片也展示了多个平台，但抽屉里面平台却没有勾上。
- **状态**: ✅ 已完成
- **排期**: M225
- **关联**: `backend/app/api/videos.py`、`backend/app/services/works_service.py`、`backend/app/api/platform.py`、`frontend_v2/src/pages/videos/edit-drawer.tsx`、R-036/R-179/R-094

## 处理结论

1. **根因**：
   - 卡片平台（云端/合并卡）实时从绑定的 `PlatformPost` 成员推导（`library_service.py:199`）。
   - 抽屉平台勾选读取 `Video.platforms` 数据库列（`edit-drawer.tsx:137`），该列只在创建/绑定/手动保存时写，合并/同步时不会重算，导致与卡片不一致。

2. **修复方向**：
   - `GET /api/videos/{id}` 在存在绑定帖子时，用 `_bound_platform_posts` 推导 `platforms`，与卡片同源。
   - 合并/拆分时持久化刷新 `Video.platforms`，供其它读取方一致。
   - `post_to_material` 改为取帖子所属 work 的全部成员平台。
   - 已绑定平台作品的素材，抽屉里的平台勾选框置为只读，并提示“平台由已绑定的平台作品决定”。

## 原文（作者原话，未改动）

> 素材库 里面明明一个视频发了多个平台，而且卡片也展示了多个平台，但抽屉里面平台却没有勾上，是为什么
