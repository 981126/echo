# R-186 灵感随手记（移动端）

- **日期**: 2026-09-28
- **状态**: ✅ 已完成（2026-09-28，M175）
- **关联**: `inspiration_notes`（新表）、`api/inspiration.py`、`services/inspiration.py`、前端「灵感随手记」页；R-012（移动端）、R-030⑧、R-185

## 原文（作者原话，未改动）
> （R-185 讨论中确认）刷到灵感随手记、语音、聊天截图、亲身经历，才是长期不缺题的原料库。

## 目标
提供一个极低成本的「随手记」入口（手机浏览器/稍后），把一句观察、语音、聊天截图、亲身经历
存进原料库；后台自动发展成「选题 + 初稿」，并入 R-185 的内容机会引擎。

## 范围（待细化）
- 入口：移动端 Web 页面 / 快速记录浮层；
- 输入：文字、语音（复用 ASR）、图片；
- 处理：AI 归类到选题资产、生成候选选题、提示可续写；
- 与 R-185 的原料库/选题账本打通。

## 实施记录（2026-09-28）
- 新表 `inspiration_notes`（creator_id/text/image_url/source/status/draft_id，create_all 自动建，启动自检 31 表）。
- `services/inspiration.refine_topic`：把随手记提炼成一个可直接写的选题标题（LLM 不可用则原样返回，不阻塞）。
- API：`GET/POST /api/inspiration`、`POST /api/inspiration/{id}/develop`（提炼 → `draft_flow.start_generation` 入队生成，标记已用）、`DELETE`。
- 前端新增「灵感随手记」页（响应式、移动端友好）：随手记输入 + 原料库列表 + 一键「生成」（生成后跳脚本工作台）；侧栏/路由/标题接入。
- 测试：`tests/test_r186_inspiration.py`；`scripts/verify.sh` 全绿（31 表 / 139 路由）。
- **未做（后续）**：语音/截图上传（当前支持文本 + 可选图片 URL）；与 R-185 原料库的自动归类暂由「一键生成」承担。

## 排期
M175

