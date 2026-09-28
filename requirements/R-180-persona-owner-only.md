# R-180 人设只学当前主博主（止血）

- **日期**: 2026-09-28
- **状态**: ✅ 已完成（2026-09-28，M169）
- **关联**: `backend/app/services/ingest.py`；D-028、R-128；触发源于 R-182 复盘

## 原文（作者原话，未改动）
> （讨论「人设档案有用吗」时确认）对标博主的素材也在跑人设分析、待确认建议堆积到约 1800 条 → 先掐断。

## 根因
`ingest.import_video_task` 对**所有**导入视频（含对标博主）调用 `enqueue_persona_incremental`，
`cid` 取 `video.creator_id`，于是每个对标博主都在跑「逐篇提取 + 全量重算」人设分析：
- 白白消耗 LLM 成本（对标素材量比主博主还多）；
- 产出 1,807 条永远用不到的待确认建议（对标博主）+ 216 条无归属历史数据；
- 违反 D-028「对标素材不进主博主人设」。

## 修复
1. `enqueue_persona_incremental`：解析出 `owner_id = current_creator_id(db)`，
   `cid != owner_id`（含无归属）直接返回 `None`，不入队。
2. `persona_init_task` / `persona_incremental_task`：入口强制把 `cid` 纠正回当前主博主，
   兜住历史遗留/异常入队。
3. 一次性清理：删除 `persona_tags` 中 `status='suggested'` 且 `creator_id` 非当前主博主的 1,807 条脏数据
   （清理前已 `scripts/backup.sh` 备份）。

## 验收
- 新增回归测试 `tests/test_r180_persona_owner_only.py`：对标视频不入队；任务 cid 被纠正回主博主。
- 清理后 `persona_tags`：163 条，全部属于主博主（31 style / 4 topic / 9 redline confirmed + rejected 留痕）。
- `scripts/verify.sh` 全绿。

## 排期
M169
