# 变更记录

## [M2] 2026-09-01 — Web 界面（Vue3 SPA）+ 脚本工作台 + 需求管理 + 时间线 + AI 对话
- 前端 Vue3 + Vite SPA（响应式，手机浏览器可用）：素材库/时间线/脚本工作台/AI 对话/人设档案/需求管理/看板
- 访问令牌登录页 + 路由守卫 + API 封装（X-Access-Token）
- 后端新增：Draft（脚本草稿，AI 原稿留底供改稿差异分析）、ChatMessage（对话历史）模型
- 草稿 API：创建/列表/编辑保存（工作台改写）
- 需求管理 API：读改写 requirements/ 文件（事实源），状态机变更、Web 新建归档 R-xxx
- AI 对话 API：DeepSeek 函数调用，只读工具（搜素材/查详情/查人设/查需求），写操作不执行（权限边界）
- FastAPI 托管前端构建产物（dist 存在时挂载）
- 测试：新增需求文件解析/编号 2 项纯逻辑测试（共 8 项离线可跑）

## [M1] 2026-09-01 — 内容库 + 转写 + 人设初始化（后端）
- 后端 FastAPI 骨架：config（.env 前缀 ECHO_）/ db（SQLite + SQLAlchemy）/ models / schemas / api / services
- 视频导入双通道：`POST /api/videos/upload`（Web 上传）+ `data/inbox/` 文件夹自动监听
- ASR 适配器：`asr_mode=mock`（开发/测试，确定性假转写）与 `aliyun`（FileTrans REST + HMAC 签名，需 NAS 联调）
- 转写 AI 校对：`correct_transcript`（结合原始文案修正行业词，无密钥安全降级）
- AI 预打标签：`PersonaService.suggest_video_tags`（主赛道/是否广告/自定义标签），`tags_confirmed` 待作者确认
- 人设初始化：`persona_init_task`（全量历史转写稿 → tags + redlines，新版本，待作者确认）
- 后台任务：DB 任务表 + 线程池（`start_task`），`/api/tasks` 查询状态
- 健康检查 `/health` + 访问令牌中间件 + CORS
- 脚本 `scripts/transcribe_all.py`：批量登记历史视频并触发转写
- 测试：`tests/test_core.py`（纯逻辑，离线可跑）+ `tests/test_services.py`（mock 外部依赖）

## [M0] 2026-09-01 — 项目脚手架 + 自描述体系 + 需求归档
- AGENTS.md / docs（PRD、ARCHITECTURE、WORKFLOW、DECISIONS、milestones）/ requirements（R-001~R-014）
- scripts/verify.sh 质量门禁；Dockerfile / docker-compose / .env.example / README / update.sh
