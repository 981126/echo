# R-219 博主管理：同步完成/失败条延迟消失 + 跳过博主可见提示

> 📌 2026-09-30：已登记并完成反问确认，作者确认方案并说「开始」，**已完成**（verify 全绿 + headless 点检 13 项全过）。

- **日期**: 2026-09-30
- **状态**: 已完成（2026-09-30）
- **关联**: R-162/R-163（sync-all 队列与并发消费者）、R-070（同步进度条）、R-171（CreatorBlock 外提防 remount）、R-175（动效规范）、R-202（进行中可见）

## 原文（作者原话，未改动）
> 为什么博主管理页面 同步按钮在转圈说明正在同步，但是有些博主下面的进度条没有了、

## 现状排查（实施前）
**根因（两套独立状态，生命周期不同步）**：
1. 进度条唯一显示条件 = 该博主存在 `status=running` 的 SyncJob（`index.tsx:158`，数据来自 4s 轮询 `/api/platform/jobs?status=running`）。
2. sync-all 是**线程池并发**消费（`platform_sync.run_all_top15_sync`），每个博主独立完成：`_finish_job` 把 job 置 done/failed → 立即从 running 列表除名 → ≤4s 后该博主进度条卸载；而整批任务（按钮/顶栏「进行中 N」）仍在转 → 「还在同步但有的条先没了」。
3. 被 skip 的博主（已在运行/无启用账号）**从不建 job**（`enqueue_all_top15_sync`），天生没条；且批次只含「当前主博主+其对标」，其他主博主本来就不参与。
4. 按钮 `syncingAll` 只覆盖 POST 时长，与后台任务无关联。
5. 「排队中」条**已存在**：入队时已为每个博主预置「排队中…」running job（R-163），保持即可。

## 反问与确认结论（2026-09-30）
问：希望如何改进「同步中进度条消失」的体验？作者多选：
1. **完成后延迟消失**：job 完成后进度条不立即消失——done 短暂停留（约 8s）显示「同步完成」再淡出；failed 停留更久（约 60s）显示失败原因。
2. **排队中也显示条**：批次内未开始的博主显示「排队中」条（后端已预置，保持不回退即可）。
3. **跳过者也提示**：被 skip 的博主（已在运行/无启用账号）卡片下显示灰色提示条，而不是无声无息。

**范围边界（作者已确认）**：
- 「同步所有博主前15条」实际只同步「当前主博主+其对标」（R-162 设计），其他主博主卡片不参与批次、本来就不该有条——本次不扩大批次范围。
- 单博主「同步」按钮的 job 由 worker 懒创建，入队到开跑之间的几秒空窗本次不动。

## 方案
### 后端（小改）
- `enqueue_all_top15_sync`：`skipped` 由 `list[str]` 改为结构化 `[{creator_id, name, reason}]`；`/api/platform/sync-all`（platform.py）400 detail 拼接与响应同步适配。
- 进度数据**零改动**：`/api/platform/jobs` 已返回 `status/finished_at`，前端改拉「最近全部状态」即可。

### 前端
- `index.tsx`：
  - jobsQ 改为 `/api/platform/jobs?limit=50`（不再只筛 running）；`runningCreators` 只统计 `status==='running'`；
  - `jobFor`：running → 进度条；done 且 finished_at < 8s → 「同步完成」条；failed 且 < 60s → 失败条；否则 null（历史旧记录不显示）；
  - syncAll() 保存结构化 skipped 到本地 state，博主卡片下渲染灰色虚线提示条（AnimatePresence 软入场）；该博主出现 running job 或下次 sync-all 覆盖时移除；toast 文案适配。
- `sync-progress-bar.tsx`：新增 done（CheckCircle 绿 + 进度 100%）/ failed（XCircle destructive + 错误摘要）形态；沿用现有展开/收起动效，收口 `opacity 1`（DESIGN.md §8）。
- `types.ts`：+`SyncSkipped`。

## 非目标
- 不扩大 sync-all 批次范围（其他主博主不参与，R-162 口径不变）
- 不改单博主同步的懒建 job 行为
- 不改 `/api/platform/jobs` 接口契约（字段不变，前端只是不再传 status 过滤）

## 验收
- [x] sync-all 并发下，先完成的博主进度条变为「同步完成」绿条停留约 8s 后淡出，而不是瞬间消失
- [x] 失败博主显示红色失败条（含原因摘要）停留约 60s
- [x] 排队中的博主持续显示「排队中…」条直到开跑（不回退）
- [x] 被 skip 的博主卡片下出现灰色提示条（注明原因），该博主开跑或下次 sync-all 后移除
- [x] 历史旧完成记录（> 阈值）打开页面时不会误显示
- [x] `test_r162_sync_all_queue.py` 更新且全绿；`scripts/verify.sh` 全绿
- [x] API.md 同步 skipped 结构；动效点检：有动效、流畅、无空白闪帧、落定 opacity 1

## 自测结论（2026-09-30）
- `scripts/verify.sh` 全绿（ruff + mypy + pytest + 前端 lint/tsc/build + 文档一致性 31 表/146 路由）。
- `test_r162_sync_all_queue.py` skipped 结构化断言通过。
- 后端重启加载新代码；`GET /api/platform/jobs?limit=50`（全状态）冒烟 200，返回含 status/finished_at（无时区尾缀北京时间）。
- vite dev 编译改动模块 200；headless 点检 `frontend_v2/r219-sync-progress.mjs`（全 mock 网络，不耗 TikHub 预算）**13 项全绿**：
  排队条/绿条+15/15/红条含原因/旧记录不误显示/落定 opacity=1/done 约 8s 自动淡出且计数连动/running 与 failed 条不受影响/跳过者灰条出现且有 job 者互斥/无页面报错。
- 明确实现细节：done 条同样展示 15/15 计数；跳过灰条与 job 条互斥（有 job 时压住灰条）；
  手动重试该博主 / 切换主博主会清掉对应灰条；时区对无尾缀北京时间补 `+08:00` 再比较。
