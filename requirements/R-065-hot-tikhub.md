# R-065-HOT-TIKHUB: 主页抓取热点走 TikHub 真实热搜

- **日期**: 2026-09-06
- **提出渠道**: 对话
- **原文摘要**: 为什么现在主页抓取更新抓到0条
- **状态**: ✅ 已完成
- **排期**: M47
- **关联**: topic_mining、R-027/R-062、config

## 原因
- .env 配置 `ECHO_HOT_SOURCE_MODE=real`（注释黏在同一行导致值脏），real 模式此前抓抖音/B站/小红书公开热点接口，当前网络下全部失败：抖音 JSON 解析失败、B站 412 反爬、小红书 500 → fetched=0

## 处理结论
1. real 模式优先走 TikHub（已配 ECHO_TIKHUB_API_KEY）：
   - 抖音热搜榜 douyin/app/v3/fetch_hot_search_list（约 50+）
   - B站热搜榜 bilibili/web/fetch_hot_search（约 50）
   - 小红书无公开热搜榜 → 用平台搜索联想词 xiaohongshu/web_v3/fetch_search_suggest（求职/面试/副业/职场/简历/大学生）代表“大众在搜什么”
2. 无 TikHub key 时退回原公开接口；mock 模式不变
3. 修复 .env 该行注释黏连问题

## 原文（作者原话，未改动）
> 为什么现在主页抓取更新 抓到0条
