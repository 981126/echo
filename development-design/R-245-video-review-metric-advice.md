# R-245 开发设计：视频复盘「按指标优化建议」（指标 + 文案结合）

## 1. 开发背景

R-237 已完成视频复盘：程序规则 `video_review_rules` 产出 findings，`video_review_llm.enhance_findings` 用 LLM 只做「整理成小白能懂的中文」，输入只有规则结论，**没有视频文案**；同时对比指标缺「平均播放占比」「收藏率」。因此现有建议偏通用，无法像作者示例那样引用视频里的原话、指出前 3 秒/每 15 秒/结尾怎么改。

本次在**不改现有复盘模块**的前提下，新增「按指标优化建议」：
- 补齐 2 个对比指标；
- 新增独立建议生成模块（规则兜底 + 单次 LLM），把「指标差距 + 文案原句 + 评论高频问题」一起给模型，产出结构化建议；
- 建议随复盘快照一起保存，前端新板块展示。

## 2. 涉及技术

- 后端：Python/FastAPI、SQLAlchemy 2.x、现有 `video_review_*` 服务、`llm_router.primary_llm`、`budget_settings`、`model_settings`。
- 数据：`platform_posts`、`platform_post_stats`、`douyin_post_metrics`、`transcripts`、`platform_post_comments`、`video_reviews.metrics_snapshot`（JSON 文本）。
- 前端：React 19 + TypeScript、现有视频复盘页。
- 无第三方新接口、无新表、无新路由（响应加字段）。

## 3. 开发流程图

```
点「更新数据并分析」
   │
   ├─ (现有) 按账号策略刷新抖音数据（含观看趋势）
   ├─ (现有) build_comparison → metrics/facts/charts
   │        └─ 新增：SPECS 增加 avg_view_proportion、favorite_rate
   ├─ (现有) transcript / comments / comment_questions
   ├─ (现有) build_findings + enhance_findings（润色）
   ├─ (新增) build_metric_advices(comparison, transcript, questions, title)
   │        ├─ 有模型：拼 brief → LLM 输出 advices → 数字/引用校验
   │        │     └─ 校验不过/异常 → 规则兜底
   │        └─ 无模型：直接规则兜底
   ├─ comparison["advices"] = advices
   ├─ (现有) 保存 findings/topics/snapshot
   └─ 前端：GET /api/douyin-review/reviews/{id} → 渲染「按指标优化建议」
```

## 4. 数据流转图

```
douyin_post_metrics (overview 私有指标)      platform_post_stats (公开指标)
        │ avg_view_proportion / finish_rate / follower_gain        │ favorites / plays
        └───────────────┬───────────────────────────────────────────┘
                        ▼
              build_comparison.facts（当前值、近 30 条同发布天数中位数、差值、样本数）
                        │
 transcripts（ASR 文案） ├─→ brief（指标差距文本 + 文案截断 3000 字 + 评论高频问题）
 platform_post_comments ─┘                    │
                                              ▼
                          build_metric_advices（规则 / 单次 LLM + 校验）
                                              │
                                              ▼
                    video_reviews.metrics_snapshot["advices"]（JSON 文本）
                                              │
                                              ▼
                 GET /api/douyin-review/reviews/{id} 响应 advices
                                              │
                                              ▼
                    前端「按指标优化建议」卡片（差距/原因/动作/文案依据）
```

## 5. 实现细节

### 5.1 对比指标补齐（`app/services/video_review_comparison.py`）

| 指标 key | label | unit | 数据来源 | 计算方式 |
|---|---|---|---|---|
| `avg_view_proportion` | 平均播放占比 | ratio | `douyin_post_metrics.avg_view_proportion`（TikHub `fetch_item_overview_data.metrics.avg_view_proportion`） | 直接取数 |
| `favorite_rate` | 收藏率 | ratio | `platform_post_stats.favorites / platform_post_stats.plays`（均真实同步值） | `favorites/plays`，`plays<=0` 时为空 |

- 加入 `SPECS` 与 `_values()`；其余逻辑（中位数、百分位、state 判定）复用现有实现，不改阈值。
- 现有 `_values` 已写入 `likes/comments/favorites/shares` 与多个私有字段，新指标放在同一函数内，避免新增查询。

### 5.2 建议模块（新增 `app/services/video_review_advices.py`）

**维度定义**

