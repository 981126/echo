# R-111 账号主页链接 + 素材卡平台标签跳转

- **日期**: 2026-09-07
- **状态**: ✅ 已完成
- **排期**: M94（已完成）
- **原文**:
  1. 博主页面的每个账号，添加一个主页链接，可以让我方便点到博主主页
  2. 素材库卡片上的播放收藏点赞，前面那个平台 label 改为可以点击的，当我点击直接跳转到这个视频对应平台链接

## 实施
1. **博主账号主页链接**：`CreatorAccountRow.vue` 每个账号行新增「主页 ↗」链接——优先用账号已存的 `home_link`，无 `home_link` 时按 `platform + platform_user_id` 兜底构造（抖音/B站/小红书主页地址）；新标签页打开。
2. **素材卡平台标签跳转**：后端 `works_service.post_item`（works/platform 共用序列化）新增 `page_url` 字段（复用 `build_platform_page_url`：B站 bvid/av、抖音 video/share_url、小红书 explore/share_url）；前端 `PlatformStats.vue` 把平台名（抖音/B站/小红书）在 `page_url` 存在时渲染为可点击链接，新标签页打开，点击不触发展开卡片。

## 验收
- 博主页每个账号行出现「主页 ↗」，点击能打开对应博主主页；无链接数据时隐藏。
- 素材库云端卡片（有播放/收藏/点赞指标的）平台名可点击并跳转到对应平台作品页。
- `scripts/verify.sh` 全绿。
