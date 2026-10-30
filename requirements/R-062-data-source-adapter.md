# R-062-DATA-SOURCE-ADAPTER: 数据源适配器（TikHub 仅默认，可整体/按平台替换）

- **日期**: 2026-09-05
- **提出渠道**: 对话
- **原文摘要**: tikhub 只是其中一个数据来源，接口要做适配器模式，后续可能直接切数据来源，每个第三方接口都可以单独替换。
- **状态**: ✅ 已完成
- **排期**: M44（已完成）
- **关联**: R-027、ARCHITECTURE §3

## 处理结论（2026-09-05）
1. 新增 `services/platform/base.py`：`DataSource` 统一接口（fetch_profile/fetch_user_posts/fetch_post_stats/fetch_comments/get_balance）+ `PostData/ProfileData` 数据契约（自 tikhub 移入并 re-export 兼容）
2. 注册中心：`register_platform_source(platform, factory)`——`douyin/bilibili/xiaohongshu/default` 任一可单独替换；`make_source(platform)` 运行期取源（override 优先，缺省回落 TikHub）
3. 业务层接线：platform_sync（账号同步/单条同步/本地素材多平台同步/评论）与 platform API（评论刷新/余额）全部改走 `make_source(platform)`，不再直接依赖 TikHub 单例
4. 契约测试：注册/取源/清理（test_core 19 项 + pytest 47 项通过）

## 未来切换方式
- 换整体源：实现一个 `DataSource`，`register_platform_source("default", 工厂)` 即可
- 只换某平台：`register_platform_source("douyin", 工厂)`
- 每个平台可来自不同第三方（如 B站用甲、抖音用乙），互不影响

## 原文（作者原话，未改动）
> 1.C二期开始做
> 2.tikhub只是我其中一个数据来源，接口要做适配器模式，后续可能直接切数据来源，每个第三方接口都可以单独替换