| dimension | 指标 key | 卡片标题 | target_metric |
|---|---|---|---|
| completion | finish_rate | 如何优化完播率 | completion |
| avg_view_proportion | avg_view_proportion | 如何优化平均播放占比 | retention |
| favorite_rate | favorite_rate | 如何优化收藏率 | engagement |
| follower_per_1k | follower_per_1k | 如何优化吸粉率 | followers |

**入口**

```python
def build_metric_advices(
    db: Session, comparison: dict, transcript: str,
    comments_questions: list[dict], post_title: str = "",
) -> tuple[list[dict], str, str]:
    """返回 (advices, 使用的模型名, 降级提示)"""
```

**规则兜底（无模型/模型异常/输出不合规时使用）**

- 生成条件（逐维度）：该指标 `value` 非空，且 `state == "low"` 或 `percentile <= 40`；否则跳过。
- 差距文本：`当前{label} {值}，你自己近 30 条相近作品在同发布天数的中位数是 {基准}（低/高 {差值}{相对百分比}；样本 N 条）`；比值型用「个百分点」。
- 原因：①差距事实；②内容推测（用「可能」）：文案开头/结尾/叙述密度/是否缺少清单等，**引用文案原句**。
- 动作：每个维度固定 3 条模板，落点到具体位置：
  - 完播率：前 3 秒前置冲突/结果 → 每 15~20 秒一个信息点 → 中段删重复、结尾提前收束；
  - 平均播放占比：每约 30 秒插实拍素材/截图 → 节点抛轻问题 → 先结论后解释、换画面；
  - 收藏率：提炼 3 条可复用清单 → 结尾可视化清单/进度表 → 关键处提示「可直接收藏照着做」；
  - 吸粉率：结尾 10 秒关注理由 → 粉丝专属资料 → 主页/置顶承接。
- 文案引用选择：按维度关键词命中句子 + 含数字句子 + 首句/尾句，去重后取 ≤3 句；无转写则为空数组。
- `judgement_type = "hypothesis"`（原因含内容推断）；`gap`/`evidence` 为程序计算的真实差距文本。

**LLM 生成（有模型时）**

- 输入 brief（JSON）：
  - `video_title`、`transcript`（截断 3000 字）、`transcript_chars`；
  - `metrics`：4 维度各含 `label/value/baseline/unit/gap_text/percentile/sample_count/state`；
  - `comment_questions`：已有 `comment_questions` 前 5 条。
- 系统提示词硬约束：
  - 只能使用 brief 中的数字与文案原句；禁止编造数字/评论/行业均值/提升幅度；
  - 基准是「发布者自己近 30 条相近作品同发布天数中位数」，**禁止写成同赛道/行业平均**；
  - 内容原因用「可能」；动作必须落到前 3 秒/每 15~30 秒/结尾 CTA 等具体位置。
- 输出 schema：`{"advices":[{"dimension","reasons":[...],"actions":[...],"copy_refs":[...]}]}`（最多 4 条，dimension 白名单）。
- 校验（任一不过 → 丢弃该条/整体回退）：
  1. dimension 在白名单且不重复；`actions >= 2`、`reasons >= 1`；
  2. 输出中所有数字必须在 brief 数字白名单内；
  3. `copy_refs` 每条必须是 `transcript` 的真实子串，至少 1 条；
  4. 校验通过后用 brief 里程序计算的 `gap_text` 覆盖展示差距（保证与程序口径一致）。
- 校验结果：部分条目不合法只丢该条；全部不合法或 LLM 异常 → 规则兜底。

**降级矩阵**

| 情况 | 行为 |
|---|---|
| 未配置模型 | 规则兜底，`warning = 按指标优化建议由程序依据真实指标与文案生成` |
| LLM 超时/异常 | 规则兜底，warning 说明 AI 不可用 |
| LLM 输出不合规 | 规则兜底，warning 说明已改用程序建议 |
| 无转写 | 只出指标卡；前端提示「转写后可结合文案分析」 |
| 可比样本 <5 | 卡片展示真实差距但标「参考样本较少」 |
| 所有维度都不满足生成条件 | `advices=[]`，前端空状态 |

### 5.3 流程接入（`app/services/video_review_service.py`）

在 `run_analysis` 中：
- `questions = comment_questions(comments)` 之后调用 `build_metric_advices(...)`；
- 结果写入 `comparison["advices"] = advices`；
- `warnings` 追加降级提示（仅在有提示时）；
- 保持现有 findings / topics / summary 生成顺序与失败回滚逻辑不变。

