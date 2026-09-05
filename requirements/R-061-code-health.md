# R-061-CODE-HEALTH: 代码与表结构体检优化（批次化，保证逻辑/UI 不变）

- **日期**: 2026-09-05
- **提出渠道**: 对话
- **原文摘要**: 1) 检查所有代码，优化点、冗余设计；2) 表结构规划评估与优化。
- **状态**: 🔨 实施中（A ✅；B ✅；C ✅；D-1 ✅；D-2/D-3 待实施）
- **排期**: M43（进行中）
- **关联**: PRD §工程标准、ARCHITECTURE/DESIGN/DATABASE

## 批次划分
- **A（已完成，本批）**：删除死代码 `core/signature.py` 及测试；下线已无前端使用的旧 `bind-link` 单链接接口；补常用索引（platform_posts.local_video_id / publish_time、videos.platform_post_id、notifications.created_at，幂等）；新增每日 04:00 清理（通知90天/后台任务30天/同步记录60天/平台统计400天）
- **B（一期 ✅）**：风格画像文本进程内缓存（素材数量/字数变化失效）；作品统计预取收敛到 `works_service.latest_stats_map`（works/platform 复用）
- **B（二期 ✅）**：TF-IDF 检索索引缓存（素材版本失效）；`_post_item`/`post_item` 合并为统一序列化（works/platform 共用）；未启用 cookie 指标通道不再每日空跑；新增 `tasks.push_notification` 统一通知写入
- **C（一期 ✅）**：后端大文件拆分——tikhub 拆 link_utils、platform_sync 拆 platform_assets 与 platform/budget、数据源适配器接线
- **C（二期 ✅ 部分）**：前端新增 MediaComments 评论子组件并接入素材编辑页评论 Tab
- **C（✅ 主要完成）**：VideosView 抽出 14 个组件/模块（MediaComments/PlatformStats/UploadVideoBar/MaterialCard/CoverEditor/TranscribeSection/PlatformLinksInput/EditActions/TranscriptEditor/TagsInput/MetaFields/CloudVideoPicker/CloudActions/CloudTextArea）；CreatorsView 抽出 CreatorAccountRow/CreatorHeaderRow/CloudPostTile/CloudPostDetail/CreatorFormModal/AccountFormModal；composables+lib 覆盖多页；转素材 500 修复
- **D-1（✅）**：绑定关系收敛——去重 + 唯一部分索引 ux_platform_posts_local_platform + videos.platform_post_id 反向补绑（迁移前已备份）
- **D-2/D-3（待实施）**：tags 关联表、raw 大字段归档
