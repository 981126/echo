# R-066-TIMEZONE-BEIJING: 系统时间统一为北京时间

- **日期**: 2026-09-06
- **提出渠道**: 对话
- **原文摘要**: 现在系统里面像通知的时间不是北京时间，差了8小时，有没有地方统一配置成北京时间
- **状态**: ✅ 已完成
- **排期**: M48
- **关联**: core/timeutil、全部模型时间列、db.py 迁移

## 处理结论
1. 新增统一时间工具 `core/timeutil.now()/today()/tz()`，默认 Asia/Shanghai，可被 `ECHO_TIMEZONE` 覆盖
2. 所有模型 created_at/updated_at/started_at 等 default/onupdate 由 `datetime.utcnow` 改为 `timeutil.now`（存北京时间 naive）；platform_sync / api 等手写 utcnow 调用点同步替换
3. 一次性迁移 `_fix_app_utc_columns`：历史按 UTC 写入的应用时间列 +8h → 北京时间（幂等，Kv 标记 app_tz_migrated_v1，先于任何新写入执行）
4. 验证：通知 03:18(UTC) → 11:18(北京)，与当前时间一致

## 原文（作者原话，未改动）
> 现在系统里面 像通知的时间不是北京时间，差了8小时，有没有地方统一配置成北京时间