`review_out` 响应新增 `advices`：

```python
"advices": snapshot.get("advices", []),
```

### 5.4 前端（`frontend_v2/src/pages/video-review/`）

- `types.ts`：`Review` 增加 `advices?: MetricAdvice[]`；新增类型：

```ts
export interface MetricAdvice {
  dimension: string
  title: string
  target_metric: string
  gap: string
  judgement_type: 'fact' | 'hypothesis'
  reasons: string[]
  actions: string[]
  copy_refs: string[]
  evidence: string[]
}
```

- `index.tsx`：在现有「这条视频为什么好或差？」结论列表之后新增板块：
  - 标题「按指标优化建议」；
  - 卡片：标题 + 判断标记（事实/推测）+ 差距行 + 「原因」列表 + 「具体怎么做」编号列表 + 「文案依据」引用块；
  - `advices` 为空 → 不显示板块或显示空状态（二选一，按最终排版）；
  - 无转写时卡片底部提示「没有文案转写，本次建议只基于指标；转写后可结合文案分析」。
- 风格沿用现有卡片 token（`rounded-xl border bg-card p-4 text-sm`、muted 文字），不改其它模块。

## 6. 新增/修改表结构

**无新增表、无新增列、无需 Alembic 迁移。**

建议数据保存在既有 `video_reviews.metrics_snapshot`（TEXT，存 JSON）内新增 `advices` 字段：

| JSON 字段 | 类型 | 说明 |
|---|---|---|
| `advices` | array | 按指标建议列表，最多 4 条，空数组表示无 |
| `advices[].dimension` | string | completion / avg_view_proportion / favorite_rate / follower_per_1k |
| `advices[].title` | string | 卡片标题 |
| `advices[].target_metric` | string | 对应现有改进计划指标（completion/retention/engagement/followers） |
| `advices[].gap` | string | 程序计算的真实差距说明 |
| `advices[].judgement_type` | string | fact / hypothesis |
| `advices[].reasons` | string[] | 原因（2~4 条） |
| `advices[].actions` | string[] | 具体动作（3~4 条） |
| `advices[].copy_refs` | string[] | 文案原句，必须是转写子串 |
| `advices[].evidence` | string[] | 指标差距证据文本 |

兼容性：旧复盘 `metrics_snapshot` 无 `advices` → 响应返回 `[]`，前端不显示，不影响历史复盘。

## 7. 新增/修改接口

无新增路由。仅 `GET /api/douyin-review/reviews/{id}` 响应新增字段：

```json
{
  "advices": [
    {
      "dimension": "completion",
      "title": "如何优化完播率",
      "target_metric": "completion",
      "gap": "当前完整完播率 7.4%，你自己近 30 条相近作品在同发布天数的中位数是 12.1%（低 4.7 个百分点，相对低 38.8%；样本 10 条）",
      "judgement_type": "hypothesis",
      "reasons": ["…指标差距…", "从文案看，视频开头是「…」，可能先铺垫背景…"],
      "actions": ["把最冲突的结果前置到前 3 秒：现在是「…」…", "…", "…"],
      "copy_refs": ["…视频原句…"],
      "evidence": ["…真实差距文本…"]
    }
  ]
}
```

错误：不变（无主博主/无作品/复盘不存在等沿用现有）。

## 8. 数据来源与原始字段明细

| 展示内容 | 来源 | 原始字段 | 落库字段 | 用途 | 更新时间 | 空值处理 |
|---|---|---|---|---|---|---|
| 完整完播率 | TikHub `fetch_item_overview_data.metrics.completion_rate` | `completion_rate` | `douyin_post_metrics.finish_rate` | 当前值/中位数/差距 | 复盘刷新时 | 空 → 不出卡 |
| 平均播放占比 | TikHub 同接口 `metrics.avg_view_proportion` | `avg_view_proportion` | `douyin_post_metrics.avg_view_proportion` | 同上 | 复盘刷新时 | 空 → 不出卡 |
| 收藏率 | 本地同步的公开统计 | `platform_post_stats.favorites`、`plays` | 同表 | 计算 `favorites/plays` | 同步时 | 分母 0 → 空 |
| 吸粉率 | TikHub `metrics.subscribe_count/unsubscribe_count` 换算的 `follower_gain` + 公开 `plays` | `follower_gain`、`plays` | `douyin_post_metrics.follower_gain` | `follower_gain/plays*1000`（现有口径） | 复盘刷新时 | 空 → 不出卡 |
| 对比基准 | 程序计算 | 上述指标 | 不落库（快照 JSON 内） | 差距文本 | 生成复盘时 | 无可比样本 → 标样本不足 |
| 文案原句 | 本地 ASR | `transcripts.corrected_text` 或 `transcript_text` | 同表 | reasons/copy_refs | 转写完成时 | 无转写 → 不引用 |
| 评论高频问题 | 本地评论 | `platform_post_comments.text/likes` | 同表 | brief 参考 | 评论同步时 | 空 → 不传 |

