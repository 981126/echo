# R-196 热点/评论匹配接入「内容立场」

- **日期**: 2026-09-28
- **状态**: ✅ 已完成（M185）
- **关联**: `services/ideas_service.py`；R-072/R-182

## 原文（作者原话，未改动）
> 四层人设重构后，热点/评论匹配规则要同步升级。…应从“内容立场”中提取可编辑的主题关键词，用于判断某个热点或评论是否适合你讲。
> 1.直接用全文提词

## 做法
- `persona_profile` 的关键词来源增加** stance 层标签+描述全文提词**（`words_of`）；赛道词（category=topic）继续计入。
- 红线剔除改为取 `layer == forbidden`（或 category=redline），与四层一致。

## 验收
- 定向测试：stance 标签的词进入 keywords；forbidden 标签进入 avoid；`verify.sh` 全绿。

## 排期
M185
