# R-217 品牌文案精简：登录页去掉标语与「回声」，侧栏与标签页同步

> ✅ 2026-09-30：已实施完成（M217，**纯前端、后端零改动**）。下面的反问结论与规格为开工依据，**实施记录与自测结论见文末**。

- **日期**: 2026-09-30
- **状态**: ✅ 已完成（2026-09-30 实施，M217；`scripts/verify.sh` 全绿 + `frontend_v2/r217-brand-text.mjs` 对 dev 3000 与生产 dist 8000 各跑一次全绿）
- **关联**: `frontend_v2/src/pages/login.tsx`、`frontend_v2/src/components/layout/sidebar.tsx`、`frontend_v2/index.html`
- **依据**: R-164（frontend_v2 为唯一前端）、R-175（动效规范：该有的不能省、且不得从 `opacity:0` 起步）

## 原文（作者原话，未改动）
> 登陆页的【让 AI 越来越懂你的人设】、【回声】去掉，包括登陆后左上角 【回声】汉字也去掉

## 现状排查（实施前）
| 位置 | 文件:行 | 当前内容 |
|---|---|---|
| 登录页 品牌标题 | `frontend_v2/src/pages/login.tsx:69` | `echo 回声`（`<motion.h1>`） |
| 登录页 标语 | `frontend_v2/src/pages/login.tsx:71-78` | `让 AI 越来越懂你的人设`（`<motion.p>`） |
| 登录后 左上角 | `frontend_v2/src/components/layout/sidebar.tsx:55` | `echo 回声`（`<motion.span>`） |
| 浏览器标签页 | `frontend_v2/index.html:6` | `<title>echo · 回声</title>` |

品牌图标（`Waves`）在登录页（:55-62）与侧栏（:46-48）各有一处，均**保留**。

## 反问与确认结论（2026-09-30）
1. **范围与边界（删到哪一步）**：作者确认**只删「回声」两个字**，`echo` 与图标保留。
   - 登录页标题：`echo 回声` → `echo`
   - 左上角：`echo 回声` → `echo`
2. **浏览器标签页是否在内**：作者确认**一并改**，`index.html` 的 `<title>echo · 回声</title>` → `<title>echo</title>`。
3. **标语**：`让 AI 越来越懂你的人设` **整行删除**（不是隐藏、不是改文案）。
4. **场景与影响**：纯文案删除，不影响登录逻辑（仍校验 `ECHO_ACCESS_TOKEN`）、不影响路由与侧栏折叠行为。
5. **数据**：无需新数据。
6. **边界与异常**：不涉及空数据/失败/重复路径。
7. **动效（R-175 / 反问清单第 9 项）**：删除标语 `<motion.p>` 后，其余入场动画（图标 spring、`h1` 淡入、表单 `y:12` 入场）**保持原样**，品牌块 `gap-3` / `mb-8` 布局参数不改；**不得引入任何从 `opacity:0` 起步的新动画**，收口仍落在 `opacity 1 / transform none`。
8. **非实时返回（R-202 / 反问清单第 10 项）**：本需求不涉及耗时/后台任务，**不适用**。
9. **成本与性能**：零 API 成本、零性能影响（仅少渲染两个文本节点）。
10. **依赖与风险**：无外部依赖；风险极低（纯静态文案）。
11. **优先级**：现在做。
12. **后端**：**零改动**（不涉及接口/表结构，故 `API.md` / `DATABASE.md` 无需同步）。

## 范围（本期）
- `login.tsx:69`：`echo 回声` → `echo`
- `login.tsx:71-78`：删除标语 `<motion.p>` 整块
- `sidebar.tsx:55`：`echo 回声` → `echo`
- `index.html:6`：`<title>echo · 回声</title>` → `<title>echo</title>`

## 非目标（明确不做）
- **不改邮件里的品牌文案**：`【echo】今日选题与脚本…` / `【echo】今日最佳…` / `【echo】…失败` 等主题与正文模板（`backend/app/services/notify.py`）保持原样
- 不改图标 `Waves`、不改配色/布局/间距
- 不改其它页面任何文案
- 不改登录逻辑与鉴权
- 后端零改动（无新接口 / 无新表 / 无新定时任务 / 无 LLM 成本）

## 排期
M217

## 验收（全部通过）
- [x] 登录页只显示「图标 + echo」，**无**「让 AI 越来越懂你的人设」标语（点检：标题块 `innerText` 只剩 `["echo"]`）
- [x] 登录后左上角显示「图标 + echo」（点检：侧栏品牌恰为 `echo`）
- [x] 浏览器标签页标题为 `echo`（点检：`document.title === 'echo'`，dev 3000 与生产 8000 均通过）
- [x] `frontend_v2/` 内 `grep 回声` **无残留**（登录后整页 `body` 文本亦无「回声」）
- [x] 侧栏折叠（`collapsed`）行为不受影响（收起后侧栏 64px、品牌字样隐藏；展开后回到 `echo`）
- [x] 动效点检：登录页入场动画正常（opacity 取值 31–32 种，确实在动）、落定 `opacity 1 / transform none`、无空白闪帧
- [x] `scripts/verify.sh` 全绿（前端 lint + tsc + build + 文档一致性 31 表/146 路由）
- [x] 后端零改动（`git diff` 无 `backend/` 改动）

## 实施记录（2026-09-30）
- **改动**：`frontend_v2/src/pages/login.tsx`（`echo 回声` → `echo`；删除标语 `<motion.p>` 整块）、
  `frontend_v2/src/components/layout/sidebar.tsx`（`echo 回声` → `echo`）、`frontend_v2/index.html`（`<title>echo</title>`）。
- **新增**：点检脚本 `frontend_v2/r217-brand-text.mjs`（playwright；覆盖登录页文案/标签页/图标/入场动效落定 + 侧栏文案/折叠）。
- **动效**：删除标语后未调整任何动画参数（图标 spring、`h1` delay 0.22+0.5、表单 delay 0.4 均保持原样），
  未引入从 `opacity:0` 起步的新动画；品牌块 `gap-3` / `mb-8` 未改。
- **自测**：`scripts/verify.sh` 全绿；`r217-brand-text.mjs` 对 dev(3000) 与生产 dist(8000) **各跑一次全绿**（各 17 项断言）；截图肉眼复核通过。
- **发现的留口（未动）**：登录页卡片下方仍有 `echo v2 · 全新界面预览`（`login.tsx:110`），本次范围未包含。
