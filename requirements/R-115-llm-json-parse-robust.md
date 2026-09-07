# R-115 AI 分析 JSON 解析健壮性

- **日期**: 2026-09-07
- **状态**: ✅ 已完成
- **排期**: M98（已完成，线上 bug 修复）
- **原文**: ❌ 不建议 AI 分析暂不可用：模型未返回合法 JSON（这是报错了？）

## 根因
对标「AI分析」用生成模型（当前 Kimi k2.6）做 JSON 输出；模型偶发返回非纯 JSON（代码块包裹/前后推理文字/尾注，或推理模型内容落在 reasoning_content），`chat_json` 解析失败即报「模型未返回合法 JSON」。

## 修复
- `llm._parse_json` 增强：先整体解析 → 去 markdown 代码围栏 → 再扫描文本中第一个合法 JSON 对象（兼容前后赘述）。
- `chat_json` 在 content 为空时回退读取 `reasoning_content` 再解析。
- 新增单测覆盖代码块/推理前后缀/非法输入。

## 验收
- `scripts/verify.sh` 全绿；再次点「AI分析」不再因偶发非纯 JSON 而报错。
