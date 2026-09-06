# R-069-CARD-SYNC-BUTTON-STATE-KEY: 卡片「同步数据」按钮状态用数字 id 撞车，点 A 误触发 B 按钮

- **日期**: 2026-09-06
- **提出渠道**: 对话
- **原文摘要**: 前端点《很多岗位苦是苦了点，但确实给得起钱》的同步按钮，却触发了《用豆包agent选对offer，少走几年弯路》的同步按钮。
- **状态**: ✅ 已完成
- **排期**: M51（已完成）
- **关联**: PRD §3.5、R-067

## 根因
1. 两条卡片在界面里分别是不同类型、但内部编号都是 1：
   - 《很多岗位苦…》= 云端**合并作品卡**（type=work，work_id=1，key=`w1`）
   - 《用豆包agent…》= 云端**单条卡**（type=post，platform_post_id=1，key=`p1`）
2. R-067 把「同步中」loading 状态改成按 `item.id`（纯数字）判断，导致两张卡 id 同为 1 → 点前者同步时，后者的「同步数据」按钮也进入 loading/像被触发。
3. 实际后端请求仍只发给被点的 A（/api/platform/works/1/sync），B 不会被真的同步；这是前端按钮状态误触发，不是请求发错。

## 处理（2026-09-06）
1. 素材库「同步中」状态改用每张卡片**唯一 key**（`w1` / `p1` / `v1`…）判断：`syncing` / `syncingPost` 记录 item.key，MaterialCard loading 与 item.key 比较
2. 本地卡与云端卡统一按 key 判断，避免 video id / post id / work id 跨类型撞车
3. 自测：前端 lint/build 通过，verify.sh 全绿

## 原文（作者原话，未改动）
> 我前端点击《很多岗位苦是苦了点，但确实给得起钱》同步按钮，为什么会触发《用豆包agent选对offer，少走几年弯路》同步按钮
