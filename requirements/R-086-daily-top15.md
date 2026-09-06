# R-086-DAILY-TOP15: 博主页 daily 同步条数改前15条

- **日期**: 2026-09-06
- **提出渠道**: 对话（R-085 后）
- **原文摘要**: 改成同步前15条
- **状态**: ✅ 已完成
- **排期**: M68（已完成）
- **关联**: R-085、platform_sync.run_sync（daily top_n）、CreatorHeaderRow

## 处理
1. `run_sync` daily 默认 top_n 10→15（手动按钮与 07:30/18:00 每日自动一致）；with_media 仍对前 15 条下载视频+转写。
2. 博主页按钮文案「同步前10条」→「同步前15条」。
3. 当前文档（PRD/ARCHITECTURE/DESIGN）同步为 15。
4. verify.sh 全绿；后端已重启。

## 原文（作者原话，未改动）
> 改成同步前15条
