# R-165 frontend_v2 线上 bug 修复：素材库卡顿 / 同步·拆分无动画 / 抽屉滚不到底

- **日期**: 2026-09-28
- **状态**: ✅ 已完成（2026-09-28，M154）
- **关联**: `frontend_v2/src/components/ui/drawer.tsx`、`frontend_v2/src/pages/videos/`（index/material-card/use-card-tasks）、
  `frontend_v2/src/pages/chat/index.tsx`；R-164

## 原文（作者原话，未改动）
> 现在页面很多bug，比如点击素材库，页面很卡，点击同步、拆分没有动画，弹出的抽屉，抽屉向下滚动不到底

## 根因与修复（线上 bug，按 AGENTS.md 直接修复并登记）
1. **素材库很卡**：618+ 张卡片全部挂 framer-motion `layout` 动画（任何进度更新都会触发全量布局测量），
   且任务进度每 5s 轮询/SSE 更新都导致整页所有卡片重渲染；无屏外渲染跳过。
   - 修：`MaterialCard` 改 `React.memo`（回调全部 `useCallback` 稳定化，任务状态经 ref 读取的 `hasTask` 判断）；
     去掉卡片/网格 `layout` 动画；仅前 40 张卡有入场动画，其余直接呈现；
     卡片加 `content-visibility: auto` + `contain-intrinsic-size` 跳过屏外渲染。
2. **点击同步/拆分没有动画**：点击后没有本地即时过渡；且没利用同步接口返回的 `media.task_id`
   （老前端有），只在 POST 后盲扫任务列表，有时序竞争；拆分/删除等快操作也无即时反馈。
   - 修：`use-card-tasks` 新增 `begin()` 本地过渡 ramp（点击即显示进度）+ `claim()`（直接用响应里的
     `media.task_id` 接管）+ `finish()`；任务终态经 `onSettled` 回调自动刷新列表；
     拆分/删除加卡片级 spinner 覆盖层即时反馈。
3. **抽屉向下滚动不到底**：自定义 Drawer 用 `position: fixed`，但渲染在带 framer-motion
   `transform/filter`（pageVariants 的 y/blur）的页面容器内——**transform/filter 会使 fixed 相对祖先
   而非视口定位**，抽屉被限制在内容区、高度/滚动异常（截图可见抽屉未覆盖侧栏/顶栏）。
   - 修：Drawer 与聊天重命名弹层改 `createPortal` 挂到 `document.body`。

## 验收
- headless 实测：抽屉 top=0 且覆盖全视口（含侧栏/顶栏遮罩）、滚动可达底部；点同步卡片立即出现
  「数据/评论同步中… 17%」进度覆盖层；618 卡列表滚动流畅；无 console 错误。
- `scripts/verify.sh` 全绿（frontend_v2 vitest 19 例 + tsc/vite build）；服务保持运行。

## 排期
M154