## 9. 测试、验证与实施计划

**后端测试（`backend/tests/test_r237_video_review.py` 增补）**

1. `build_comparison` 返回的 metrics 含 `avg_view_proportion`、`favorite_rate` 且值与算口径一致；
2. `build_metric_advices`（无模型环境）返回非空 advices：`copy_refs` 全部是 transcript 子串、`gap` 数字与 facts 一致、无「同赛道/行业平均/提升」字样；
3. 数字/引用校验函数单测：构造带未提供数字或伪造引用的候选 → 被丢弃；
4. `review_out` 对旧快照（无 advices）返回 `[]`。

**冒烟/点检**

- 真实作品 1952、1902 各生成一次复盘，检查新板块卡片内容；
- 无转写作品（如未转写的旧作品）检查降级提示；
- 浏览器点检排版（卡片间距/tab 切换不高亮异常）。

**实施步骤**

1. 补 comparison 两个指标 + 测试；
2. 新增 `video_review_advices.py`（规则兜底 + LLM + 校验）＋测试；
3. 接入 `run_analysis` / `review_out`；
4. 前端类型 + 板块渲染；
5. `scripts/verify.sh` 全绿 → 真实复盘冒烟 → 合并 main push。

**风险与对策**

- LLM 输出不稳定/编造 → 数字白名单 + 引用子串校验 + 整体回退规则；
- 上下文过长 → transcript 截断 3000 字，其余只传摘要；
- 额外成本 → 仅每次生成复盘多 1 次 LLM 调用（与现有 enhance_findings 同级），无第三方 API 请求；
- 历史复盘无新字段 → 响应默认 `[]`，兼容旧数据。

## 10. 实现记录（2026-11-02）

| 项 | 落地情况 |
|---|---|
| 对比指标 | `SPECS` 已加 `avg_view_proportion`、`favorite_rate`；两者无独立列，`_values` 从 `douyin_post_metrics.raw.item.metrics` 取；计数缺失时用 raw 的 `view_count/like_count/favorite_count` 补齐，再算比率 |
| 基准回退 | 同发布天数无快照时用「最早可用快照」（设计未写，因私有指标 2026-10-30 才开始记录；`comparison.sample_note` 已注明，避免大多数老作品算不出基准） |
| 标题口径 | 低于自身中位数 →「如何优化 X」；高于/持平 →「如何继续提升 X」；标题里的数值判断用 brief 的 `value_num/baseline_num`，避免格式化字符串无法比较 |
| LLM 校验 | 维度白名单、`actions>=2`、`reasons>=1`、数字 ⊆ brief 数字白名单、`copy_refs` 必须是转写子串；数字白名单额外允许 `time_hints`（前 3 秒 / 每 15~30 秒 / 结尾 10 秒），否则合法的动作会因「3 秒」被误判 |
| 降级 | 未配置模型/模型异常/输出不合规 → 规则兜底；实测第一次真实复盘因旧基准缺失导致 LLM 返回空 advices，回退警告正常显示且不阻塞复盘 |
| 文件清单 | `backend/app/services/video_review_comparison.py`（指标/回退/raw 读取）、`backend/app/services/video_review_advices.py`（新增）、`backend/app/services/video_review_service.py`（接入 + `review_out` 暴露）、`backend/tests/test_r237_video_review.py`、`frontend_v2/src/pages/video-review/{types.ts,index.tsx}` |
| 冒烟 | 作品 1952 真实复盘：4 张卡、每卡 3 条文案引用、无「同赛道/行业平均/提升 X%」；前端点检板块正常渲染、无 console error |
