# R-167 frontend_v2 线上 bug 修复②：草稿抽屉空白（防御）/ AI 对话 [object Object] / 对标封面裂开

- **日期**: 2026-09-28
- **状态**: ✅ 已完成（2026-09-28，M156）
- **关联**: `frontend_v2/src/pages/chat/index.tsx`、`frontend_v2/src/api/client.ts`、
  `frontend_v2/src/components/ui/error-boundary.tsx`（新增）、`frontend_v2/src/pages/drafts/edit-drawer.tsx`、
  `backend/app/services/benchmark.py`、`frontend_v2/src/pages/benchmark/index.tsx`；R-164、R-165

## 原文（作者原话，未改动）
> 脚本工作台明明有草稿，打开却是空白，ai对话进行对话，ai回复我出错了：[object Object]，博主对标页面的封面图是裂开的

## 根因与修复
1. **AI 对话「出错了：[object Object]」**：前端只检查帧内 `data.error` 字段，未显式处理
   `event: error` 帧；且当错误负载是对象/数组（如 FastAPI 422 的 detail 数组、嵌套 error 对象）时，
   `new Error(object)` 的消息就是 `[object Object]`。
   - 修：`chat/index.tsx` 显式处理 `event: error` 帧 + 新增 `errText()` 健壮提取（字符串/对象/嵌套/数组）；
     `api/client.ts` 新增 `detailText()` 统一 detail 提取（含 422 数组）。
2. **对标封面裂开**：后端 `unit_payload` 返回 `post.cover_url`（远端 CDN 防盗链 403）。
   - 修：后端改用 `post.cover_url_local`（本地 `/covers/` 优先、远端兜底）；
     前端各封面 `<img>` 加 `referrerPolicy="no-referrer"`（远端兜底也能加载）。
3. **草稿抽屉空白（防御）**：本地全量复测无法复现（34 篇草稿深链/点击、新建→保存→重开、预览、
   各 tab、深色、生产构建全部正常）。为防止特定内容导致编辑器渲染崩溃时白屏，
   新增 `ErrorBoundary` 组件包住 TipTap 块编辑器——崩溃时降级为纯文本编辑（内容不丢、可保存）。

## 验收
- 对标页封面实测全部加载（headless 截图确认，33 图 24 已加载其余懒加载中、0 张 4xx）；
  错误提取单测 3 例（含 422 数组、嵌套对象、JSON 兜底不含 `[object Object]`）；
  vitest 22 例全绿；`scripts/verify.sh` 全绿；服务保持运行。
- 草稿抽屉空白：若作者仍复现，需补充具体草稿/截图/控制台报错进一步定位（当前已有兜底不白屏）。

## 排期
M156
