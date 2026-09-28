# R-188 每周灵感补给定时推送

- **日期**: 2026-09-28
- **状态**: ✅ 已完成（M177）
- **关联**: `scheduler.py`、`services/opportunity.py`、`services/notify.py`；R-185/R-187

## 原文（作者原话，未改动）
> 做这个系统的初心就是，博主越做越久话题就会越来越少，越来越没灵感
> （R-187 之后）继续

## 目标
R-185/R-187 的灵感需要作者主动去点。本需求让系统**主动**：每周一早上把
「缺口选题 + 每周灵感包」的 Top 选题推送（站内通知 + best-effort 邮件，深链到主页），
降低「想不起来去要灵感」的摩擦。

## 做法
- `services/opportunity.digest_message(pack_items, gap_items, limit)`：把两路灵感拼成可推送文案（纯逻辑，可测）。
- `scheduler._weekly_ideas_job`：每周一 08:30 生成 pack（本地统计）+ gap（AI，失败降级），
  有内容才推送；失败写告警；邮件为次要通道（失败不影响站内通知）。
- 站内通知深链 `/home`（内容机会卡）。

## 验收
- 定时任务注册成功；`digest_message` 单测；任务失败不炸穿、不重复。
- `scripts/verify.sh` 全绿。

## 排期
M177
