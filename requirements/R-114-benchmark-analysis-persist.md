# R-114 对标页「AI分析」结果切页保留

- **日期**: 2026-09-07
- **状态**: ✅ 已完成
- **排期**: M97（已完成，线上 bug 修复）
- **原文**: 博主对标页面，我点击了 ai 分析，切换回来之后动画又没了

## 根因
「AI分析」是同步 LLM 调用，结果只存在前端组件内存 `analysisMap`；切到别的页面组件卸载后，返回时 `load()` 重建并清空，分析结果/进行态全部丢失。

## 修复
- 后端 `POST /api/benchmark/analyze` 接受 `key`（作品单元稳定键），分析成功后把 `{can, reason, suggestion}` 存入 `app_kv`（键 `ba:{owner_id}:{unit_key}`）。
- `GET /api/benchmark/top` / `POST /api/benchmark/prepare` 的每条 item 带上已保存的 `analysis`。
- 前端 `load()` 从返回的 `analysis` 回填 `analysisMap`，切页回来结果仍在；「AI分析」请求发送 `key`。

## 验收
- 点击「AI分析」出结果后切走再回来，结果（能讲/不建议 + 原因 + 洗稿按钮）仍显示。
- `scripts/verify.sh` 全绿。
