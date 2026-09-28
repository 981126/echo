# R-192 内容机会进 AI 对话 + 选题归因 + 评论聚类接模型1 语义聚类

- **日期**: 2026-09-28
- **状态**: ✅ 已完成（M181）
- **关联**: `services/opportunity.py`、`services/chat_service.py`、`api/opportunities.py`、主页；R-185/R-187/R-189

## 原文（作者原话，未改动）
> 1.继续 2.继续 3.继续，评论聚类接 embedding模型使用系统中的模型1

## 目标
1. AI 对话里能直接要内容机会三路（聊天式找选题）。
2. 把已发布稿件的表现接入选题归因，让「哪类选题数据好」加权进每周灵感包。
3. 评论聚类升级为**语义聚类**；按作者要求用**系统中的模型1**（实测 DeepSeek 无 `/embeddings`，故用模型1 的 LLM 做语义归并，效果等价且不新增供应商），失败自动回退本地聚类。

## 做法
- **AI 对话工具** `get_content_opportunities(want=comment/weekly/gap/all)`：返回三路灵感；评论簇在对话内用**本地聚类**避免嵌套 LLM。
- **选题归因** `opportunity.topic_attribution`：按 `drafts.tags` 聚合已发布稿件的表现（`drafts.performance`），出 `by_tag/avg_engagement/good_tags/top/bottom`；`_weekly_pack` 对命中「好标签」的灵感 **+15** 并标注理由；`GET /api/opportunities/attribution`；主页「看表现归因」。
- **模型1 语义聚类** `opportunity._llm_comment_clusters`：把清洗后的评论（上限 60 条）编号喂模型1 → 归并成规范问题组；
  硬超时 100s（超时/失败回退本地聚类）；结果缓存 6 小时；每周灵感任务顺带**预热**，界面点开通常即得。
  `GET /api/opportunities/comments?use_llm=true`（默认）；`use_llm=false` 强制本地。
- 主页「内容机会」卡新增「看表现归因」按钮 + 标签表现徽标。

## 验收
- 对话工具/归因/模型1 聚类单测（含无模型降级）；`scripts/verify.sh` 全绿。

## 排期
M181
