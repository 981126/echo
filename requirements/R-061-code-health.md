# R-061-CODE-HEALTH: 代码与表结构体检优化（批次化，保证逻辑/UI 不变）

- **日期**: 2026-09-05
- **提出渠道**: 对话
- **原文摘要**: 1) 检查所有代码，优化点、冗余设计；2) 表结构规划评估与优化。
- **状态**: 🔨 实施中（批次 A 已完成；B/C/D 待实施）
- **排期**: M43（进行中）
- **关联**: PRD §工程标准、ARCHITECTURE/DESIGN/DATABASE

## 批次划分
- **A（已完成，本批）**：删除死代码 `core/signature.py` 及测试；下线已无前端使用的旧 `bind-link` 单链接接口；补常用索引（platform_posts.local_video_id / publish_time、videos.platform_post_id、notifications.created_at，幂等）；新增每日 04:00 清理（通知90天/后台任务30天/同步记录60天/平台统计400天）
- **B（待实施）**：风格画像与检索索引缓存（按素材版本失效）；post_item 双实现合并收敛；cookie 指标占位通道处理；任务通知统一封装
- **C（待实施）**：大文件拆分（VideosView/CreatorsView 组件化；tikhub/platform_sync 拆模块；前端 composables 统一）
- **D（待实施）**：schema 收敛——绑定关系单事实源(local_video_id)+唯一约束、tags 关联表、raw 归档策略（需备份迁移）
